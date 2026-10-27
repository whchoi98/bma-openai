import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { cleanMarkdownProse, displayAccountId, displayModel, hidePendingAccount, maskAccountIds } from "../presentation.js";
import { MarkdownResult } from "../ui/markdown.js";

const account = "123456789012";

test("only the final three account digits appear in prose, code, ARNs, or links", () => {
  const markdown = [
    `계정 ${account}`, `\`${account}\``, "",
    "```json", JSON.stringify({ arn: `arn:aws:lambda:ap-northeast-2:${account}:function:demo` }), "```",
    `[console](https://example.invalid/${account} "${account}")`,
  ].join("\n");
  const html = renderToStaticMarkup(createElement(MarkdownResult, { markdown, accounts: [account] }));
  assert.doesNotMatch(html, new RegExp(account));
  assert.match(html, /\*{9}012/);
  assert.doesNotMatch(html, /href=/);
  assert.equal(displayAccountId(account), "*********012");
  const source = { account_id: account };
  assert.equal(maskAccountIds(JSON.stringify(source), [account]), '{"account_id":"*********012"}');
  assert.equal(source.account_id, account);
  assert.equal(maskAccountIds("i-00000000000000001", ["000000000000"]), "i-00000000000000001");
});

test("partial account digits cannot flash during streaming", () => {
  for (let length = 1; length < 12; length++) {
    const partial = "ID: " + account.slice(0, length);
    assert.equal(hidePendingAccount(partial, [account]), "ID: Account ID");
  }
  assert.equal(hidePendingAccount("ID: " + account, [account, "222222222222"]), "ID: " + account);
  const resource = "i-0abcdef0123456123";
  assert.equal(hidePendingAccount(resource, [account]), resource);
  assert.equal(maskAccountIds(resource, [account], { partial: true }), resource);
});

test("formatted and interrupted account numbers stay masked after streaming stops", () => {
  for (const text of ["1234**5678**9012", "1234-5678-9012", "1234 5678 9012"]) {
    const html = renderToStaticMarkup(createElement(MarkdownResult, {
      markdown: `Account ID: ${text}`, accounts: [account],
    }));
    assert.match(html, /\*{9}012/);
    assert.doesNotMatch(html, /1234|5678|9012/);
    assert.equal(maskAccountIds(text, [account]), "*********012");
  }
  for (const text of ["Account ID: 123456789", "Account ID: **1234-5678**", "<pre>Account ID: 123456789</pre>",
    "Account ID: **1**", "Account ID: **12**", "Account ID: **123**"]) {
    assert.doesNotMatch(maskAccountIds(text, [account], { partial: true }), /\d/);
  }
  const html = renderToStaticMarkup(createElement(MarkdownResult, {
    markdown: "Account ID: 123456789", accounts: [account], incomplete: true,
  }));
  assert.doesNotMatch(html, /123456789/);
  assert.match(html, /\*{9}/);
  assert.equal(maskAccountIds("CPU value: 1234", [account]), "CPU value: 1234");
});

test("narrative punctuation is cleaned without changing identifiers in code or URLs", () => {
  const source = "오리건 — EC2·RDS\n`resource—name·exact`\nhttps://example.invalid/a—b";
  const cleaned = cleanMarkdownProse(source);
  assert.match(cleaned, /^오레곤, EC2, RDS/);
  assert.match(cleaned, /`resource—name·exact`/);
  assert.match(cleaned, /https:\/\/example.invalid\/a—b/);
  const html = renderToStaticMarkup(createElement(MarkdownResult, { markdown: "오리건 — EC2·RDS" }));
  assert.doesNotMatch(html, /[—·]|오리건/);
  assert.match(html, /오레곤, EC2, RDS/);
});

test("the Luna display name does not replace the configured model identifier", () => {
  assert.equal(displayModel("global.openai.gpt-6-luna"), "Luna");
  assert.equal(displayModel("openai.gpt-5.6-luna"), "Luna");
  assert.equal(displayModel("other-model"), "other-model");
});

test("strict export masking hides a known account embedded in a resource name", () => {
  assert.equal(maskAccountIds(`Bucket: logs${account}`, [account], { strict: true }), "Bucket: logs*********012");
  assert.equal(maskAccountIds("Unrelated numeric ID: 987654321098", [account], { strict: true }),
    "Unrelated numeric ID: 987654321098");
});
