import { existsSync, readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MarkdownResult } from "./markdown.js";
import { maskAccountIds } from "./presentation.js";

const staticRoot = existsSync(new URL("./static/report.css", import.meta.url))
  ? new URL("./static/", import.meta.url) : new URL("../webapp/static/", import.meta.url);
const css = readFileSync(new URL("report.css", staticRoot), "utf8");
const font = readFileSync(new URL("fonts/NanumSquareB.otf", staticRoot)).toString("base64");
const standaloneCss = css.replace("/static/fonts/NanumSquareB.otf", `data:font/otf;base64,${font}`);
const fontLicense = readFileSync(new URL("fonts/OFL.txt", staticRoot), "utf8")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

export function prepareHtmlReport(record, { redact = false, accountIds = [] } = {}) {
  const accounts = redact ? [...new Set([
    ...accountIds, ...(record.evidence || []).map((item) => item.account_id),
  ].filter((value) => typeof value === "string" && /^\d{12}$/.test(value)))] : [];
  const incomplete = Boolean(record.errors?.length);
  const answerHtml = renderToStaticMarkup(createElement(MarkdownResult, {
    markdown: record.answer || "", accounts, incomplete, language: record.language,
  }));
  const present = (value) => {
    if (typeof value === "string") return maskAccountIds(value, accounts, { partial: incomplete, strict: true });
    if (Array.isArray(value)) return value.map(present);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, present(item)]));
    return value;
  };
  return { record: redact ? present(record) : record, answerHtml };
}

export function reportHead(language, { preview = false, theme = "light" } = {}) {
  const lang = language === "en" ? "en" : "ko";
  const appearance = theme === "dark" ? "dark" : "light";
  const title = lang === "en" ? "AWS operations report" : "AWS 운영 조회 보고서";
  const policy = preview
    ? "default-src 'none'; style-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'"
    : "default-src 'none'; style-src 'unsafe-inline'; font-src data:; base-uri 'none'; form-action 'none'";
  const styles = preview ? '<link rel="stylesheet" href="/static/report.css">' : `<style>${standaloneCss}</style>`;
  const license = preview ? "" : `<template id="font-license"><pre>${fontLicense}</pre></template>`;
  return `<!doctype html><html lang="${lang}" data-theme="${appearance}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="${policy}"><title>${title}</title>${styles}</head><body>${license}`;
}
