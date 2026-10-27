#!/usr/bin/env python3
"""Retire only the Oregon resources recorded by the approved region migration."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, quote

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "artifacts/migration-east"
REGION = "us-west-2"
STACKS = ("bma-seoul-inventory", "bma-seoul-build")
CONFIG = Config(connect_timeout=4, read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 3})


class Retirement:
    def __init__(self):
        self.discovery = json.loads((STATE / "discovery.json").read_text())
        self.account = self.discovery["account_id"]
        assert self.discovery["source_region"] == REGION
        assert self.discovery["destination_region"] == "us-east-1"
        assert (STATE / "previous-reports.zip").is_file()
        self.session = boto3.Session()
        self.verify_account()
        self.stacks = {item["name"]: item for item in self.discovery["stacks"][REGION]}
        assert set(self.stacks) == set(STACKS)
        for name, stack in self.stacks.items():
            assert stack["id"].startswith(f"arn:aws:cloudformation:{REGION}:{self.account}:stack/{name}/")
        self.resources = {
            row["LogicalResourceId"]: row
            for stack in self.stacks.values() for row in stack["resources"]
        }
        self.runtime_id = self.resources["Runtime"]["PhysicalResourceId"]
        self.runtime_arn = f"arn:aws:bedrock-agentcore:{REGION}:{self.account}:runtime/{self.runtime_id}"
        self.role_arn = f"arn:aws:iam::{self.account}:role/{self.resources['SessionRole']['PhysicalResourceId']}"
        self.proof_path = STATE / "cleanup.json"
        self.proof = json.loads(self.proof_path.read_text()) if self.proof_path.exists() else {
            "source_region": REGION, "account_id": self.account, "operations": [],
        }

    def client(self, name):
        return self.session.client(name, region_name=REGION, config=CONFIG)

    def verify_account(self):
        actual = self.session.client("sts", region_name=REGION, config=CONFIG).get_caller_identity()["Account"]
        if actual != self.account:
            raise RuntimeError("AccountMismatch: retirement blocked")

    def record(self, operation, **details):
        row = {"operation": operation, "at": datetime.now(timezone.utc).isoformat(), **details}
        self.proof["operations"].append(row)
        self.proof_path.write_text(json.dumps(self.proof, indent=2) + "\n")
        print(json.dumps(row).replace(self.account, "*********" + self.account[-3:]), flush=True)

    def bma(self, method, path):
        url = f"https://bedrock-mantle.{REGION}.api.aws/openai/v1/agents/sessions{path}"
        request = AWSRequest(method=method, url=url)
        SigV4Auth(self.session.get_credentials().get_frozen_credentials(), "bedrock-mantle", REGION).add_auth(request)
        response = httpx.request(method, url, headers=dict(request.headers), timeout=35)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json() if response.content else {}

    def project_sessions(self):
        query = {"limit": 100, "order": "asc"}
        result, seen = [], set()
        for _ in range(20):
            page = self.bma("GET", "?" + urlencode(query))
            for item in page.get("data", []):
                if (item.get("environment", {}).get("runtime_arn") == self.runtime_arn
                        and item.get("role_arn") == self.role_arn):
                    result.append(item["id"])
            if not page.get("has_more"):
                return result
            cursor = page.get("last_id")
            if not cursor or cursor in seen:
                raise RuntimeError("IncompleteSessionPagination")
            seen.add(cursor)
            query["after"] = cursor
        raise RuntimeError("SessionPaginationLimit")

    def delete_stack(self, name):
        self.verify_account()
        client = self.client("cloudformation")
        identifier = self.stacks[name]["id"]
        try:
            current = client.describe_stacks(StackName=identifier)["Stacks"][0]
        except ClientError as error:
            if "does not exist" in error.response["Error"].get("Message", ""):
                self.record("stack_already_absent", name=name)
                return
            raise
        if current["StackStatus"] == "DELETE_COMPLETE":
            self.record("stack_already_absent", name=name)
            return
        if current["StackStatus"] != "DELETE_IN_PROGRESS":
            current_resources = []
            for page in client.get_paginator("list_stack_resources").paginate(StackName=identifier):
                current_resources.extend(page["StackResourceSummaries"])
            expected = {(r["LogicalResourceId"], r["PhysicalResourceId"]) for r in self.stacks[name]["resources"]}
            actual = {(r["LogicalResourceId"], r["PhysicalResourceId"]) for r in current_resources}
            if actual != expected:
                raise RuntimeError("StackChangedAfterDiscovery")
            client.delete_stack(StackName=identifier)
            self.record("delete_stack_requested", name=name)
        for attempt in range(150):
            time.sleep(8)
            status = client.describe_stacks(StackName=identifier)["Stacks"][0]["StackStatus"]
            if status == "DELETE_COMPLETE":
                self.record("stack_deleted", name=name)
                return
            if status == "DELETE_FAILED":
                failed = [r for r in client.describe_stack_events(StackName=identifier)["StackEvents"]
                          if r["ResourceStatus"] == "DELETE_FAILED"]
                self.record("stack_delete_failed", name=name, failures=[
                    {"logical_id": r["LogicalResourceId"], "reason": r.get("ResourceStatusReason")} for r in failed
                ])
                raise RuntimeError("StackDeleteFailed")
            if attempt % 5 == 0:
                self.record("stack_delete_wait", name=name, status=status)
        raise RuntimeError("StackDeleteTimeout")

    def delete_bucket(self, logical_id):
        self.verify_account()
        name = self.resources[logical_id]["PhysicalResourceId"]
        expected_stack = "bma-seoul-build" if logical_id == "CodeBucket" else "bma-seoul-inventory"
        if not name.startswith(expected_stack + "-"):
            raise RuntimeError("UnexpectedBucketName")
        client = self.client("s3")
        try:
            location = client.get_bucket_location(Bucket=name, ExpectedBucketOwner=self.account)["LocationConstraint"]
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchBucket":
                self.record("bucket_already_absent", name=name)
                return
            raise
        if location != REGION:
            raise RuntimeError("UnexpectedBucketRegion")
        deleted = 0
        # Start from the first page after each deletion, so no deleted cursor is reused.
        for _ in range(30):
            page = client.list_object_versions(Bucket=name, ExpectedBucketOwner=self.account, MaxKeys=1000)
            objects = [{"Key": row["Key"], "VersionId": row["VersionId"]}
                       for row in page.get("Versions", []) + page.get("DeleteMarkers", [])]
            if not objects:
                break
            reply = client.delete_objects(Bucket=name, ExpectedBucketOwner=self.account,
                                          Delete={"Objects": objects, "Quiet": True})
            if reply.get("Errors"):
                raise RuntimeError("BucketObjectDeletionFailed")
            deleted += len(objects)
        else:
            raise RuntimeError("BucketDeletionLimit")
        client.delete_bucket(Bucket=name, ExpectedBucketOwner=self.account)
        self.record("bucket_deleted", name=name, versions_and_markers=deleted)

    def execute(self):
        self.proof["deletion_status"] = "in_progress"
        for session_id in self.project_sessions():
            # Retrieve again before deleting to bind the operation to the recorded Runtime.
            item = self.bma("GET", "/" + quote(session_id, safe=""))
            if item is None:
                continue
            if (item.get("environment", {}).get("runtime_arn") != self.runtime_arn
                    or item.get("role_arn") != self.role_arn):
                raise RuntimeError("SessionOwnershipChanged")
            self.bma("DELETE", "/" + quote(session_id, safe=""))
            self.record("bma_session_deleted", session_id=session_id)
        for name in STACKS:
            self.delete_stack(name)
        for logical_id in ("AppState", "CodeBucket"):
            self.delete_bucket(logical_id)
        self.verify_account()
        repository = self.resources["RuntimeRepository"]["PhysicalResourceId"]
        if repository != "bma-seoul-runtime":
            raise RuntimeError("UnexpectedRepository")
        try:
            self.client("ecr").delete_repository(registryId=self.account, repositoryName=repository, force=True)
            self.record("repository_deleted", name=repository)
        except self.client("ecr").exceptions.RepositoryNotFoundException:
            self.record("repository_already_absent", name=repository)
        web_log = self.resources["WebLogs"]["PhysicalResourceId"]
        for group in [web_log, *self.discovery.get("runtime_log_groups", [])]:
            if group != web_log and not group.startswith("/aws/bedrock-agentcore/runtimes/" + self.runtime_id + "-"):
                raise RuntimeError("UnexpectedLogGroup")
            try:
                self.client("logs").delete_log_group(logGroupName=group)
                self.record("log_group_deleted", name=group)
            except self.client("logs").exceptions.ResourceNotFoundException:
                self.record("log_group_already_absent", name=group)
        if self.project_sessions():
            raise RuntimeError("ProjectSessionsStillPresent")
        self.proof["deletion_status"] = "completed"
        self.record("retirement_completed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    retirement = Retirement()
    if args.execute:
        retirement.execute()
    else:
        print(json.dumps({"region": REGION, "stacks": list(STACKS),
                          "project_sessions": len(retirement.project_sessions()),
                          "execute": False}, indent=2))
