import { createElement } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cleanNarrative, hidePendingAccount, maskAccountIds, restoreAccountMasks } from "./presentation.js";

const h = createElement;

function presentation({ accounts }) {
  return (tree) => {
    const visit = (node) => {
      if (node.type === "text") node.value = cleanNarrative(maskAccountIds(restoreAccountMasks(node.value), accounts));
      if (node.type === "code" || node.type === "inlineCode") node.value = maskAccountIds(restoreAccountMasks(node.value), accounts);
      if (node.title) node.title = cleanNarrative(maskAccountIds(restoreAccountMasks(node.title), accounts));
      if (node.alt) node.alt = cleanNarrative(maskAccountIds(restoreAccountMasks(node.alt), accounts));
      // A masked account must not remain visible in link previews or DOM attributes.
      if (node.url && (maskAccountIds(node.url, accounts) !== node.url || restoreAccountMasks(node.url) !== node.url)) node.url = "";
      for (const child of node.children || []) visit(child);
    };
    visit(tree);
  };
}

const components = (language) => ({
  table({ children }) {
    return h("div", { className: "markdown-table", tabIndex: 0, "aria-label": language === "en" ? "Results table" : "조회 결과 표" },
      h("table", null, children));
  },
  a({ href, children, title }) {
    if (!href) return h("span", null, children);
    return h("a", { href, title, target: "_blank", rel: "noopener noreferrer" }, children);
  },
  img({ alt }) {
    return h("span", { className: "markdown-image-label" }, alt || (language === "en" ? "Image" : "이미지"));
  },
});

export function MarkdownResult({ markdown, streaming = false, incomplete = false, accounts = [], language = "ko" }) {
  const masked = maskAccountIds(markdown, accounts, { markers: true, partial: streaming || incomplete, strict: true });
  const source = streaming || incomplete ? hidePendingAccount(masked, accounts) : masked;
  return h("div", { className: "markdown-body", "aria-busy": streaming },
    h(Markdown, { remarkPlugins: [remarkGfm, [presentation, { accounts }]], components: components(language), skipHtml: true }, source),
    streaming ? h("span", { className: "streaming-cursor", "aria-hidden": true }) : null);
}
