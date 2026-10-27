#!/usr/bin/env python3
"""Capture README screenshots in Chromium; no AWS/model calls.

desk: the Operations Desk in sample mode. studio: AI Document Studio served by
studio/scripts/fixture_server.mjs from files rendered by the real renderers in .studio-venv.
Usage: capture_screenshots.py [desk] [studio] [ko] [en]  (default: everything)
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/images"
STUDIO_PYTHON = ROOT / ".studio-venv/bin/python"
STUDIO_FONT = ROOT / "studio/web/static/fonts/NanumSquareB.otf"
DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}
MAX_HEIGHT = 1400
DONE = re.compile(r"^(조회 완료|Query complete|완료|Complete|일부 결과|Partial results)$")
# Sample investigations finish immediately, so the UI may already show the stored turn (historyLoaded)
INVESTIGATION_DONE = re.compile(r"^(조사 완료|Investigation complete|일부 결과 저장됨|Partial results saved"
                                r"|저장된 결과를 표시합니다\.|Showing a saved result\.)$")
TEXT = {
    "ko": {
        "report": "조회 가능한 서울 리전 서비스의 운영 보고서를 작성해 줘",
        "investigation": "운영 보고서 절차로 서울 리전의 ALARM 상태 CloudWatch 알람과 EC2 상태를 정리해 줘",
    },
    "en": {
        "report": "Write an operations report for the supported Seoul services",
        "investigation": "Use the operations report procedure for ALARM CloudWatch alarms and EC2 health in Seoul",
    },
}


def shot(page, name, locator=None, full=False, mask=()):
    """Save a viewport, element (height-capped) or full-page screenshot under docs/images."""
    path = OUTPUT / f"{name}.png"
    options = {"path": str(path), "animations": "disabled", "mask": list(mask), "mask_color": "#dfe5ef"}
    if locator is not None:
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        scroll_y = page.evaluate("() => window.scrollY")
        options.update(full_page=True, clip={"x": box["x"], "y": box["y"] + scroll_y,
                                             "width": box["width"], "height": min(box["height"], MAX_HEIGHT)})
    else:
        page.evaluate("() => window.scrollTo(0, 0)")
        options["full_page"] = full
    page.screenshot(**options)
    print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KiB")


def ask(page, key):
    page.locator(f"[data-prompt-key={key}]").click()
    expect(page.locator("#run-status")).to_have_text(DONE, timeout=30000)


def capture(browser, base, language):
    page = browser.new_page(viewport=DESKTOP, locale="ko-KR" if language == "ko" else "en-US")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base)
    expect(page.locator("#submit")).to_be_enabled()
    if language == "en":
        page.locator("#language-toggle").click()
    expect(page.locator("html")).to_have_attribute("lang", language)
    expect(page.locator("html")).to_have_attribute("data-theme", "light")

    # 1. Overview and streamed Markdown answer with the run trace
    ask(page, "exampleInventory")
    shot(page, f"{language}-overview")
    shot(page, f"{language}-answer", page.locator(".answer-panel"))
    shot(page, f"{language}-trace", page.locator(".trace-panel"))

    # 2. Observed-resource relationship graph
    ask(page, "exampleTopology")
    expect(page.locator("#resource-insights svg")).to_be_visible()
    page.locator(".graph-node").first.click()
    expect(page.locator(".graph-selected")).to_be_visible()
    panels = page.locator("#resource-insights .insight-panel")
    shot(page, f"{language}-topology", panels.filter(has=page.locator("svg")))

    # 3. Security configuration checks (meets / needs review / unverified)
    ask(page, "exampleSecurity")
    expect(page.locator(".security-fail").first).to_be_visible()
    shot(page, f"{language}-security", panels.filter(has=page.locator(".security-fail")))

    # 4. Saved report history and the sandboxed HTML report preview
    page.locator("#prompt").fill(TEXT[language]["report"])
    page.locator("#submit").click()
    expect(page.locator("#run-status")).to_have_text(DONE, timeout=30000)
    page.locator("#preview-html").click()
    expect(page.locator("#preview-download")).to_be_enabled(timeout=30000)
    expect(page.frame_locator("#report-preview-frame").locator("#report-answer")).to_be_visible()
    shot(page, f"{language}-report-preview")
    page.locator("#preview-close").click()
    shot(page, f"{language}-history", page.locator("#single-question-workspace .history-panel"))

    # 5. Operations investigation with a versioned procedure and step status
    page.locator("#mode-investigation").click()
    expect(page.locator("#investigation-workspace")).to_be_visible()
    page.locator("#procedure-picker").select_option("operations-report")
    expect(page.locator("#procedure-version")).to_contain_text("1.0.0")
    page.locator("#investigation-prompt").fill(TEXT[language]["investigation"])
    page.locator("#investigation-submit").click()
    # #run-status still shows the previous single question here, so wait on the investigation phase
    expect(page.locator("#phase")).to_have_text(INVESTIGATION_DONE, timeout=60000)
    expect(page.locator("#investigation-turns button")).to_have_count(1)
    shot(page, f"{language}-investigation", page.locator(".workspace"))

    # 6. Dark mode, then the mobile layout
    page.locator("#theme-toggle").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    shot(page, f"{language}-dark")
    page.locator("#theme-toggle").click()
    page.locator("#mode-question").click()
    page.set_viewport_size(MOBILE)
    page.reload()
    expect(page.locator("#submit")).to_be_enabled()
    if page.locator("html").get_attribute("lang") != language:
        page.locator("#language-toggle").click()
    ask(page, "exampleInventory")
    if not page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth"):
        raise AssertionError("Horizontal overflow on mobile")
    shot(page, f"{language}-mobile")
    page.close()
    if errors:
        raise AssertionError(errors)


def capture_studio(browser, base, manifest, server, language):
    page = browser.new_page(viewport=DESKTOP, locale="ko-KR" if language == "ko" else "en-US")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base)
    if language == "en":
        page.locator("#language").select_option("en")
    expect(page.locator("html")).to_have_attribute("lang", language)
    page.locator("#access-key").fill(manifest["access_key"])
    page.locator("#connect").click()
    expect(page.locator("#model-info")).to_contain_text(manifest["model"])
    expect(page.locator("#history .history-item")).to_have_count(1)

    # 1. Brief: one spreadsheet, a plain-language request, outputs (PPTX/DOCX are preselected) and a style
    page.locator("#file-input").set_input_files(manifest["draft"]["file"])
    expect(page.locator("#selected-file")).to_be_visible()
    page.locator("#prompt").fill(manifest["draft"]["prompt"])
    page.locator('label.output-option:has(input[value="chart"])').click()
    for value in ["pptx", "docx", "chart"]:
        expect(page.locator(f'input[name="output"][value="{value}"]')).to_be_checked()
    shot(page, f"{language}-studio-brief", page.locator(".editor-panel"))

    # 2. Real phase names, elapsed time and the working animation (fixture holds on "writing")
    page.locator("#generate").click()
    expect(page.locator("#progress-panel")).to_be_visible()
    expect(page.locator("#completed-steps li:not(.current)")).to_have_count(4)
    shot(page, f"{language}-studio-progress", page.locator(".result-panel"))

    # 3. Finished files and the sandboxed document content preview
    server.stdin.write("complete\n")
    server.stdin.flush()
    expect(page.locator("#artifact-list .artifact-card")).to_have_count(5, timeout=15000)
    figure = page.frame_locator("#preview-frame").locator("figure")
    expect(figure.locator("img")).to_be_visible()
    # The sidebar is one viewport high, so grow the viewport to the page instead of a full-page capture
    page.set_viewport_size({"width": DESKTOP["width"],
                            "height": page.evaluate("() => document.documentElement.scrollHeight")})
    figure.scroll_into_view_if_needed()
    shot(page, f"{language}-studio-result")
    page.set_viewport_size(DESKTOP)

    # 4. The earlier notes job in the AWS Operations Desk style: its workflow diagram file
    page.locator("#history .history-item").nth(1).click()
    expect(page.locator("#job-title")).to_have_text(manifest["history"][0]["title"])
    page.locator('.artifact-card[data-artifact-id="diagram_1_png"] .artifact-main').click()
    page.wait_for_function("() => { const image = document.querySelector('#preview-image');"
                           " return !image.hidden && image.complete && image.naturalWidth > 0; }")
    shot(page, f"{language}-studio-diagram", page.locator(".result-panel"))
    page.close()
    if errors:
        raise AssertionError(errors)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def sample_server():
    """Start web/index.js in sample mode on a free port; its MemoryStore starts empty."""
    port = free_port()
    environment = {**os.environ, "DATA_MODE": "sample", "APP_ACCESS_TOKEN": "",
                   "AWS_LAMBDA_HTTP_ENDPOINT": f"127.0.0.1:{port}",
                   "APP_REGION": "us-east-1", "TARGET_REGION": "ap-northeast-2"}
    process = subprocess.Popen(["node", "web/index.js"], cwd=ROOT, env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Sample server did not start.")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=5)


@contextmanager
def studio_server(language):
    """Render Studio fixtures in .studio-venv, then serve them through the real Studio HTTP routes."""
    with tempfile.TemporaryDirectory() as directory:
        environment = {**os.environ, "MPLBACKEND": "Agg", "STUDIO_FONT_PATH": str(STUDIO_FONT)}
        subprocess.run([str(STUDIO_PYTHON), "studio/scripts/render_fixtures.py", directory, language],
                       cwd=ROOT, env=environment, check=True)
        manifest_path = Path(directory, "fixtures.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        port = free_port()
        process = subprocess.Popen(["node", "studio/scripts/fixture_server.mjs", str(manifest_path), str(port)],
                                   cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            if process.stdout.readline().strip() != "ready":
                raise RuntimeError("Studio fixture server did not start.")
            yield f"http://127.0.0.1:{port}", manifest, process
        finally:
            process.terminate()
            process.wait(timeout=5)


def run(targets, languages):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for language in languages:
            # A fresh server per language keeps each history list in a single language
            if "desk" in targets:
                with sample_server() as base:
                    capture(browser, base, language)
            if "studio" in targets:
                with studio_server(language) as (base, manifest, server):
                    capture_studio(browser, base, manifest, server, language)
        browser.close()


if __name__ == "__main__":
    arguments = sys.argv[1:]
    run([name for name in arguments if name in {"desk", "studio"}] or ["desk", "studio"],
        [name for name in arguments if name in {"ko", "en"}] or ["ko", "en"])
