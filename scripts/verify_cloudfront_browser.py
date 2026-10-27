#!/usr/bin/env python3
"""Open both CloudFront apps and an existing document; block every API mutation."""

import argparse
import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def load(path):
    return json.loads((ROOT / path).read_text())


def check_browser_storage(page, token, account):
    value = page.evaluate("""() => ({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage))
    })""")
    encoded = json.dumps(value)
    require(token not in encoded and account not in encoded, "SensitiveBrowserStorage")
    return {"local_keys": sorted(value["local"]), "session_keys": sorted(value["session"])}


def screenshot(page, path, token, account):
    body = page.locator("body").inner_text()
    require(token not in body and account not in body, "SensitiveVisibleContent")
    page.screenshot(path=str(path), full_page=True, animations="disabled",
                    mask=[page.locator("#access-key:visible")], mask_color="#dfe5ef")


def completed_studio_job(session, manifest, account):
    proof = load("artifacts/studio/live/excel-summary.json")
    job_id = proof["job_id"]
    require(bool(re.fullmatch(r"[a-f0-9-]{36}", job_id)), "InvalidExistingJobId")
    s3 = session.client("s3", region_name="us-east-1", config=Config(
        connect_timeout=5, read_timeout=20,
        retries={"mode": "standard", "total_max_attempts": 2},
    ))
    response = s3.get_object(Bucket=manifest["outputs"]["StudioBucket"],
                             Key=f"jobs/{job_id}/state.json", ExpectedBucketOwner=account)
    body = response["Body"]
    try:
        raw = body.read(4_000_001)
        require(len(raw) <= 4_000_000, "StoredJobTooLarge")
    finally:
        body.close()
    state = json.loads(raw)
    require(state.get("id") == job_id and state.get("account_id") == account and
            state.get("status") == "complete", "ExistingJobNotSafelyComplete")
    return state


