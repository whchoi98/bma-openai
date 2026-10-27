#!/usr/bin/env python3
"""Check real DOM rendering before SSE completion, GFM semantics, local OTF and safety."""
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        ["node", "web/tests/stream-ui-server.mjs"], cwd=ROOT,
        env={**os.environ, "TEST_PORT": str(port)}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    output = ROOT / "artifacts"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("SSE fixture did not start.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors, external_images = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: external_images.append(request.url)
                    if "example.invalid" in request.url else None)
            page.route("**/api/context", lambda route: route.fulfill(
                status=401, content_type="application/json", body='{"error":"AuthenticationRequired"}'))
            page.goto(base)
            expect(page.locator("#notice")).to_contain_text("접속 키")
            page.locator("#language-toggle").click()
            expect(page.locator("#notice")).to_have_text("Enter your access key and connect.")
            expect(page.locator("#mode")).to_have_text("Not connected")
            page.unroute("**/api/context")
            page.locator("#connect").click()
            expect(page.locator("#submit")).to_be_enabled()
            page.locator("#language-toggle").click()
            expect(page.locator(".brand")).to_have_text("AI-Powered AWS Operations Desk")
            expect(page.locator("#account")).to_have_text("*********000")
            page.locator("#prompt").fill("서울 리소스 결과를 표시해 줘")
            page.locator("#submit").click()
            expect(page.locator("#answer h2")).to_have_text("서울 리소스")
            expect(page.locator("#run-status")).to_have_text("답변 작성 중")
            expect(page.locator("#answer table")).to_be_visible()
            expect(page.locator("#answer pre code")).to_contain_text("ap-northeast-2")
            expect(page.locator("#answer input[type=checkbox]").first).to_be_disabled()
            expect(page.locator(".streaming-cursor")).to_be_visible()
            expect(page.locator("#download-md")).to_be_disabled()
            expect(page.locator("#preview-html")).to_be_disabled()
            expect(page.locator("#language-toggle")).to_be_disabled()
            assert page.locator("#answer script, #answer img, #answer a[href^='javascript:']").count() == 0
            assert page.evaluate("() => window.markdownUnsafe === undefined")
            assert not re.search(r"(?<!\d)000000000000(?!\d)", page.locator("body").inner_text())
            assert not any(mark in page.locator("#answer").inner_text() for mark in ["—", "·", "오리건"])
            loaded = page.evaluate("async () => { await document.fonts.ready; return document.fonts.check('700 16px \"NanumSquare OTF Bold\"'); }")
            assert loaded
            assert page.evaluate("() => getComputedStyle(document.body).fontWeight") == "700"
            page.screenshot(path=str(output / "markdown-streaming-desktop.png"), full_page=True)
            page.locator("#theme-toggle").click()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            assert page.evaluate("() => getComputedStyle(document.body).backgroundColor") == "rgb(12, 25, 37)"
            page.request.get(base + "/__test/release")
            expect(page.locator("#run-status")).to_have_text("조회 완료")
            expect(page.locator("#answer h3")).to_have_text("조회 한계")
            expect(page.locator(".streaming-cursor")).to_have_count(0)
            expect(page.locator("#download-md")).to_be_enabled()
            page.locator("#preview-html").click()
            expect(page.locator("#report-preview")).to_be_visible()
            expect(page.locator("#preview-download")).to_be_enabled()
            assert page.locator("#report-preview-frame").get_attribute("sandbox") == "allow-same-origin"
            report = page.frame_locator("#report-preview-frame")
            expect(report.locator("#report-answer h2")).to_have_text("서울 리소스")
            expect(report.locator("#report-answer table")).to_be_visible()
            expect(report.locator("html")).to_have_attribute("data-theme", "dark")
            assert report.locator("body").evaluate(
                "() => getComputedStyle(document.body).backgroundColor"
            ) == "rgb(12, 25, 37)"
            assert not re.search(r"(?<!\d)000000000000(?!\d)", report.locator("body").inner_text())
            assert report.locator("script, img, a[href^='javascript:']").count() == 0
            assert report.locator("body").evaluate(
                "async () => {await document.fonts.ready; return document.fonts.check('700 16px \"NanumSquare OTF Bold\"');}"
            )
            page.screenshot(path=str(output / "html-preview-ko-dark.png"), full_page=True)
            page.locator("#preview-close").click()
            expect(page.locator("#report-preview")).not_to_be_visible()
            expect(page.locator("#preview-html")).to_be_focused()
            page.locator("#language-toggle").click()
            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.locator("#submit")).to_have_text("Run query")
            page.locator("[data-prompt-key=exampleInventory]").click()
            expect(page.locator("#prompt")).to_have_value("Show EC2 and RDS resources in Seoul")
            expect(page.locator("#answer h2")).to_have_text("Seoul resources")
            expect(page.locator("#run-status")).to_have_text("Query complete")
            page.locator("#preview-html").click()
            expect(page.locator("#preview-download")).to_be_enabled()
            expect(report.locator("#report-answer h2")).to_have_text("Seoul resources")
            expect(report.locator("html")).to_have_attribute("lang", "en")
            page.screenshot(path=str(output / "html-preview-en-dark.png"), full_page=True)
            with page.expect_download() as preview_download:
                page.locator("#preview-download").click()
            preview_path = output / "html-preview-download.html"
            preview_download.value.save_as(preview_path)
            preview_text = preview_path.read_text()
            assert "<h2>Seoul resources</h2>" in preview_text and "data:font/otf;base64," in preview_text
            offline = browser.new_page()
            offline_requests = []
            offline.on("request", lambda request: offline_requests.append(request.url)
                       if request.url.startswith(("http://", "https://")) else None)
            offline.goto(preview_path.as_uri())
            expect(offline.locator("#report-answer h2")).to_have_text("Seoul resources")
            assert offline.evaluate(
                "async () => {await document.fonts.ready; return document.fonts.check('700 16px \"NanumSquare OTF Bold\"');}"
            )
            assert not offline_requests
            offline.close()
            page.locator("#preview-close").focus()
            page.keyboard.press("Escape")
            expect(page.locator("#report-preview")).not_to_be_visible()
            delayed_downloads = []

            def delay_download(route):
                delayed_downloads.append((route, route.fetch()))

            page.route("**/report.html?view=download*", delay_download)
            with page.expect_download() as delayed:
                with page.expect_request("**/report.html?view=download*") as original_request:
                    page.locator("#download-html").click()
                original_id = original_request.value.url.split("/runs/")[1].split("/")[0]
                page.locator("#prompt").fill("Run another query while the old report downloads")
                with page.expect_response("**/api/chat") as next_query:
                    page.locator("#submit").click()
                completed_events = [json.loads(line[6:]) for line in next_query.value.text().splitlines()
                                    if line.startswith("data: ")]
                assert completed_events[-1]["type"] == "complete"
                assert completed_events[-1]["id"] != original_id
                expect(page.locator("#run-status")).to_have_text("Query complete")
                assert delayed_downloads
                delayed_downloads[0][0].fulfill(response=delayed_downloads[0][1])
            assert delayed.value.suggested_filename == f"aws-report-{original_id}.html"
            page.unroute("**/report.html?view=download*")
            for format in ["md", "html"]:
                with page.expect_download() as download:
                    page.locator(f"#download-{format}").click()
                path = output / f"ui-preferences-report.{format}"
                download.value.save_as(path)
                text = path.read_text()
                assert not re.search(r"(?<!\d)000000000000(?!\d)", text)
                assert "*********000" in text
                assert "AWS operations report" in text
            page.screenshot(path=str(output / "ui-preferences-dark-en.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#preview-html").click()
            expect(page.locator("#preview-download")).to_be_enabled()
            assert page.locator("#report-preview").evaluate(
                "e => e.getBoundingClientRect().width <= window.innerWidth"
            )
            assert report.locator("body").evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth"
            )
            page.screenshot(path=str(output / "html-preview-mobile.png"), full_page=True)
            page.locator("#preview-close").click()
            if not page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"):
                print(page.evaluate("""() => Object.fromEntries(
                  ['.workspace','.results-column','.answer-panel','.answer','.markdown-body','.markdown-table','pre']
                  .map(s => {const e=document.querySelector(s);return [s,e?{width:e.getBoundingClientRect().width,scroll:e.scrollWidth}:null]})
                )"""))
                page.screenshot(path=str(output / "markdown-overflow.png"), full_page=True)
            assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "markdown-mobile.png"), full_page=True)
            page.reload()
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.locator("#account")).to_have_text("*********000")
            expect(page.locator("#submit")).to_have_text("Run query")
            page.locator("#theme-toggle").click()
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.locator("#language-toggle").click()
            expect(page.locator("html")).to_have_attribute("lang", "ko")
            page.locator("#prompt").fill("__disconnect__")
            page.locator("#submit").click()
            expect(page.locator("#run-status")).to_have_text("완료되지 않음")
            expect(page.locator("#answer h2")).to_have_text("Partial result")
            assert "000000" not in page.locator("#answer").inner_text()
            page.locator("#language-toggle").click()
            expect(page.locator("#run-status")).to_have_text("Not completed")
            expect(page.locator("#answer h2")).to_have_text("Partial result")
            expect(page.locator("#trace-count")).to_have_text("1 query")
            assert "000000" not in page.locator("#answer").inner_text()
            assert not errors and not external_images
            browser.close()
            result = {"rendered_before_sse_completion": True, "gfm_table_list_code": "passed",
                      "font": "NanumSquareB.otf", "font_weight": 700, "unsafe_content": "blocked",
                      "external_image_requests": 0, "javascript_errors": [], "mobile_overflow": False,
                      "account_masking": "card, Markdown, evidence, downloads",
                      "dark_mode": "passed", "language_toggle": "ko/en passed",
                      "preferences_survive_reload": True, "prose_punctuation": "passed"}
            result["interrupted_answer_survives_language_toggle"] = True
            result["html_report_preview"] = {
                "rendered_markdown": True, "masked": True, "theme": "dark",
                "languages": ["ko", "en"], "keyboard_close": True, "mobile_overflow": False,
                "standalone_download": True,
                "download_keeps_original_run": True,
            }
            (output / "markdown-browser-check.json").write_text(json.dumps(result, indent=2) + "\n")
            (output / "ui-preferences-check.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    run()
