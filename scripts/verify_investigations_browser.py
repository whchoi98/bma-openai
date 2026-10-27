#!/usr/bin/env python3
"""One bounded live investigation, reload recovery, and saved-report UI checks.

Run explicitly with:
    .venv/bin/python scripts/verify_investigations_browser.py

This script submits exactly one new Korean operations-report request. It never
submits a follow-up or retries a POST. All later checks use saved results and GET
requests. Secrets are read locally, never printed, and excluded from artifacts.
"""

import hashlib
import json
import os
import re
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/investigations/browser"
MODEL = "openai.gpt-6-luna"
PROCEDURES = {"inventory", "service-health", "security-review", "operations-report"}
TERMINAL = {"complete", "partial", "failed", "cancelled", "uncertain"}
PROMPT = (
    "운영 보고서 절차로 서울 리전의 ALARM 상태 CloudWatch 알람만 확인해 줘. "
    "처음에 get_account_context를 한 번 호출하고, "
    'list_cloudwatch_alarms(state="ALARM")를 한 번 호출해 최대 2개만 조회해 줘. '
    "위 두 도구 외에는 어떤 도구도 호출하지 마. "
    "다른 서비스, 지표, 로그, 비용, 알람 상세 추가 조회는 하지 마. "
    "조회 결과가 없으면 빈 결과라고 쓰고 추가 조회는 하지 마. "
    "한국어로 조회 범위, 실제 관측 시각의 UTC 원본과 Asia/Seoul 표시, "
    "근거 API, 잘림 여부와 미조회 범위를 정리해 줘. "
    "ALARM 개수나 애플리케이션 정상 여부를 추측하지 마."
)

# This observer copies public responses into page memory only. It neither
# changes requests nor writes localStorage, sessionStorage, cookies, or headers.
OBSERVER = r"""
(() => {
  const proof = window.__investigationBrowserProof = {
    snapshot: null, final: null, events: [], readErrors: 0
  };
  const append = (event) => {
    if (event.type === "snapshot") proof.snapshot = event;
    if (event.type === "complete") proof.final = event;
    if (proof.events.length < 1000) proof.events.push({
      type: event.type, at: performance.now(),
      investigation_id: event.investigation?.id || event.investigation_id,
      run_id: event.run?.id || event.id,
      status: event.run?.status || event.status,
      phase: event.run?.phase,
      answer_characters: event.run?.answer?.length,
      evidence_count: event.run?.evidence?.length,
      code: event.type === "error" ? event.code : undefined
    });
  };
  const original = window.fetch;
  window.fetch = async (...args) => {
    const response = await original(...args);
    const input = args[0] instanceof Request ? args[0].url : String(args[0]);
    const url = new URL(input, window.location.href);
    if (url.origin !== window.location.origin ||
        !url.pathname.startsWith("/api/investigations")) return response;
    const copy = response.clone();
    const contentType = copy.headers.get("content-type") || "";
    if (contentType.includes("text/event-stream") && copy.body) {
      (async () => {
        const reader = copy.body.getReader(), decoder = new TextDecoder();
        let buffer = "";
        try {
          while (true) {
            const {value, done} = await reader.read();
            buffer = (buffer + decoder.decode(value, {stream: !done}))
              .replace(/\r\n/g, "\n");
            if (buffer.length > 4000000) throw new Error("ResponseTooLarge");
            let end;
            while ((end = buffer.indexOf("\n\n")) !== -1) {
              const frame = buffer.slice(0, end);
              buffer = buffer.slice(end + 2);
              const data = frame.split("\n")
                .filter(line => line.startsWith("data:"))
                .map(line => line.slice(5).trimStart()).join("\n");
              if (data) append(JSON.parse(data));
            }
            if (done) break;
          }
        } catch { proof.readErrors++; }
        finally { await reader.cancel().catch(() => {}); }
      })();
    } else if (response.ok && contentType.includes("application/json")) {
      copy.json().then(value => {
        if (value.investigation && value.run)
          append({type: "snapshot", ...value});
      }).catch(() => { proof.readErrors++; });
    }
    return response;
  };
})();
"""