def check_app(browser, name, app, manifest, account, output, existing=None):
    domain = app["domain"]
    require(bool(re.fullmatch(r"[a-z0-9]+\.cloudfront\.net", domain)), "InvalidCloudFrontDomain")
    token = load(manifest["secret_file"])["app_access_token"]
    context = browser.new_context(viewport={"width": 1512, "height": 1080},
                                  accept_downloads=True, service_workers="block",
                                  reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(30000)
    errors, blocked, responses = [], [], []

    def safe_text(value):
        return str(value).replace(token, "[redacted]").replace(account, "*********" + account[-3:])

    def guard(route):
        request = route.request
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            blocked.append({"method": request.method, "path": urlparse(request.url).path})
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def observe(response):
        request = response.request
        parsed = urlparse(response.url)
        if parsed.hostname == domain and parsed.path.startswith("/api/"):
            responses.append({"path": parsed.path, "status": response.status,
                              "method": request.method})

    context.route("**/api/**", guard)
    page.on("pageerror", lambda error: errors.append(safe_text(error)))
    page.on("response", observe)
    started = time.monotonic()
    try:
        navigation = page.goto("https://" + domain, wait_until="domcontentloaded", timeout=45000)
        require(navigation is not None and navigation.status == 200, "BrowserNavigationFailed")
        require(bool(navigation.header_value("x-amz-cf-id")), "BrowserBypassedCloudFront")
        pop = navigation.header_value("x-amz-cf-pop")
        shell_ms = round((time.monotonic() - started) * 1000)
        expect(page.locator("#access-key")).to_be_visible()
        page.locator("#access-key").fill(token)
        api_path = "/api/config" if name == "studio" else "/api/context"
        with page.expect_response(lambda response: urlparse(response.url).path == api_path
                                  and response.status == 200) as connection:
            page.locator("#connect").click()
        configuration = connection.value.json()
        require(configuration.get("model") == manifest["model"], "BrowserModelMismatch")
        screenshots = []
        if name == "desk":
            expect(page.locator("#model-id")).to_have_text(manifest["model"])
            expect(page.locator("#account")).to_have_text("*********" + account[-3:])
            expect(page.locator("#submit")).to_be_enabled()
            for lang, theme in [("ko", "light"), ("en", "dark")]:
                if lang == "en":
                    page.locator("#language-toggle").click()
                    page.locator("#theme-toggle").click()
                expect(page.locator("html")).to_have_attribute("lang", lang)
                expect(page.locator("html")).to_have_attribute("data-theme", theme)
                filename = f"desk-{lang}-{theme}.png"
                screenshot(page, output / filename, token, account)
                screenshots.append(filename)
            extra = {"masked_account": "*********" + account[-3:]}
        else:
            expect(page.locator("#model-info")).to_contain_text(manifest["model"])
            expect(page.locator("#access-control")).not_to_have_attribute("open", "")
            job_id = existing["id"]
            button = page.locator(f'#history [data-job-id="{job_id}"]')
            # The known completed example is normally in the first ten entries.
            # Page through at most three bounded pages without opening other jobs.
            for _ in range(3):
                try:
                    expect(button).to_be_visible(timeout=5000)
                    break
                except AssertionError:
                    more = page.locator("#load-more")
                    require(more.is_visible(), "KnownCompletedJobNotInHistory")
                    with page.expect_response(lambda response: "/api/jobs?" in response.url):
                        more.click()
            expect(button).to_be_visible()
            button.click()
            expect(page.locator("#job-result")).to_be_visible()
            expect(page.locator("#artifact-list .artifact-card")).to_have_count(len(existing["artifacts"]))
            html = next(item for item in existing["artifacts"] if item["mime"] == "text/html")
            page.locator(f'[data-artifact-id="{html["id"]}"] .artifact-main').click()
            expect(page.locator("#preview-frame")).to_be_visible()
            expect(page.frame_locator("#preview-frame").locator("h1")).to_be_visible()
            require(page.locator("#preview-frame").get_attribute("sandbox") == "",
                    "HtmlPreviewSandboxChanged")
            require(page.locator("#preview-frame").get_attribute("src").startswith("blob:"),
                    "HtmlPreviewNotLocalBlob")
            pptx = next(item for item in existing["artifacts"] if item["filename"].endswith(".pptx"))
            with page.expect_download() as download:
                page.locator(f'[data-download="{pptx["id"]}"]').click()
            downloaded = output / "studio-existing-document.pptx"
            download.value.save_as(downloaded)
            require(hashlib.sha256(downloaded.read_bytes()).hexdigest() == pptx["sha256"],
                    "BrowserDownloadHashMismatch")
            with zipfile.ZipFile(downloaded) as archive:
                require(archive.testzip() is None, "BrowserDownloadInvalidOffice")
            for lang, theme in [("ko", "light"), ("en", "dark")]:
                if lang == "en":
                    page.locator("#language").select_option("en")
                    page.locator("#theme-toggle").click()
                expect(page.locator("html")).to_have_attribute("lang", lang)
                expect(page.locator("html")).to_have_attribute("data-theme", theme)
                filename = f"studio-{lang}-{theme}.png"
                screenshot(page, output / filename, token, account)
                screenshots.append(filename)
            extra = {"job_id": job_id, "html_preview": True, "html_sandbox": "",
                     "download": {"filename": downloaded.name, "sha256": pptx["sha256"],
                                  "bytes": downloaded.stat().st_size}}
        storage = check_browser_storage(page, token, account)
        page.set_viewport_size({"width": 390, "height": 844})
        require(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"),
                "MobileHorizontalOverflow")
        mobile = f"{name}-mobile.png"
        screenshot(page, output / mobile, token, account)
        screenshots.append(mobile)
        require(not blocked, "BrowserAttemptedApiMutation")
        require(not errors, "BrowserJavaScriptErrors")
        require(not any(item["status"] >= 500 for item in responses), "BrowserApiServerError")
        return {"status": "passed", "domain": domain, "model": manifest["model"],
                "cloudfront_pop": pop, "initial_dom_milliseconds": shell_ms,
                "api_mutations": blocked, "javascript_errors": errors,
                "mobile_overflow": False, "browser_storage": storage, "screenshots": screenshots,
                "api_request_count": len(responses), **extra}
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment", default="artifacts/cloudfront/deployment.json")
    parser.add_argument("--output", default="artifacts/cloudfront/browser")
    args = parser.parse_args()
    deployment = load(args.deployment)
    manifests = {name: load(app["deployment_manifest"]) for name, app in deployment["apps"].items()}
    accounts = {item["outputs"]["ExpectedAccountId"] for item in manifests.values()}
    require(len(accounts) == 1, "DeploymentAccountMismatch")
    account = accounts.pop()
    session = boto3.Session()
    actual = session.client("sts", region_name="us-east-1").get_caller_identity()["Account"]
    require(actual == account, "CallerAccountMismatch")
    existing = completed_studio_job(session, manifests["studio"], account)
    output = ROOT / args.output
    output.mkdir(parents=True, exist_ok=True)
    proof = {"status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
             "model_submissions": 0,
             "stream_scope": "Existing completed content only; no active generation or long-running SSE tested.",
             "vantage": "current execution environment; not a Seoul latency measurement", "apps": {}}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            for name in ["desk", "studio"]:
                proof["apps"][name] = check_app(
                    browser, name, deployment["apps"][name], manifests[name], account, output, existing)
        except Exception as cause:
            proof["status"] = "failed"
            # Playwright assertion messages can contain DOM text; keep only the
            # exception type, or our fixed failure code, in persisted output.
            proof["error"] = str(cause) if type(cause) is RuntimeError else type(cause).__name__
        finally:
            browser.close()
            (output / "summary.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(proof, ensure_ascii=False, indent=2), flush=True)
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
