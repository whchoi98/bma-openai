#!/usr/bin/env python3
"""Check CloudFront/OAC delivery, with one tiny upload and no model submissions."""

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

import boto3
import httpx
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
AWS_CONFIG = Config(
    connect_timeout=5, read_timeout=20,
    retries={"mode": "standard", "total_max_attempts": 2},
)
MAX_DOCUMENT = 10 * 1024 * 1024


class VerificationError(RuntimeError):
    """A bounded, credential-free verification failure."""


def require(condition, code):
    if not condition:
        raise VerificationError(code)


def load_json(path):
    return json.loads((ROOT / path).read_text())


def private_object(s3, bucket, key, account, maximum=4_000_000):
    response = s3.get_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    body = response["Body"]
    try:
        require(response.get("ContentLength", 0) <= maximum, "StoredObjectTooLarge")
        data = body.read(maximum + 1)
        require(len(data) <= maximum, "StoredObjectTooLarge")
        return data, response["ETag"]
    finally:
        body.close()


def is_hit(response):
    return "hit from cloudfront" in response.headers.get("x-cache", "").lower()


def no_cache(response):
    require("no-store" in response.headers.get("cache-control", "").lower(),
            "PrivateResponseMissingNoStore")
    require(not is_hit(response), "PrivateResponseWasCached")
    require(response.headers.get("age", "0") == "0", "PrivateResponseHasCacheAge")


def edge_headers(response):
    require(bool(response.headers.get("x-amz-cf-id")), "NotDeliveredThroughCloudFront")
    require(bool(response.headers.get("x-amz-cf-pop")), "CloudFrontPopMissing")


def verify_forwarding(config, origin_id):
    """Validate legacy inline forwarding without consuming custom-policy quota."""
    default = config["DefaultCacheBehavior"]
    public = config.get("CacheBehaviors", {}).get("Items", [])
    require({row.get("PathPattern") for row in public} == {"/", "/static/*"},
            "UnexpectedPublicCachePaths")
    for behavior in [default, *public]:
        require(behavior.get("TargetOriginId") == origin_id, "UnexpectedBehaviorOrigin")
        require(not behavior.get("CachePolicyId") and not behavior.get("OriginRequestPolicyId"),
                "UnexpectedManagedForwardingConfiguration")
        forwarding = behavior.get("ForwardedValues", {})
        headers = {item.lower() for item in forwarding.get("Headers", {}).get("Items", [])}
        require("authorization" in headers and "host" not in headers and "*" not in headers,
                "UnsafeAuthorizationOrHostForwarding")
        require(forwarding.get("QueryString") is True and
                forwarding.get("Cookies", {}).get("Forward") == "all",
                "ViewerQueryOrCookieNotForwarded")
    require(all(default.get(key) == 0 for key in ["MinTTL", "DefaultTTL", "MaxTTL"]),
            "DynamicCacheTtlNotZero")
    require(default.get("Compress") is False, "DynamicCompressionEnabled")
    require({"GET", "HEAD", "POST"} <= set(default.get("AllowedMethods", {}).get("Items", [])),
            "RequiredViewerMethodsNotAllowed")
    headers = {item.lower() for item in default["ForwardedValues"]["Headers"]["Items"]}
    require({"authorization", "content-type", "x-file-name", "last-event-id", "origin", "accept"} <= headers,
            "RequiredDynamicHeadersNotForwarded")
    require(all(row.get("MinTTL") == 0 and row.get("DefaultTTL") == 0 and
                0 < row.get("MaxTTL", 0) <= 3600 for row in public),
            "PublicCacheTtlNotBounded")
    return {"mode": "inline ForwardedValues", "dynamic_ttl_seconds": 0,
            "authorization_preserved": True, "viewer_host_excluded": True,
            "public_paths": sorted(row["PathPattern"] for row in public)}


def verify_static(client, base, path):
    digests, hits, pops = [], [], set()
    for attempt in range(5):
        response = client.get(base + path)
        require(response.status_code == 200, "StaticFileNotAvailable")
        edge_headers(response)
        require("no-store" not in response.headers.get("cache-control", "").lower(),
                "StaticFileUncacheable")
        digests.append(hashlib.sha256(response.content).hexdigest())
        hits.append(is_hit(response))
        pops.add(response.headers["x-amz-cf-pop"])
        if hits[-1]:
            break
        if attempt < 4:
            time.sleep(0.25)
    require(len(set(digests)) == 1, "StaticFileChangedBetweenRequests")
    require(any(hits), "StaticCacheHitNotObserved")
    return {"path": path, "requests": len(hits), "cache_hit": True, "pops": sorted(pops)}