class VerificationFailure(Exception):
    """A fixed, non-sensitive failure code suitable for a private summary."""


def require(condition, code):
    if not condition:
        raise VerificationFailure(code)


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def redact(value, secret, account):
    if isinstance(value, dict):
        return {key: redact(item, secret, account) for key, item in value.items()
                if key.lower() not in {"authorization", "access_token", "app_access_token"}}
    if isinstance(value, list):
        return [redact(item, secret, account) for item in value]
    if isinstance(value, str):
        return value.replace(secret, "[redacted]").replace(account, "*********" + account[-3:])
    return value


def proof_of(page):
    return page.evaluate("() => window.__investigationBrowserProof")


def storage_of(page):
    return page.evaluate("""() => ({
      local: Object.fromEntries(Object.entries(localStorage)),
      session: Object.fromEntries(Object.entries(sessionStorage))
    })""")


def verify_storage(page, investigation_id, secret, account):
    stored = storage_of(page)
    allowed = {"aws-desk-last-investigation", "aws-desk-language", "aws-desk-theme"}
    require(set(stored["local"]) <= allowed, "UnexpectedLocalStorage")
    require(not stored["session"], "UnexpectedSessionStorage")
    require(stored["local"].get("aws-desk-last-investigation") == investigation_id,
            "LastInvestigationNotPersisted")
    encoded = json.dumps(stored, ensure_ascii=False)
    require(secret not in encoded and account not in encoded and PROMPT not in encoded,
            "SensitiveBrowserStorage")
    return stored


def check_display(page, account, secret):
    visible = page.locator("body").inner_text()
    require(account not in visible and secret not in visible, "SensitiveVisibleContent")
    narrative = page.locator("#answer").evaluate("""element => {
      const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), text = [];
      while (walker.nextNode()) {
        if (!walker.currentNode.parentElement.closest("code,pre"))
          text.push(walker.currentNode.textContent);
      }
      return text.join("");
    }""")
    require("—" not in narrative and "·" not in narrative, "DecorativeNarrativePunctuation")


def screenshot(page, directory, name, summary, account, secret):
    check_display(page, account, secret)
    path = directory / name
    page.screenshot(path=str(path), full_page=True, animations="disabled",
                    mask=[page.locator("#access-key")])
    path.chmod(0o600)
    summary["screenshots"].append(str(path.relative_to(ROOT)))


def verify_evidence(result, account):
    require(result.get("model") == MODEL, "WrongResultModel")
    require(result.get("agent_backend") == "bma", "WrongResultBackend")
    require(result.get("language") == "ko", "WrongResultLanguage")
    require(result.get("app_region") == "us-east-1" and
            result.get("target_region") == "ap-northeast-2", "WrongResultRegions")
    require(result.get("account_id") == account, "WrongResultAccount")
    require(result.get("status") in {"complete", "partial"}, "UnsuccessfulTerminalResult")
    evidence = result.get("evidence", [])
    names = [item.get("tool") for item in evidence]
    require(sorted(names) == ["get_account_context", "list_cloudwatch_alarms"],
            "UnexpectedOrRepeatedTool")
    allowed_apis = {("sts", "GetCallerIdentity"), ("cloudwatch", "DescribeAlarms")}
    for item in evidence:
        require(item.get("account_id") == account, "WrongEvidenceAccount")
        require(item.get("mode") == "live" and item.get("region") == "ap-northeast-2",
                "WrongEvidenceScope")
        require(bool(item.get("observed_at")), "MissingObservationTime")
        scope = item.get("scope", {})
        require(scope.get("max_resources") == 2, "UnboundedResourceLimit")
        require(isinstance(scope.get("max_pages"), int) and 1 <= scope["max_pages"] <= 2,
                "UnboundedPageLimit")
        for call in item.get("api_calls", []):
            require((call.get("service"), call.get("api")) in allowed_apis, "UnexpectedAwsApi")
            expected_region = "us-east-1" if call["service"] == "sts" else "ap-northeast-2"
            require(call.get("region") == expected_region, "WrongApiRegion")
    alarms = next(item for item in evidence if item["tool"] == "list_cloudwatch_alarms")
    require(alarms.get("scope", {}).get("alarm_state") == "ALARM", "WrongAlarmFilter")
    rows = alarms.get("data", [])
    require(isinstance(rows, list) and len(rows) <= 2, "TooManyReturnedAlarms")
    require(all(row.get("state") == "ALARM" for row in rows), "NonAlarmResult")
    # Empty, truncated and partial observations remain observations. No minimum
    # resource count, complete-pagination claim, or health judgment is imposed.
    return {
        "tools": names, "returned_alarms": len(rows), "alarm_status": alarms.get("status"),
        "pagination_complete": alarms.get("pagination_complete"),
        "truncated": alarms.get("truncated"), "errors": result.get("errors", []),
    }


