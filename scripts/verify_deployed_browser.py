#!/usr/bin/env python3
"""Verify deployed OTF/Markdown/SSE using one bounded, real CloudWatch alarm query."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from verify_deployed import ALLOWED_APIS, CASES


def main(language="ko", report_preview=False):
    deployment = json.loads(Path("artifacts/aws-deployment.json").read_text())
    secret = json.loads(Path(deployment["secret_file"]).read_text())["app_access_token"]
    output = Path(deployment.get("ui_e2e_directory",
                                "artifacts/e2e-report-preview" if report_preview else "artifacts/e2e-ui"))
    output.mkdir(exist_ok=True)
    base = deployment["outputs"]["WebUrl"]
    prompt = CASES["alarms"]["prompt"] + " 결과 목록은 Markdown 표로 표시해 줘."
    if language == "en":
        prompt = ("Use aws-operations-report to verify the execution account and list only CloudWatch alarms "
                  "in ALARM state in Seoul. Return at most 2 alarms using the tool limit. Do not query other "
                  "services or metrics. Use a Markdown table, quote API evidence and UTC/Asia-Seoul times, "
                  "and state truncation and unqueried scope.")
    started = time.monotonic()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page.set_default_timeout(30000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("""
            window.__streamProof = {events: [], final: null, paints: []};
            const originalFetch = window.fetch;
            window.fetch = async (...args) => {
              const response = await originalFetch(...args);
              if (args[0] === "/api/chat" && response.ok) {
                const reader = response.clone().body.getReader();
                const decoder = new TextDecoder();
                (async () => {
                  let buffer = "";
                  while (true) {
                    const {value, done} = await reader.read();
                    buffer += decoder.decode(value, {stream: !done});
                    let boundary;
                    while ((boundary = buffer.indexOf("\\n\\n")) >= 0) {
                      const frame = buffer.slice(0, boundary);
                      buffer = buffer.slice(boundary + 2);
                      const line = frame.split("\\n").find(line => line.startsWith("data: "));
                      if (!line) continue;
                      const event = JSON.parse(line.slice(6));
                      window.__streamProof.events.push({type: event.type, at: performance.now()});
                      if (event.type === "complete") window.__streamProof.final = event;
                    }
                    if (done) break;
                  }
                })();
              }
              return response;
            };
        """)
        page.goto(base)
        expect(page).to_have_title("AI-Powered AWS Operations Desk")
        expect(page.locator(".brand")).to_have_text("AI-Powered AWS Operations Desk")
        if language == "en":
            page.locator("#language-toggle").click()
            page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("lang", language)
        expected_theme = "dark" if language == "en" else "light"
        expect(page.locator("html")).to_have_attribute("data-theme", expected_theme)
        page.locator("#access-key").fill(secret)
        page.locator("#connect").click()
        expect(page.locator("#submit")).to_be_enabled()
        masked_account = "*********" + deployment["account_id"][-3:]
        expect(page.locator("#account")).to_have_text(masked_account)
        expect(page.locator("#model-label")).to_contain_text("Luna")
        expect(page.locator("#model-id")).to_have_text(deployment["model"])
        expect(page.locator("#data-flow")).to_contain_text("BMA" if deployment.get("agent_backend") == "bma" else ("global" if language == "en" else "글로벌"))
        expect(page.locator("[data-i18n=appRegionName]")).to_have_text("N. Virginia" if language == "en" else "버지니아 북부")
        font = page.evaluate("""
            async () => {
              await document.fonts.ready;
              return {loaded: document.fonts.check('700 16px "NanumSquare OTF Bold"'),
                      family: getComputedStyle(document.body).fontFamily,
                      weight: getComputedStyle(document.body).fontWeight};
            }
        """)
        assert font["loaded"] and font["weight"] == "700"
        page.evaluate("""
            () => new MutationObserver(() => {
              const answer = document.querySelector("#answer");
              if (["답변 작성 중", "Writing answer"].includes(document.querySelector("#run-status").textContent) &&
                  answer.textContent.length > 80 && window.__streamProof.paints.length < 20) {
                window.__streamProof.paints.push({at: performance.now(), characters: answer.textContent.length});
              }
            }).observe(document.querySelector("#answer"), {subtree: true, childList: true, characterData: true})
        """)
        page.locator("#prompt").fill(prompt)
        page.locator("#submit").click()
        page.wait_for_function("() => window.__streamProof.final !== null", timeout=330000)
        expect(page.locator("#download-md")).to_be_enabled()
        expect(page.locator("#answer table")).to_be_visible()
        statuses = {"Query complete", "Partial results"} if language == "en" else {"조회 완료", "일부 결과"}
        assert page.locator("#run-status").inner_text() in statuses
        expect(page.locator("#notice")).to_have_text("")
        proof = page.evaluate("() => window.__streamProof")
        final = proof["final"]
        assert not final["errors"]
        assert final["model"] == deployment["model"]
        assert final["model_processing_scope"] == deployment["model_processing_scope"]
        assert final["language"] == language
        names = {result["tool"] for result in final["evidence"]}
        assert names == set(CASES["alarms"]["required"])
        for result in final["evidence"]:
            assert result["account_id"] == deployment["account_id"]
            assert result["region"] == "ap-northeast-2"
            assert result["mode"] == "live" and not result["errors"] and not result["permission_denied"]
            assert result["scope"]["max_resources"] == 2
            for call in result["api_calls"]:
                assert call["api"] in ALLOWED_APIS[call["service"]]
                assert call["success"] and call["request_id"]
                assert call["region"] == ("us-east-1" if call["service"] == "sts" else "ap-northeast-2")
        deltas = [event for event in proof["events"] if event["type"] == "answer_delta"]
        completed_at = next(event["at"] for event in proof["events"] if event["type"] == "complete")
        assert deltas and deltas[0]["at"] < completed_at
        assert any(paint["at"] < completed_at for paint in proof["paints"]), "No actual Markdown paint before completion"
        assert deployment["account_id"] not in page.locator("body").inner_text()
        narrative = page.locator("#answer").evaluate("""element => {
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
          const text = [];
          while (walker.nextNode()) if (!walker.currentNode.parentElement.closest('code,pre')) text.push(walker.currentNode.textContent);
          return text.join('');
        }""")
        assert not any(mark in narrative for mark in ["—", "·", "오리건"])
        page.screenshot(path=str(output / f"{language}-{expected_theme}-desktop.png"), full_page=True)
        if report_preview:
            page.locator("#preview-html").click()
            expect(page.locator("#preview-download")).to_be_enabled()
            report = page.frame_locator("#report-preview-frame")
            expect(report.locator("html")).to_have_attribute("lang", language)
            expect(report.locator("html")).to_have_attribute("data-theme", expected_theme)
            report.locator("#report-answer").scroll_into_view_if_needed()
            expect(report.locator("#report-answer table")).to_be_visible()
            assert deployment["account_id"] not in report.locator("body").inner_text()
            assert report.locator("script, img, a[href^='javascript:']").count() == 0
            assert report.locator("body").evaluate(
                "async () => {await document.fonts.ready; return document.fonts.check('700 16px \"NanumSquare OTF Bold\"');}"
            )
            page.screenshot(path=str(output / f"{language}-html-preview.png"), full_page=True)
            with page.expect_download() as preview_file:
                page.locator("#preview-download").click()
            preview_path = output / f"{language}-preview-download.html"
            preview_file.value.save_as(preview_path)
            preview_html = preview_path.read_text()
            assert 'id="report-answer"' in preview_html and "data:font/otf;base64," in preview_html
            assert deployment["account_id"] not in preview_html
            page.locator("#preview-close").click()
        for format in ["md", "html"]:
            with page.expect_download() as pending:
                page.locator(f"#download-{format}").click()
            destination = output / f"{language}-alarms-{stamp}.{format}"
            pending.value.save_as(destination)
            text = destination.read_text()
            processing_label = "BMA" if deployment["agent_backend"] == "bma" else ("Global" if language == "en" else "글로벌")
            assert "Asia/Seoul" in text and processing_label in text and masked_account in text
            assert "us-east-1" in text and deployment["model"] in text
            assert deployment["account_id"] not in text
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / f"{language}-{expected_theme}-mobile.png"), full_page=True)
        if report_preview:
            page.locator("#preview-html").click()
            expect(page.locator("#preview-download")).to_be_enabled()
            assert page.locator("#report-preview").evaluate("e => e.getBoundingClientRect().width <= window.innerWidth")
            assert report.locator("body").evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / f"{language}-html-preview-mobile.png"), full_page=True)
            page.locator("#preview-close").click()
        page.reload()
        expect(page.locator("html")).to_have_attribute("lang", language)
        expect(page.locator("html")).to_have_attribute("data-theme", expected_theme)
        assert not errors
        browser.close()
    path = output / f"{language}-alarms-browser-{stamp}.json"
    path.write_text(json.dumps({"result": final, "events": proof["events"], "paints": proof["paints"],
                               "font": font, "javascript_errors": errors}, ensure_ascii=False, indent=2) + "\n")
    summary = {
        "case": "alarms", "status": "passed", "run_id": final["id"], "tools": sorted(names),
        "response_status": final["status"], "elapsed_seconds": round(time.monotonic() - started, 2),
        "evidence": str(path), "account_id": deployment["account_id"],
        "app_region": "us-east-1", "target_region": "ap-northeast-2",
        "agent_backend": deployment["agent_backend"], "model": final["model"], "answer_delta_events": len(deltas),
        "markdown_painted_before_completion": True, "font": font,
        "mobile_overflow": False, "javascript_errors": [],
        "language": language, "theme": expected_theme, "masked_account": masked_account,
        "preferences_survive_reload": True, "prose_punctuation": "passed",
        "html_report_preview": report_preview,
    }
    (output / f"{language}-latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**summary, "account_id": masked_account}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--language", choices=["ko", "en"], default="ko")
    parser.add_argument("--report-preview", action="store_true")
    args = parser.parse_args()
    main(args.language, args.report_preview)