def verify_sse(client, url, headers, expected_id, studio=False):
    events, first_event_seconds = [], None
    started = time.monotonic()
    with client.stream("GET", url, headers=headers) as response:
        require(response.status_code == 200, "SseHttpFailure")
        require("text/event-stream" in response.headers.get("content-type", ""), "SseContentType")
        edge_headers(response)
        no_cache(response)
        for line in response.iter_lines():
            require(time.monotonic() - started < 30, "TerminalSseDeadline")
            require(len(line) <= 4_000_000, "SseEventTooLarge")
            if not line.startswith("data: "):
                continue
            if first_event_seconds is None:
                first_event_seconds = round(time.monotonic() - started, 3)
            event = json.loads(line[6:])
            require(event.get("type") != "error", "SseErrorEvent")
            events.append(event.get("type"))
            require(len(events) <= 10, "UnexpectedNonterminalSse")
            if event.get("type") == "complete":
                result = event.get("job") if studio else event
                require(result.get("id") == expected_id, "SseWrongResult")
                require(result.get("status") in {"complete", "partial"}, "SseResultNotSuccessful")
                break
    require("snapshot" in events and "complete" in events, "TerminalSseIncomplete")
    return {"events": events, "first_event_seconds": first_event_seconds,
            "new_generation_submitted": False,
            "scope": "existing terminal result; not an active long-running stream"}


def verify_upload(client, base, headers, s3, bucket, account):
    """Exercise POST and the UTF-8 filename header without starting a job."""
    payload = b"month,value\nJan,1\nFeb,2\n"
    filename = "서울-CDN-검증.csv"
    upload_headers = {
        "Content-Type": "application/octet-stream",
        "X-File-Name": quote(filename, safe=""),
    }
    rejected = client.post(base + "/api/uploads", content=payload, headers=upload_headers)
    edge_headers(rejected)
    no_cache(rejected)
    require(rejected.status_code == 401 and
            rejected.json().get("error") == "AuthenticationRequired",
            "UnauthenticatedUploadNotRejected")
    response = client.post(base + "/api/uploads", content=payload,
                           headers={**upload_headers, **headers})
    edge_headers(response)
    no_cache(response)
    require(response.status_code == 201, "TinyUploadFailed")
    upload = response.json().get("upload", {})
    require(bool(re.fullmatch(r"[a-f0-9-]{36}", upload.get("id", ""))) and
            upload.get("name") == filename and upload.get("size") == len(payload) and
            upload.get("extension") == "csv", "UploadMetadataMismatch")
    expected_hash = hashlib.sha256(payload).hexdigest()
    raw, _ = private_object(s3, bucket, f"uploads/{upload['id']}/data", account, maximum=100)
    require(hashlib.sha256(raw).hexdigest() == expected_hash, "UploadedBytesChanged")
    raw_meta, _ = private_object(
        s3, bucket, f"uploads/{upload['id']}/meta.json", account, maximum=4096)
    metadata = json.loads(raw_meta)
    require(metadata.get("id") == upload["id"] and metadata.get("account_id") == account and
            metadata.get("app_region") == "us-east-1" and metadata.get("sha256") == expected_hash,
            "StoredUploadMetadataMismatch")
    return {"id": upload["id"], "filename": filename, "bytes": len(payload),
            "sha256": expected_hash, "unauthenticated_denied": True,
            "utf8_filename_preserved": True, "stored_bytes_match": True,
            "job_started": False, "retention": "normal seven-day Studio lifecycle"}