def verify_download(path, kind, account, secret):
    require(path.stat().st_size > 0, "EmptyReportDownload")
    if kind in {"docx", "pptx"}:
        require(zipfile.is_zipfile(path), "InvalidOfficeZip")
        with zipfile.ZipFile(path) as package:
            require(package.testzip() is None, "CorruptOfficeZip")
            names = set(package.namelist())
            require({"[Content_Types].xml", "_rels/.rels"} <= names, "MissingOfficePackageParts")
            required = "word/document.xml" if kind == "docx" else "ppt/presentation.xml"
            require(required in names, "MissingOfficeDocument")
            if kind == "pptx":
                require(any(re.fullmatch(r"ppt/slides/slide\d+\.xml", name) for name in names),
                        "MissingPresentationSlides")
            require(sum(item.file_size for item in package.infolist()) <= 64_000_000,
                    "OfficePackageTooLarge")
            texts = []
            for name in names:
                if name.endswith((".xml", ".rels")):
                    content = package.read(name)
                    node = ElementTree.fromstring(content)
                    require(account.encode() not in content and secret.encode() not in content,
                            "SensitiveOfficeContent")
                    texts.extend(node.itertext())
            rendered = "\n".join(texts)
    else:
        rendered = path.read_text(encoding="utf-8")
        require(account not in rendered and secret not in rendered, "SensitiveReportContent")
        if kind == "html":
            require('id="report-answer"' in rendered, "MissingHtmlReportAnswer")
    require("Asia/Seoul" in rendered or "KST" in rendered, "MissingReportObservationZone")
    require("us-east-1" in rendered and "ap-northeast-2" in rendered, "MissingReportRegions")
    require(MODEL in rendered, "MissingReportModel")
    return {"format": kind, "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def verify():
    os.umask(0o077)
    deployment = json.loads((ROOT / "artifacts/aws-deployment.json").read_text())
    account = deployment["account_id"]
    secret_path = Path(deployment["secret_file"])
    if not secret_path.is_absolute():
        secret_path = ROOT / secret_path
    secret = json.loads(secret_path.read_text())["app_access_token"]
    base = deployment["outputs"]["WebUrl"].rstrip("/")
    parsed = urlparse(base)
    require(parsed.scheme == "https" and bool(parsed.hostname) and
            not parsed.username and not parsed.password and not parsed.query, "InvalidDeploymentUrl")
    require(bool(re.fullmatch(r"\d{12}", account)) and len(secret) >= 32, "InvalidLocalCredentials")
    require((deployment["app_region"], deployment["target_region"],
             deployment["agent_backend"], deployment["model"]) ==
            ("us-east-1", "ap-northeast-2", "bma", MODEL), "UnexpectedDeploymentScope")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = OUTPUT / stamp
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    started = time.monotonic()
    summary = {
        "status": "running", "started_at": stamp, "model": MODEL,
        "app_region": "us-east-1", "target_region": "ap-northeast-2",
        "account_display": "*********" + account[-3:],
        "screenshots": [], "downloads": [],
    }
    observations = {"requests": [], "responses": [], "blocked_posts": [], "javascript_errors": []}
    capture = {"request_id": None, "allowed_posts": 0, "creation_enabled": False}
    page = None

    def save():
        summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
        posts = [item for item in observations["requests"] if item["method"] == "POST"]
        summary["post_count"] = len(posts)
        summary["allowed_post_count"] = capture["allowed_posts"]
        summary["blocked_post_count"] = len(observations["blocked_posts"])
        summary["observations"] = str((directory / "observations.json").relative_to(ROOT))
        private_json(directory / "observations.json", redact(observations, secret, account))
        private_json(directory / "summary.json", redact(summary, secret, account))
        private_json(OUTPUT / "latest.json", redact(summary, secret, account))

    def request_seen(request):
        url = urlparse(request.url)
        if f"{url.scheme}://{url.netloc}" == origin and url.path.startswith("/api/"):
            observations["requests"].append({
                "method": request.method, "path": url.path,
                "seconds": round(time.monotonic() - started, 3),
            })

    def response_seen(response):
        url = urlparse(response.url)
        if f"{url.scheme}://{url.netloc}" == origin and url.path.startswith("/api/"):
            observations["responses"].append({
                "method": response.request.method, "path": url.path,
                "status": response.status, "seconds": round(time.monotonic() - started, 3),
            })

    def guard_posts(route, request):
        url = urlparse(request.url)
        if request.method != "POST":
            route.continue_()
            return
        valid = False
        if (f"{url.scheme}://{url.netloc}" == origin and url.path == "/api/investigations"
                and capture["creation_enabled"] and capture["allowed_posts"] == 0):
            try:
                body = request.post_data_json
                request_id = str(uuid.UUID(body["request_id"]))
                valid = (set(body) == {"request_id", "procedure_id", "prompt", "language"} and
                         body["procedure_id"] == "operations-report" and body["prompt"] == PROMPT and
                         body["language"] == "ko" and body["request_id"] == request_id)
            except (ValueError, TypeError, KeyError):
                valid = False
        if not valid:
            observations["blocked_posts"].append({"path": url.path, "method": request.method})
            route.abort()
            return
        capture["request_id"] = request_id
        capture["allowed_posts"] += 1
        capture["creation_enabled"] = False
        summary["investigation_id"] = request_id
        summary["run_id"] = request_id
        save()  # Preserve the reservation ID even if the response is lost.
        route.continue_()

    def unchanged_posts(expected=1):
        posts = [item for item in observations["requests"] if item["method"] == "POST"]
        require(len(posts) == expected and capture["allowed_posts"] == expected and
                not observations["blocked_posts"], "UnexpectedAdditionalPost")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1100}, color_scheme="light",
                    accept_downloads=True, service_workers="block",
                )
                context.route("**/*", guard_posts)
                page = context.new_page()
                page.set_default_timeout(30000)
                page.on("request", request_seen)
                page.on("response", response_seen)
                # Do not retain exception messages: Playwright or page errors can
                # contain request content. A count and fixed marker are enough.
                page.on("pageerror", lambda _: observations["javascript_errors"].append("PageError"))
                page.add_init_script(OBSERVER)
                page.goto(base, wait_until="domcontentloaded")
                expect(page.locator("#single-question-workspace")).to_be_visible()
                expect(page.locator("#investigation-workspace")).to_be_hidden()
                expect(page.locator("html")).to_have_attribute("lang", "ko")
                expect(page.locator("html")).to_have_attribute("data-theme", "light")
                page.locator("#access-key").fill(secret)
                with page.expect_response(lambda response:
                                          urlparse(response.url).path == "/api/context" and
                                          response.status == 200) as connected:
                    page.locator("#connect").click()
                app_context = connected.value.json()
                require(app_context.get("mode") == "live" and app_context.get("agent_backend") == "bma",
                        "NotLiveBmaContext")
                require(app_context.get("account_id") == account and app_context.get("model") == MODEL,
                        "UnexpectedLiveContext")
                require(app_context.get("app_region") == "us-east-1" and
                        app_context.get("target_region") == "ap-northeast-2", "WrongContextRegions")
                require(app_context.get("max_resources") == 2 and app_context.get("max_metric_hours") == 1,
                        "UnboundedDeploymentLimits")
                observations["context"] = app_context
                expect(page.locator("#submit")).to_be_enabled()
                expect(page.locator("#account")).to_have_text(summary["account_display"])
                expect(page.locator("#model-id")).to_have_text(MODEL)
                page.locator("#mode-investigation").click()
                expect(page.locator("#procedure-picker option")).to_have_count(4)
                choices = page.locator("#procedure-picker option").evaluate_all(
                    "items => items.map(item => item.value)")
                require(set(choices) == PROCEDURES, "WrongProcedureCatalog")
                page.locator("#procedure-picker").select_option("operations-report")
                expect(page.locator("#procedure-version")).to_contain_text("1.0.0")
                page.locator("#investigation-prompt").fill(PROMPT)
                capture["creation_enabled"] = True
                submitted_at = time.monotonic()
                with page.expect_response(lambda response:
                                          response.request.method == "POST" and
                                          urlparse(response.url).path == "/api/investigations") as created:
                    page.locator("#investigation-submit").click()
                require(created.value.status == 202, "CreationNotAccepted")
                initial = created.value.json()
                investigation_id = capture["request_id"]
                require(initial.get("investigation", {}).get("id") == investigation_id and
                        initial.get("run", {}).get("id") == investigation_id, "CreationIdMismatch")
                require(initial["run"]["status"] in {"queued", "running"}, "CompletedBeforeReload")
                # No screenshot, polling, or additional request precedes reload.
                observations["initial"] = initial
                observations["before_reload"] = proof_of(page)
                require(not observations["before_reload"].get("final"), "CompletedBeforeReload")
                reload_request_index = len(observations["requests"])
                page.reload(wait_until="domcontentloaded")
                summary["reloaded_before_terminal"] = True
                require(page.locator("#access-key").input_value() == "", "AccessKeyPersisted")
                expect(page.locator("#single-question-workspace")).to_be_visible()
                observations["storage_after_reload"] = verify_storage(
                    page, investigation_id, secret, account)
                page.locator("#access-key").fill(secret)
                page.locator("#connect").click()
                expect(page.locator("#submit")).to_be_enabled()
                page.locator("#mode-investigation").click()
                deadline = submitted_at + 330
                last_reconnect = 0.0
                while time.monotonic() < deadline:
                    current = proof_of(page)
                    snapshot = current.get("snapshot") or {}
                    run = snapshot.get("run") or {}
                    if run.get("status") in TERMINAL:
                        break
                    unchanged_posts()
                    connection_text = page.locator("#investigation-connection").inner_text()
                    if "끊겼습니다" in connection_text and time.monotonic() - last_reconnect >= 3:
                        page.locator("#investigation-reconnect").click()
                        last_reconnect = time.monotonic()
                    page.wait_for_timeout(min(1000, max(1, int((deadline - time.monotonic()) * 1000))))
                else:
                    raise VerificationFailure("TerminalResultTimeout")
                observations["after_reconnect"] = current
                require(snapshot.get("investigation", {}).get("id") == investigation_id and
                        run.get("id") == investigation_id, "RestoredDifferentInvestigation")
                require(any(item["method"] == "GET" and
                            item["path"] == f"/api/investigations/{investigation_id}"
                            for item in observations["requests"][reload_request_index:]),
                        "MissingGetRestoration")
                unchanged_posts()
                result = run.get("result") or current.get("final")
                require(isinstance(result, dict), "MissingSavedResult")
                observations["result"] = result
                summary["evidence"] = verify_evidence(result, account)
                summary["terminal_status"] = run["status"]
                summary["recovered_same_investigation"] = True
                summary["reconnect_additional_posts"] = 0
                expect(page.locator("#investigation-turns button")).to_have_count(1)
                turn = page.locator(f'#investigation-turns [data-turn-id="{investigation_id}"]')
                expect(turn).to_be_visible()
                expect(page.locator("#download-md")).to_be_enabled()
                turn.click()
                expect(turn).to_have_attribute("aria-current", "true")
                expect(page.locator("#investigation-selected-prompt")).to_have_text(PROMPT)
                require(page.locator("#run-status").inner_text() in {"완료", "일부 결과"},
                        "WrongKoreanTerminalStatus")
                expect(page.locator("#procedure-picker")).to_be_disabled()
                expect(page.locator("#procedure-version")).to_contain_text("1.0.0")
                expect(page.locator("#procedure-steps li")).to_have_count(4)
                summary["font"] = page.evaluate("""async () => {
                  await document.fonts.ready;
                  return {loaded: document.fonts.check('700 16px "NanumSquare OTF Bold"'),
                    family: getComputedStyle(document.body).fontFamily,
                    weight: getComputedStyle(document.body).fontWeight};
                }""")
                require(summary["font"]["loaded"] and summary["font"]["weight"] == "700",
                        "WrongInterfaceFont")
                screenshot(page, directory, "ko-light-desktop.png", summary, account, secret)
                page.locator("#language-toggle").click()
                page.locator("#theme-toggle").click()
                expect(page.locator("html")).to_have_attribute("lang", "en")
                expect(page.locator("html")).to_have_attribute("data-theme", "dark")
                require(page.locator("#run-status").inner_text() in {"Complete", "Partial results"},
                        "WrongEnglishTerminalStatus")
                screenshot(page, directory, "en-dark-desktop.png", summary, account, secret)
                page.locator("#preview-html").click()
                expect(page.locator("#preview-download")).to_be_enabled(timeout=30000)
                report = page.frame_locator("#report-preview-frame")
                expect(report.locator("html")).to_have_attribute("lang", "ko")
                expect(report.locator("html")).to_have_attribute("data-theme", "dark")
                expect(report.locator("#report-answer")).to_be_visible()
                report_text = report.locator("body").inner_text()
                require(account not in report_text and secret not in report_text,
                        "SensitiveReportPreview")
                require(report.locator("script, a[href^='javascript:']").count() == 0,
                        "ActiveReportContent")
                screenshot(page, directory, "ko-report-dark-preview.png", summary, account, secret)
                page.locator("#preview-close").click()
                for kind in ("md", "html", "docx", "pptx"):
                    with page.expect_download(timeout=30000) as pending:
                        page.locator(f"#download-{kind}").click()
                    destination = directory / f"operations-report.{kind}"
                    pending.value.save_as(str(destination))
                    destination.chmod(0o600)
                    details = verify_download(destination, kind, account, secret)
                    details["path"] = str(destination.relative_to(ROOT))
                    summary["downloads"].append(details)
                    unchanged_posts()
                page.set_viewport_size({"width": 390, "height": 844})
                require(page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"),
                        "MobileHorizontalOverflow")
                screenshot(page, directory, "en-dark-mobile.png", summary, account, secret)
                page.locator("#preview-html").click()
                expect(page.locator("#preview-download")).to_be_enabled()
                require(page.locator("#report-preview").evaluate(
                    "element => element.getBoundingClientRect().width <= innerWidth"),
                    "MobilePreviewOverflow")
                screenshot(page, directory, "ko-report-dark-mobile.png", summary, account, secret)
                page.locator("#preview-close").click()
                observations["final_storage"] = verify_storage(page, investigation_id, secret, account)
                observations["final_proof"] = proof_of(page)
                unchanged_posts()
                require(not observations["javascript_errors"], "BrowserJavaScriptError")
                summary.update({
                    "status": "passed", "history_turns": 1, "procedure_choices": choices,
                    "procedure_version": "1.0.0", "languages": ["ko", "en"],
                    "themes": ["light", "dark"], "mobile_overflow": False,
                    "html_preview": True, "export_additional_posts": 0,
                    "secret_persisted": False, "account_masked": True,
                })
            finally:
                if page is not None:
                    try:
                        observations["last_proof"] = proof_of(page)
                    except Exception:
                        pass
                browser.close()
    except Exception as error:
        # Never print a traceback or Playwright call log containing input values.
        summary["status"] = "failed"
        summary["failure"] = str(error) if isinstance(error, VerificationFailure) else type(error).__name__
        save()
        return 1
    save()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(verify())
    except Exception:
        # Configuration failures happen before the artifact directory exists.
        # Keep them silent rather than leaking local paths or secret content.
        raise SystemExit(2) from None
