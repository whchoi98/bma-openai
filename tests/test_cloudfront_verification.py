import hashlib
import io
import json
from contextlib import contextmanager
from copy import deepcopy
from urllib.parse import unquote

import httpx
import pytest

from scripts.verify_cloudfront import (
    VerificationError,
    no_cache,
    private_object,
    verify_forwarding,
    verify_sse,
    verify_static,
    verify_upload,
)


def response(body=b"ok", *, cache="no-store", hit=False, age=None):
    headers = {
        "cache-control": cache,
        "x-cache": "Hit from cloudfront" if hit else "Miss from cloudfront",
        "x-amz-cf-id": "sample",
        "x-amz-cf-pop": "ICN57-P1",
    }
    if age is not None:
        headers["age"] = age
    return httpx.Response(200, content=body, headers=headers)


def test_private_response_requires_both_no_store_and_no_cache_hit():
    no_cache(response())
    for candidate in [
        response(cache="public, max-age=60"),
        response(hit=True),
        response(age="2"),
    ]:
        with pytest.raises(VerificationError):
            no_cache(candidate)


def test_static_verification_requires_a_real_hit_and_unchanged_bytes(monkeypatch):
    monkeypatch.setattr("scripts.verify_cloudfront.time.sleep", lambda _: None)

    class Client:
        def __init__(self, responses):
            self.responses = iter(responses)

        def get(self, _):
            return next(self.responses)

    result = verify_static(Client([
        response(cache="public, max-age=60"),
        response(cache="public, max-age=60", hit=True),
    ]), "https://example.cloudfront.net", "/static/app.js")
    assert result["cache_hit"] and result["requests"] == 2
    assert result["pops"] == ["ICN57-P1"]
    with pytest.raises(VerificationError, match="StaticFileChangedBetweenRequests"):
        verify_static(Client([
            response(cache="public"),
            response(b"modified", cache="public", hit=True),
        ]), "https://example.cloudfront.net", "/static/app.js")
    with pytest.raises(VerificationError, match="StaticCacheHitNotObserved"):
        verify_static(Client([response(cache="public")] * 5),
                      "https://example.cloudfront.net", "/static/app.js")


def test_s3_reads_are_owner_bound_size_limited_and_closed():
    class S3:
        def get_object(self, **kwargs):
            assert kwargs == {"Bucket": "bucket", "Key": "key", "ExpectedBucketOwner": "123456789012"}
            self.body = io.BytesIO(b"12345")
            return {"Body": self.body, "ETag": "etag"}

    s3 = S3()
    with pytest.raises(VerificationError, match="StoredObjectTooLarge"):
        private_object(s3, "bucket", "key", "123456789012", maximum=4)
    assert s3.body.closed


def test_terminal_sse_requires_matching_complete_result_without_post():
    class StreamClient:
        @contextmanager
        def stream(self, method, _, headers):
            assert method == "GET"
            events = [
                {"type": "snapshot", "job": {"id": "job", "status": "complete"}},
                {"type": "complete", "job": {"id": "job", "status": "complete"}},
            ]
            result = response("".join("data: " + json.dumps(item) + "\n\n" for item in events).encode())
            result.headers["content-type"] = "text/event-stream"
            yield result

    result = verify_sse(StreamClient(), "https://example.cloudfront.net/events", {}, "job", studio=True)
    assert result["events"] == ["snapshot", "complete"]
    assert not result["new_generation_submitted"]
    with pytest.raises(VerificationError, match="SseWrongResult"):
        verify_sse(StreamClient(), "https://example.cloudfront.net/events", {}, "other", studio=True)


def test_tiny_upload_checks_rejection_filename_and_stored_bytes():
    account = "123456789012"
    upload_id = "b124aab8-3307-4d49-b54c-18890fdb4f62"

    class Client:
        calls = []

        def post(self, url, *, content, headers):
            assert url.endswith("/api/uploads") and len(content) <= 100
            self.calls.append(headers)
            self.payload = content
            self.filename = unquote(headers["X-File-Name"])
            if "Authorization" not in headers:
                result = response(json.dumps({"error": "AuthenticationRequired"}).encode())
                result.status_code = 401
            else:
                result = response(json.dumps({"upload": {
                    "id": upload_id, "name": self.filename, "size": len(content), "extension": "csv",
                }}).encode())
                result.status_code = 201
            return result

    class S3:
        def get_object(self, *, Bucket, Key, ExpectedBucketOwner):
            assert Bucket == "bucket" and ExpectedBucketOwner == account
            if Key.endswith("/data"):
                body = client.payload
            else:
                assert Key == f"uploads/{upload_id}/meta.json"
                body = json.dumps({"id": upload_id, "account_id": account, "app_region": "us-east-1",
                                   "sha256": hashlib.sha256(client.payload).hexdigest()}).encode()
            return {"Body": io.BytesIO(body), "ETag": "sample"}

    client = Client()
    result = verify_upload(client, "https://example.cloudfront.net",
                           {"Authorization": "Bearer sample"}, S3(), "bucket", account)
    assert len(client.calls) == 2 and result["stored_bytes_match"]
    assert result["filename"] == "서울-CDN-검증.csv"
    assert not result["job_started"]


def forwarding_config():
    default = {
        "TargetOriginId": "web", "MinTTL": 0, "DefaultTTL": 0, "MaxTTL": 0, "Compress": False,
        "AllowedMethods": {"Items": ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]},
        "ForwardedValues": {"QueryString": True, "Cookies": {"Forward": "all"}, "Headers": {
            "Items": ["Authorization", "Content-Type", "X-File-Name", "Last-Event-ID", "Origin", "Accept"],
        }},
    }
    public = []
    for pattern in ["/", "/static/*"]:
        item = deepcopy(default)
        item.update(PathPattern=pattern, MaxTTL=3600, Compress=True)
        item["ForwardedValues"]["Headers"]["Items"] = ["Authorization"]
        public.append(item)
    return {"DefaultCacheBehavior": default, "CacheBehaviors": {"Items": public}}


def test_inline_forwarding_preserves_auth_and_disables_dynamic_cache():
    result = verify_forwarding(forwarding_config(), "web")
    assert result["dynamic_ttl_seconds"] == 0
    assert result["viewer_host_excluded"]
    for header in ["Host", "*"]:
        config = forwarding_config()
        config["DefaultCacheBehavior"]["ForwardedValues"]["Headers"]["Items"].append(header)
        with pytest.raises(VerificationError, match="UnsafeAuthorizationOrHostForwarding"):
            verify_forwarding(config, "web")
    config = forwarding_config()
    config["DefaultCacheBehavior"]["MaxTTL"] = 1
    with pytest.raises(VerificationError, match="DynamicCacheTtlNotZero"):
        verify_forwarding(config, "web")
    config = forwarding_config()
    config["DefaultCacheBehavior"]["ForwardedValues"]["Headers"]["Items"].remove("X-File-Name")
    with pytest.raises(VerificationError, match="RequiredDynamicHeadersNotForwarded"):
        verify_forwarding(config, "web")