def verify_existing_result(name, manifest, client, base, headers, s3, account):
    if name == "studio":
        proof = load_json("artifacts/studio/live/excel-summary.json")
        job_id = proof["job_id"]
        require(bool(re.fullmatch(r"[a-f0-9-]{36}", job_id)), "InvalidRecordedJob")
        bucket = manifest["outputs"]["StudioBucket"]
        state_key = f"jobs/{job_id}/state.json"
        raw, before_etag = private_object(s3, bucket, state_key, account)
        state = json.loads(raw)
        require(state.get("id") == job_id and state.get("account_id") == account,
                "StoredJobScopeMismatch")
        require(state.get("status") == "complete", "ExistingStudioJobNotComplete")
        result = verify_sse(client, base + f"/api/jobs/{job_id}/events",
                            headers, job_id, studio=True)
        downloads = []
        for artifact in state.get("artifacts", []):
            require(len(downloads) < 15, "TooManyExistingArtifacts")
            artifact_id, key = artifact["id"], artifact["key"]
            require(bool(re.fullmatch(r"[A-Za-z0-9_-]{1,100}", artifact_id)),
                    "InvalidStoredArtifactId")
            require(key.startswith(f"jobs/{job_id}/outputs/") and ".." not in key,
                    "StoredArtifactScopeMismatch")
            source, _ = private_object(s3, bucket, key, account, MAX_DOCUMENT)
            expected_hash = hashlib.sha256(source).hexdigest()
            require(expected_hash == artifact["sha256"], "StoredArtifactHashMismatch")
            url = base + f"/api/jobs/{job_id}/artifacts/{artifact_id}"
            response = client.get(url, headers=headers)
            require(response.status_code == 200, "ArtifactDownloadFailed")
            edge_headers(response)
            no_cache(response)
            require(hashlib.sha256(response.content).hexdigest() == expected_hash,
                    "CloudFrontArtifactHashMismatch")
            require("attachment" in response.headers.get("content-disposition", ""),
                    "ArtifactAttachmentHeaderMissing")
            if artifact["mime"] == "text/html":
                inline = client.get(url + "?view=inline", headers=headers)
                require(inline.status_code == 200, "InlinePreviewFailed")
                no_cache(inline)
                require("inline" in inline.headers.get("content-disposition", ""),
                        "InlineQueryNotForwarded")
                require("sandbox" in inline.headers.get("content-security-policy", ""),
                        "InlineSandboxMissing")
                require(hashlib.sha256(inline.content).hexdigest() == expected_hash,
                        "InlinePreviewHashMismatch")
                result["html_inline_verified"] = True
            downloads.append({"id": artifact_id, "bytes": len(source), "sha256": expected_hash})
        require(downloads and result.get("html_inline_verified"), "ExpectedArtifactsMissing")
        _, after_etag = private_object(s3, bucket, state_key, account)
        require(before_etag == after_etag, "ReadOnlyStudioCheckChangedState")
        result.update(job_id=job_id, artifacts=downloads, job_state_unchanged=True)
        return result

    proof = load_json("artifacts/investigations/live/summary.json")
    investigation_id, run_id = proof["investigation_id"], proof["run_ids"][-1]
    require(all(re.fullmatch(r"[a-f0-9-]{36}", item) for item in [investigation_id, run_id]),
            "InvalidRecordedInvestigation")
    bucket = manifest["outputs"]["StateBucket"]
    prefix = f"investigations/{account}/{manifest['target_region']}"
    state_key = f"{prefix}/turns/{run_id}.json"
    raw, before_etag = private_object(s3, bucket, state_key, account)
    state = json.loads(raw)
    require(state.get("status") in {"complete", "partial"} and state.get("result"),
            "ExistingDeskTurnNotComplete")
    require(state.get("id") == run_id and state.get("investigation_id") == investigation_id,
            "StoredTurnScopeMismatch")
    session_raw, session_etag = private_object(
        s3, bucket, f"{prefix}/sessions/{investigation_id}.json", account)
    require(json.loads(session_raw).get("active_run_id") is None,
            "ExistingInvestigationIsActive")
    result = verify_sse(
        client, base + f"/api/investigations/{investigation_id}/turns/{run_id}/events",
        headers, run_id)
    response = client.get(base + f"/api/runs/{run_id}/report.html?view=preview&theme=dark",
                          headers=headers)
    require(response.status_code == 200, "DeskReportDownloadFailed")
    no_cache(response)
    require("inline" in response.headers.get("content-disposition", ""),
            "DeskPreviewQueryNotForwarded")
    require(account not in response.text, "DeskReportAccountNotMasked")
    _, after_etag = private_object(s3, bucket, state_key, account)
    _, after_session_etag = private_object(
        s3, bucket, f"{prefix}/sessions/{investigation_id}.json", account)
    require(before_etag == after_etag and session_etag == after_session_etag,
            "ReadOnlyDeskCheckChangedState")
    result.update(run_id=run_id, html_preview_verified=True, job_state_unchanged=True)
    return result


