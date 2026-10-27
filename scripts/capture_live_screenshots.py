#!/usr/bin/env python3
"""Capture README screenshots from both live CloudFront addresses without new queries or model calls.

Every /api request other than GET is blocked. The Desk is captured right after connecting (no question
is run, because saved answers contain real resource identifiers); Studio shows existing completed jobs
made from the demo inputs. Screenshots stop if visible text holds the key, the full account ID, an ARN or
a resource ID. Ask before running: it uses the real access key from the deployment secret file.
Usage: .venv/bin/python scripts/capture_live_screenshots.py [ko] [en]
"""
import json
import re
import sys

from capture_screenshots import DESKTOP, OUTPUT, ROOT, shot
from playwright.sync_api import expect, sync_playwright

EXAMPLES = ROOT / "studio/examples"
# Existing completed Studio jobs from the live verification (excel/business and notes/aws-desk)
SALES_JOB = "78464ae3-3e4c-4000-8f64-3df134fa1554"
NOTES_JOB = "ca7c8c78-9330-48e8-ac01-0be3e64f6c0a"
RESOURCE = re.compile(r"arn:aws:|\b(?:i|vpc|subnet|sg|vol|eni|rtb|igw|nat|snap|ami)-[0-9a-f]{8,17}\b")
TEXT = {
    "ko": {"file": "monthly-sales.xlsx",
           "prompt": "첨부한 월별 매출을 막대 차트로 만들고, 차트를 포함한 발표자료와 Word 보고서를 만들어 줘."},
    "en": {"file": "monthly-sales-en.xlsx",
           "prompt": "Turn the attached monthly revenue into a bar chart, then build a slide deck and a Word report "
                     "that include the chart."},
}


def load(path):
    return json.loads((ROOT / path).read_text())


def open_page(browser, domain, secrets, blocked, errors, language):
    context = browser.new_context(viewport=DESKTOP, locale="ko-KR" if language == "ko" else "en-US",
                                  service_workers="block")

    def guard(route):
        # Read-only capture: never upload, create jobs, ask questions or cancel anything
        if route.request.method != "GET":
            blocked.append(route.request.method)
            route.abort("blockedbyclient")
        else:
            route.continue_()

    context.route("**/api/**", guard)
    page = context.new_page()
    page.set_default_timeout(30000)
    page.on("pageerror", lambda error: errors.append(redact(str(error), secrets)))
    page.goto("https://" + domain)
    return page


def redact(value, secrets):
    for secret in secrets:
        value = value.replace(secret, "[redacted]")
    return value


def safe_shot(page, name, secrets, locator=None):
    text = page.locator("body").inner_text()
    if any(secret in text for secret in secrets) or RESOURCE.search(text):
        raise RuntimeError(f"SensitiveVisibleContent: {name}")
    shot(page, name, locator, mask=[page.locator("#access-key:visible")])


def connect(page, token):
    page.locator("#access-key").fill(token)
    page.locator("#connect").click()


def capture_desk(browser, domain, secrets, blocked, errors, language):
    page = open_page(browser, domain, secrets, blocked, errors, language)
    if language == "en":
        page.locator("#language-toggle").click()
    expect(page.locator("html")).to_have_attribute("lang", language)
    connect(page, secrets[0])
    expect(page.locator("#history-refresh")).to_be_enabled()
    safe_shot(page, f"{language}-live-desk", secrets)
    page.context.close()


def select_job(page, job_id):
    items, more = page.locator("#history .history-item"), page.locator("#load-more")
    button = page.locator(f'#history [data-job-id="{job_id}"]')
    # History loads after connecting; page back through older jobs only while the button is shown
    expect(items.first).to_be_visible()
    for _ in range(5):
        if button.count() or not more.is_visible():
            break
        count = items.count()
        more.click()
        expect(items).not_to_have_count(count)
    button.click()
    expect(page.locator("#job-result")).to_be_visible()


def capture_studio(browser, domain, model, secrets, blocked, errors, language):
    page = open_page(browser, domain, secrets, blocked, errors, language)
    if language == "en":
        page.locator("#language").select_option("en")
    expect(page.locator("html")).to_have_attribute("lang", language)
    connect(page, secrets[0])
    expect(page.locator("#model-info")).to_contain_text(model)

    # 1. Brief only: choosing a file does not upload it; the generate button is never pressed
    page.locator("#file-input").set_input_files(str(EXAMPLES / TEXT[language]["file"]))
    page.locator("#prompt").fill(TEXT[language]["prompt"])
    page.locator('label.output-option:has(input[value="chart"])').click()
    expect(page.locator('input[name="output"][value="chart"]')).to_be_checked()
    safe_shot(page, f"{language}-live-studio-brief", secrets, page.locator(".editor-panel"))

    # 2. Existing spreadsheet job: files and the document preview with its chart
    select_job(page, SALES_JOB)
    figure = page.frame_locator("#preview-frame").locator("figure")
    expect(figure.locator("img").first).to_be_visible()
    page.set_viewport_size({"width": DESKTOP["width"],
                            "height": page.evaluate("() => document.documentElement.scrollHeight")})
    figure.first.scroll_into_view_if_needed()
    safe_shot(page, f"{language}-live-studio-result", secrets)
    page.set_viewport_size(DESKTOP)

    # 3. Existing notes job in the AWS Operations Desk style: its workflow diagram file
    select_job(page, NOTES_JOB)
    page.locator('.artifact-card[data-artifact-id="diagram_1_png"] .artifact-main').click()
    page.wait_for_function("() => { const image = document.querySelector('#preview-image');"
                           " return !image.hidden && image.complete && image.naturalWidth > 0; }")
    safe_shot(page, f"{language}-live-studio-diagram", secrets, page.locator(".result-panel"))
    storage = json.dumps(page.evaluate("() => [Object.entries(localStorage), Object.entries(sessionStorage)]"))
    if any(secret in storage for secret in secrets):
        raise RuntimeError("SensitiveBrowserStorage")
    page.context.close()


def run(languages):
    mapping = load("artifacts/cloudfront/deployment.json")["apps"]
    desk, studio = load(mapping["desk"]["deployment_manifest"]), load(mapping["studio"]["deployment_manifest"])
    token = load(desk["secret_file"])["app_access_token"]
    secrets = [token, desk["account_id"]]
    blocked, errors = [], []
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for language in languages:
            capture_desk(browser, mapping["desk"]["domain"], secrets, blocked, errors, language)
            capture_studio(browser, mapping["studio"]["domain"], studio["model"], secrets, blocked, errors, language)
        browser.close()
    if blocked or errors:
        raise RuntimeError({"blocked_requests": blocked, "javascript_errors": errors})


if __name__ == "__main__":
    run(sys.argv[1:] or ["ko", "en"])
