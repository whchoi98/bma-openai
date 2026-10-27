#!/usr/bin/env python3
"""Load an already verified live run from history and check graph/security/Office UI."""
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from playwright.sync_api import expect, sync_playwright


def main():
    deployment = json.loads(Path("artifacts/aws-deployment.json").read_text())
    output = Path(deployment.get("extended_e2e_directory", "artifacts/e2e-extraction"))
    summary = json.loads((output / "network-latest.json").read_text())
    secret = json.loads(Path(deployment["secret_file"]).read_text())["app_access_token"]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        errors, queries = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: queries.append(request.url)
                if request.method == "POST" and request.url.endswith("/api/chat") else None)
        page.goto(deployment["outputs"]["WebUrl"])
        page.locator("#access-key").fill(secret)
        page.locator("#connect").click()
        expect(page.locator("#submit")).to_be_enabled()
        expect(page.locator("#account")).to_have_text("*********" + deployment["account_id"][-3:])
        saved = page.locator(f'#history-list [data-run-id="{summary["run_id"]}"]')
        expect(saved).to_be_visible(timeout=30000)
        saved.click()
        expect(page.locator("#phase")).to_have_text("저장된 결과를 표시합니다.")
        expect(page.locator("#resource-insights svg")).to_be_visible()
        assert page.locator(".graph-node").count() > 0
        page.locator(".graph-node").first.click()
        expect(page.locator(".graph-selected")).to_be_visible()
        page.screenshot(path=str(output / "live-topology-history-ko.png"), full_page=True)
        page.locator("#language-toggle").click()
        page.locator("#theme-toggle").click()
        expect(page.locator("#phase")).to_have_text("Showing a saved result.")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        for format in ["md", "html", "docx", "pptx"]:
            with page.expect_download() as download:
                page.locator("#download-" + format).click()
            path = output / ("history-network." + format)
            download.value.save_as(path)
            if format in {"docx", "pptx"}:
                with zipfile.ZipFile(path) as package:
                    assert package.testzip() is None
                    texts = []
                    for name in package.namelist():
                        if name.endswith(".xml"):
                            node = ElementTree.fromstring(package.read(name))
                            texts.extend(node.itertext())
                    assert deployment["account_id"] not in "".join(texts)
                    assert any("Asia/Seoul" in value or "KST" in value for value in texts)
            else:
                assert deployment["account_id"] not in path.read_text()
        page.locator("#preview-html").click()
        expect(page.locator("#preview-download")).to_be_enabled()
        assert deployment["account_id"] not in page.frame_locator("#report-preview-frame").locator("body").inner_text()
        page.locator("#preview-close").click()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "live-history-mobile-en.png"), full_page=True)
        assert not queries, "History load/export unexpectedly ran a new model query"
        assert not errors
        browser.close()
    result = {"status": "passed", "run_id": summary["run_id"], "history_load": True,
              "topology": True, "formats": ["md", "html", "docx", "pptx"],
              "account_masked": True, "new_model_queries": 0, "javascript_errors": [],
              "mobile_overflow": False, "language": "ko/en", "theme": "light/dark"}
    (output / "browser.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