def verify_app(name, app, manifest, session, account):
    domain = app["domain"]
    require(bool(re.fullmatch(r"[a-z0-9]+\.cloudfront\.net", domain)),
            "InvalidCloudFrontDomain")
    origin = urlparse(app["origin_url"])
    require(origin.scheme == "https" and
            bool(re.fullmatch(r"[a-z0-9.]+\.lambda-web\.us-east-1\.on\.aws", origin.netloc)),
            "InvalidRecordedOrigin")
    base = "https://" + domain
    cf = session.client("cloudfront", region_name="us-east-1", config=AWS_CONFIG)
    dist = cf.get_distribution(Id=app["distribution_id"])["Distribution"]
    require(dist["Status"] == "Deployed" and dist["DomainName"] == domain,
            "DistributionNotDeployed")
    config = dist["DistributionConfig"]
    require(config["Enabled"] and config.get("PriceClass") != "PriceClass_100",
            "SeoulEdgeNotEnabled")
    origins = [item for item in config["Origins"]["Items"]
               if item["DomainName"] == origin.netloc]
    require(len(origins) == 1 and origins[0].get("OriginAccessControlId"),
            "ExpectedOacOriginMissing")
    oac = cf.get_origin_access_control(
        Id=origins[0]["OriginAccessControlId"])["OriginAccessControl"]["OriginAccessControlConfig"]
    require(oac["SigningBehavior"] == "always-amz-auth" and
            oac["SigningProtocol"] == "sigv4" and oac["OriginAccessControlOriginType"] == "lambda",
            "IncorrectLambdaWebOac")
    forwarding = verify_forwarding(config, origins[0]["Id"])
    token = load_json(manifest["secret_file"])["app_access_token"]
    headers = {"Authorization": "Bearer " + token}
    api_path = "/api/config" if name == "studio" else "/api/context"
    with httpx.Client(timeout=httpx.Timeout(35, connect=10), follow_redirects=False) as client:
        direct = client.get(app["origin_url"].rstrip("/") + "/")
        require(direct.status_code == 403, "DirectOriginStillPublic")
        # A valid app key must also fail when the viewer bypasses CloudFront.
        direct_auth = client.get(app["origin_url"].rstrip("/") + api_path, headers=headers)
        require(direct_auth.status_code == 403, "AppKeyBypassesOriginProtection")
        shell = client.get(base + "/")
        require(shell.status_code == 200 and "<html" in shell.text.lower(), "PublicShellFailed")
        edge_headers(shell)
        static = [verify_static(client, base, path) for path in
                  ["/static/app.js", "/static/fonts/NanumSquareB.otf"]]
        for request_headers in [{}, headers, headers, {}, {"Authorization": "Bearer invalid-cdn-test"}]:
            response = client.get(base + api_path, headers=request_headers)
            no_cache(response)
            edge_headers(response)
            if request_headers == headers:
                require(response.status_code == 200, "ViewerAuthorizationNotPreserved")
                data = response.json()
                require(data.get("model") == manifest["model"] and
                        data.get("app_region") == "us-east-1", "AppConfigurationChanged")
                if name == "desk":
                    require(data.get("account_id") == account and
                            data.get("target_region") == "ap-northeast-2", "DeskScopeChanged")
            else:
                require(response.status_code == 401 and
                        response.json().get("error") == "AuthenticationRequired",
                        "UnauthenticatedApiNotRejected")
        s3 = session.client("s3", region_name="us-east-1", config=AWS_CONFIG)
        existing = verify_existing_result(name, manifest, client, base, headers, s3, account)
        upload = verify_upload(client, base, headers, s3, manifest["outputs"]["StudioBucket"],
                               account) if name == "studio" else None
    return {
        "status": "passed", "domain": domain, "distribution_id": app["distribution_id"],
        "model": manifest["model"], "signing_behavior": oac["SigningBehavior"],
        "price_class": config.get("PriceClass", "PriceClass_All"),
        "forwarding": forwarding,
        "direct_origin_denied": True, "direct_origin_with_app_key_denied": True,
        "viewer_authorization_preserved": True, "authenticated_responses_uncached": True,
        "static": static, "existing_result": existing, "model_requests_submitted": 0,
        **({"tiny_upload": upload} if upload else {}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", default="artifacts/cloudfront/deployment.json")
    parser.add_argument("--output", default="artifacts/cloudfront/verification.json")
    parser.add_argument("--app", choices=["desk", "studio"])
    args = parser.parse_args()
    deployment = load_json(args.deployment)
    names = [args.app] if args.app else ["desk", "studio"]
    manifests = {name: load_json(deployment["apps"][name]["deployment_manifest"]) for name in names}
    accounts = {manifest["outputs"]["ExpectedAccountId"] for manifest in manifests.values()}
    require(len(accounts) == 1, "DeploymentAccountMismatch")
    account = accounts.pop()
    session = boto3.Session()
    actual = session.client("sts", region_name="us-east-1", config=AWS_CONFIG).get_caller_identity()["Account"]
    require(account == actual, "CallerAccountMismatch")
    result = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
              "vantage": "current execution environment; not a Seoul latency measurement", "apps": {}}
    for name in names:
        try:
            result["apps"][name] = verify_app(
                name, deployment["apps"][name], manifests[name], session, account)
        except Exception as cause:
            code = str(cause) if isinstance(cause, VerificationError) else type(cause).__name__
            result["apps"][name] = {"status": "failed", "error": code}
            result["status"] = "failed"
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
