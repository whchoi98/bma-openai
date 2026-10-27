#!/usr/bin/env python3
"""One real notes-to-Office UI run, including progress animation and reload."""
import io
import json
import time
import zipfile
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def verify():
    root = Path(__file__).resolve().parents[2]
    d = json.loads((root / "artifacts/studio/deployment.json").read_text())
    token = json.loads((root / d["secret_file"]).read_text())["app_access_token"]
    output = root / "artifacts/studio/live-browser"
    output.mkdir(parents=True, exist_ok=True)
    base = d["outputs"]["WebUrl"]
    posts, errors = [], []
    started = time.monotonic()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1512, "height": 1100}, reduced_motion="no-preference")
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/api/jobs" in r.url else None)
        page.goto(base)
        page.locator("#access-key").fill(token)
        page.locator("#connect").click()
        expect(page.locator("#access-control")).not_to_have_attribute("open", "")
        expect(page.locator("#model-info")).to_contain_text(d["model"])
        page.locator("#notes").fill(
            "신입사원 온보딩 업무 메모. 인사팀은 입사 서류를 접수한다. IT팀은 계정과 장비를 준비한다. "
            "팀장은 첫 주 일정을 안내한다. 멘토는 질의응답을 진행한다. 인사팀은 적응 상태를 확인한다. "
            "이 메모는 데모용 예시이며 다른 일정이나 담당자는 정하지 않았다."
        )
        page.locator("#prompt").fill("이 메모의 업무 흐름도를 만들고, 흐름도를 포함한 짧은 PPT와 Word 안내서를 만들어 주세요.")
        page.locator('label.output-option:has(input[value="diagram"])').click()
        page.locator('label.style-option:has(input[value="aws-desk"])').click()
        with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/api/jobs")) as accepted:
            page.locator("#generate").click()
        initial = accepted.value.json()["job"]
        job_id = initial["id"]
        expect(page.locator("#progress-panel")).to_be_visible(timeout=20000)
        animation_count = page.locator("#working-scene").evaluate("(e) => e.getAnimations({subtree:true}).length")
        assert animation_count > 0
        page.screenshot(path=str(output / "working.png"), full_page=True)
        page.reload()
        assert page.locator("#access-key").input_value() == ""
        page.locator("#access-key").fill(token)
        page.locator("#connect").click()
        page.wait_for_function("() => !document.querySelector('#job-result').hidden", timeout=330000)
        with httpx.Client(timeout=30) as client:
            final_response = client.get(base + "/api/jobs/" + job_id, headers={"Authorization": "Bearer " + token})
            final_response.raise_for_status()
            final = final_response.json()["job"]
        assert final["status"] == "complete" and not final["errors"], final
        assert len(posts) == 1
        assert final["style"] == "aws-desk"
        assert {"pptx", "docx", "diagram"} <= set(final["outputs"])
        expect(page.locator("#artifact-list .artifact-card").first).to_be_visible()
        page.screenshot(path=str(output / "office-ko-light.png"), full_page=True)
        page.locator("#language").select_option("en")
        page.locator("#theme-toggle").click()
        page.screenshot(path=str(output / "office-en-dark.png"), full_page=True)
        for item in final["artifacts"]:
            response = httpx.get(base + f"/api/jobs/{job_id}/artifacts/{item['id']}",
                                 headers={"Authorization": "Bearer " + token}, timeout=30)
            response.raise_for_status()
            (output / item["filename"]).write_bytes(response.content)
            if item["filename"].endswith((".docx", ".pptx")):
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    assert archive.testzip() is None
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(output / "office-mobile.png"), full_page=True)
        assert not errors
        browser.close()
    proof = {"status": "passed", "job_id": job_id, "model": d["model"], "style": "aws-desk",
             "post_count": len(posts), "reload_without_resubmission": True, "animation_count": animation_count,
             "artifacts": [{k: item[k] for k in ["id", "filename", "mime", "size"]} for item in final["artifacts"]],
             "javascript_errors": errors, "mobile_overflow": False,
             "elapsed_seconds": round(time.monotonic() - started, 2)}
    (output / "summary.json").write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    verify()
