import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownResult } from "../ui/markdown.js";

const render = (markdown, streaming = false) =>
  renderToStaticMarkup(createElement(MarkdownResult, { markdown, streaming }));

test("query Markdown renders headings, GFM tables, lists, code and task lists", () => {
  const html = render([
    "## 서울 리소스", "",
    "| 리소스 | 상태 |", "| --- | --- |", "| **EC2** | `running` |", "",
    "- 확인한 목록", "- ~~이전 상태~~", "", "- [x] 계정 확인", "- [ ] 추가 점검", "",
    "> 구성 상태는 앱 정상의 증거가 아닙니다.", "",
    "```json", '{"region":"ap-northeast-2"}', "```",
  ].join("\n"));
  assert.match(html, /<h2>서울 리소스<\/h2>/);
  assert.match(html, /<table>/);
  assert.match(html, /<thead>/);
  assert.match(html, /<strong>EC2<\/strong>/);
  assert.match(html, /<code>running<\/code>/);
  assert.match(html, /<del>이전 상태<\/del>/);
  assert.match(html, /type="checkbox"/);
  assert.match(html, /disabled=""/);
  assert.match(html, /<blockquote>/);
  assert.match(html, /<pre><code class="language-json">/);
  assert.match(html, /class="markdown-table"/);
});

test("raw HTML, unsafe URLs and remote images cannot execute or fetch data", () => {
  const html = render([
    '<script>window.leaked=true</script>', "",
    '<img src=x onerror="window.leaked=true">', "",
    "[unsafe](javascript:alert%281%29)", "",
    "[공식 문서](https://docs.aws.amazon.com/)", "",
    "![외부 이미지](https://example.invalid/track?account=private)",
  ].join("\n"));
  assert.doesNotMatch(html, /<script|<img|javascript:|onerror=/i);
  assert.match(html, /href="https:\/\/docs.aws.amazon.com\/"/);
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /외부 이미지/);
  assert.doesNotMatch(html, /example\.invalid/);
});

test("partial streamed Markdown renders immediately and final output removes the cursor", () => {
  const partial = render("## 조회 중\n\n**EC2", true);
  assert.match(partial, /EC2/);
  assert.match(partial, /aria-busy="true"/);
  assert.match(partial, /streaming-cursor/);
  const complete = render("## 조회 결과\n\n**EC2** 확인 완료", false);
  assert.match(complete, /<strong>EC2<\/strong>/);
  assert.doesNotMatch(complete, /streaming-cursor/);
});
