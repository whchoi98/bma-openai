import { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, HeadingLevel,
  WidthType, BorderStyle, Footer, AlignmentType, PageNumber } from "docx";
import PptxGenJS from "pptxgenjs";
import { cleanMarkdownProse, restoreAccountMasks } from "./presentation.js";
import { historyTimeKst, reportAccountIds, redactReportValue, reportServiceScope, validateRunId } from "./history.js";

export const OFFICE_MIME = Object.freeze({
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
});
export const OFFICE_LIMITS = Object.freeze({ maxInputBytes: 1_000_000, maxOutputBytes: 4_000_000, maxSlides: 40 });
const FONT = "NanumSquare";
const FONT_OPTIONS = { ascii: FONT, eastAsia: FONT, hAnsi: FONT, cs: FONT };
const COLORS = { primary: "142334", accent: "0077B6", text: "253548", muted: "526476",
  border: "D1DBE5", header: "E8EFF5", stripe: "F6F8FA" };
const sourceKeys = ["id", "created_at", "mode", "language", "status", "account_id", "app_region", "target_region",
  "supported_services", "requested_services", "model", "model_processing_scope", "prompt", "answer", "errors", "evidence"];

function text(value) {
  // XML 1.0 cannot contain control characters; show their escape rather than
  // silently removing evidence. JSON evidence already encodes them this way.
  return restoreAccountMasks(String(value ?? "")).toWellFormed().replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g,
    (character) => "\\u" + character.charCodeAt(0).toString(16).padStart(4, "0"));
}

function labels(language) {
  const en = language === "en";
  return {
    en, title: en ? "AWS operations report" : "AWS 운영 조회 보고서",
    scope: en ? "Service scope and query coverage" : "서비스 범위와 조회 완료 여부",
    answer: en ? "Observations and answer" : "관측 결과와 답변",
    errors: en ? "Execution errors" : "실행 오류",
    evidence: en ? "Evidence" : "근거",
    none: en ? "None recorded" : "기록 없음",
    notQueried: en ? "No resource query evidence was returned." : "리소스 조회 근거를 받지 못했습니다.",
    sample: en ? "Sample data, no AWS or model calls" : "샘플 데이터, AWS 및 모델 호출 없음",
    live: en ? "Saved live query" : "저장된 실제 조회",
    limits: en ? "Configuration observations do not establish application health. Unqueried, empty, denied and partial results remain distinct."
      : "구성 관측만으로 애플리케이션 정상 여부를 판단하지 않습니다. 미조회, 빈 결과, 권한 거부, 부분 조회를 구분합니다.",
    truncated: en ? "Presentation summary truncated" : "발표 자료 요약 일부 생략",
    notes: en ? "The complete redacted answer, errors and evidence are preserved in the speaker notes of the Evidence slide."
      : "계정을 가린 답변, 오류, 근거 전체는 근거 슬라이드의 발표자 노트에 보존했습니다.",
  };
}

function prepare(record, accountIds) {
  if (!record || typeof record !== "object" || Array.isArray(record)) throw new Error("InvalidOfficeRecord");
  let serialized;
  try { serialized = JSON.stringify(record); } catch { throw new Error("InvalidOfficeRecord"); }
  if (Buffer.byteLength(serialized) > OFFICE_LIMITS.maxInputBytes) throw new Error("OfficeReportTooLarge");
  if (!Array.isArray(record.evidence || []) || !Array.isArray(record.errors || [])) throw new Error("InvalidOfficeRecord");
  const accounts = reportAccountIds(record, accountIds);
  const source = Object.fromEntries(sourceKeys.filter((key) => record[key] !== undefined).map((key) => [key, record[key]]));
  const safe = redactReportValue(source, accounts, {
    markers: true, strict: true, partial: Boolean(record.errors?.length) || record.status !== "complete",
  });
  if (source.id !== undefined) {
    try { safe.id = validateRunId(source.id); }
    catch { throw new Error("InvalidOfficeRecord"); }
  }
  safe.prompt = cleanMarkdownProse(safe.prompt || "");
  safe.answer = cleanMarkdownProse(safe.answer || "");
  safe.evidence ||= []; safe.errors ||= [];
  const words = labels(record.language), scope = reportServiceScope(safe);
  const account = text(safe.account_id || redactReportValue(accounts.join(", "), accounts,
    { markers: true, strict: true })) || words.none;
  const context = safe.evidence.find((item) => item.tool === "get_account_context")?.data?.[0];
  const processing = safe.mode === "sample" ? words.sample
    : (safe.model_processing_scope || context?.data_processing_scope) === "global"
      ? (words.en ? "Global Bedrock inference profile" : "글로벌 Bedrock 추론 프로파일")
      : "BMA (us-east-1)";
  const metadata = [
    [words.en ? "Mode" : "모드", safe.mode === "sample" ? words.sample : words.live],
    [words.en ? "Account ID" : "계정 ID", account],
    [words.en ? "App and Runtime region" : "앱과 Runtime 실행 리전", safe.app_region || "us-east-1"],
    [words.en ? "Target region" : "조회 대상 리전", safe.target_region || "ap-northeast-2"],
    [words.en ? "Report status" : "보고서 상태", safe.status || words.none],
    ["UTC", safe.created_at || words.none], ["Asia/Seoul", historyTimeKst(safe.created_at)],
    [words.en ? "Model processing" : "모델 처리 경로", processing],
    [words.en ? "Model" : "모델", safe.model || words.none],
    [words.en ? "Supported services" : "지원 서비스", scope.supported_services.join(", ") || words.none],
    [words.en ? "Requested services (saved)" : "저장된 요청 서비스", scope.requested_services.join(", ") || words.none],
    [words.en ? "Queried services" : "조회 서비스", scope.queried_services.join(", ") || words.none],
    [words.en ? "Unqueried services" : "미조회 서비스", scope.unqueried_services.join(", ") || words.none],
    [words.en ? "Request" : "요청", safe.prompt],
  ];
  return { record: safe, words, metadata, scope };
}

// Adapted from awsops report-docx.ts / report-pptx.ts classifyLine and inline
// parsers. Redaction runs first, before text is separated into formatting runs.
function classifyLine(line) {
  const raw = line.trim();
  if (!raw) return { type: "blank", raw: "" };
  const heading = /^(#{1,4})\s+(.+)$/.exec(raw);
  if (heading) return { type: "heading", level: heading[1].length, raw: heading[2] };
  if (/^(?:-{3,}|\*{3,})$/.test(raw)) return { type: "divider", raw: "" };
  if (/^\|[\s:|-]+\|$/.test(raw)) return { type: "table-sep", raw };
  if (raw.startsWith("|") && raw.endsWith("|")) return {
    type: "table-row", raw, cells: raw.slice(1, -1).split(/(?<!\\)\|/).map((cell) => cell.trim().replaceAll("\\|", "|")),
  };
  if (/^[-*]\s+\[[ xX]\]\s/.test(raw)) return { type: "list", raw: raw.replace(/^[-*]\s+/, "") };
  if (/^[-*]\s/.test(raw)) return { type: "list", raw: raw.replace(/^[-*]\s+/, "") };
  if (raw.startsWith("> ")) return { type: "quote", raw: raw.slice(2) };
  return { type: "text", raw };
}

function inlineParts(value) {
  // Protect already masked IDs, whose asterisks are content, not Markdown.
  const protectedText = String(value).replace(/\*{9}(\d{3})?/g, (_, suffix) => `\uE000${suffix || "MASK"}\uE001`);
  return protectedText.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/).filter(Boolean).map((part) => {
    if (part.startsWith("**") && part.endsWith("**")) return { text: part.slice(2, -2), bold: true };
    if (part.startsWith("`") && part.endsWith("`")) return { text: part.slice(1, -1), code: true };
    if (part.startsWith("*") && part.endsWith("*")) return { text: part.slice(1, -1), italics: true };
    return { text: part };
  });
}

const stripMd = (value) => inlineParts(value).map((part) => text(part.text)).join("");
const run = (value, options = {}) => new TextRun({ text: text(value), font: FONT_OPTIONS, size: 20,
  color: COLORS.text, ...options });
const inline = (value, options = {}) => inlineParts(value).map((part) => run(part.text, {
  bold: part.bold, italics: part.italics, ...(part.code ? { color: COLORS.accent, size: 18 } : {}), ...options,
}));
const paragraph = (value, options = {}) => new Paragraph({
  spacing: { after: 90 }, children: inline(value), ...options,
});
const heading = (value, level = HeadingLevel.HEADING_1) => new Paragraph({
  heading: level, spacing: { before: 220, after: 120 },
  children: [run(stripMd(value), { bold: true, size: level === HeadingLevel.HEADING_1 ? 28 : 24, color: COLORS.primary })],
});

function buildTable(rows, header = true) {
  const columns = Math.max(...rows.map((row) => row.length));
  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: Object.fromEntries(["top", "bottom", "left", "right", "insideHorizontal", "insideVertical"]
      .map((key) => [key, { style: BorderStyle.SINGLE, size: 1, color: COLORS.border }])),
    rows: rows.map((row, index) => new TableRow({
      tableHeader: header && index === 0,
      children: Array.from({ length: columns }, (_, col) => new TableCell({
        width: { size: Math.floor(100 / columns), type: WidthType.PERCENTAGE },
        shading: { fill: header && index === 0 ? COLORS.header : index % 2 ? COLORS.stripe : "FFFFFF" },
        children: [new Paragraph({ spacing: { after: 50 },
          children: inline(row[col] || "", { size: 18, bold: header && index === 0 }) })],
      })),
    })),
  });
}

function convertContent(markdown) {
  const lines = String(markdown).split(/\r?\n/), elements = [];
  let fenced = false;
  for (let index = 0; index < lines.length; index++) {
    if (/^\s*```/.test(lines[index])) { fenced = !fenced; continue; }
    if (fenced) {
      elements.push(new Paragraph({ spacing: { after: 30 }, children: [run(lines[index], { size: 17 })] }));
      continue;
    }
    const line = classifyLine(lines[index]);
    if (line.type === "heading") elements.push(heading(line.raw,
      line.level <= 2 ? HeadingLevel.HEADING_2 : HeadingLevel.HEADING_3));
    else if (line.type === "table-row") {
      const rows = [line.cells];
      while (index + 1 < lines.length) {
        const next = classifyLine(lines[index + 1]);
        if (!["table-row", "table-sep"].includes(next.type)) break;
        if (next.cells) rows.push(next.cells);
        index++;
      }
      if (Math.max(...rows.map((row) => row.length)) > 12) {
        rows.forEach((row) => elements.push(paragraph(row.join(" | "))));
      } else elements.push(buildTable(rows));
    } else if (line.type === "quote") elements.push(paragraph(line.raw, {
      indent: { left: 300 }, border: { left: { style: BorderStyle.SINGLE, size: 8, color: COLORS.accent, space: 8 } },
    }));
    else if (line.type === "list") elements.push(paragraph("- " + line.raw));
    else if (line.type === "text") elements.push(paragraph(line.raw));
  }
  return elements;
}

function coverageRows(prepared) {
  const { record, words } = prepared;
  const rows = [words.en ? ["Service / tool", "Result", "Returned resources", "Pagination complete", "Truncated"]
    : ["서비스 / 도구", "결과", "반환 리소스", "페이지 완료", "잘림"]];
  for (const item of record.evidence.filter((result) => result.service !== "sts")) {
    rows.push([`${item.service} / ${item.tool}`, item.status,
      ["ok", "empty", "partial"].includes(item.status) ? String(item.resource_count ?? words.none) : words.none,
      String(item.pagination_complete === true), String(item.truncated === true)]);
  }
  return rows;
}

function errorLines(errors) {
  return errors.map((error) => typeof error === "string" ? error : JSON.stringify(error));
}

async function renderDocx(prepared) {
  const { record, words, metadata } = prepared;
  const elements = [
    heading(words.title), buildTable(metadata, false), heading(words.scope),
  ];
  const rows = coverageRows(prepared);
  if (rows.length > 1) elements.push(buildTable(rows)); else elements.push(paragraph(words.notQueried));
  elements.push(paragraph(words.limits), heading(words.answer), ...convertContent(record.answer),
    heading(words.errors), ...errorLines(record.errors).map((error) => paragraph(error)));
  if (!record.errors.length) elements.push(paragraph(words.none));
  elements.push(heading(words.evidence));
  if (!record.evidence.length) elements.push(paragraph(words.notQueried));
  for (const item of record.evidence) {
    elements.push(heading(`${item.service} / ${item.tool}`, HeadingLevel.HEADING_2),
      paragraph(`UTC: ${item.observed_at || words.none}`),
      paragraph(`Asia/Seoul: ${historyTimeKst(item.observed_at)}`));
    // Adapted from report-generator.ts jsonBlock; keep the full evidence instead
    // of its original abbreviate() behavior, which silently took only 20 rows.
    const json = text(JSON.stringify(item, null, 2));
    for (const line of json.split("\n")) elements.push(new Paragraph({
      spacing: { after: 20 }, children: [run(line, { size: 17 })],
    }));
  }
  if (elements.length > 20_000) throw new Error("OfficeReportTooLarge");
  const document = new Document({
    creator: "AWS operations", title: words.title, description: words.limits,
    styles: { default: {
      document: { run: { font: FONT_OPTIONS, size: 20, color: COLORS.text },
        paragraph: { spacing: { line: 276 } } },
      heading1: { run: { font: FONT_OPTIONS, size: 28, bold: true, color: COLORS.primary } },
      heading2: { run: { font: FONT_OPTIONS, size: 24, bold: true, color: COLORS.primary } },
      heading3: { run: { font: FONT_OPTIONS, size: 22, bold: true, color: COLORS.primary } },
    } },
    sections: [{
      properties: { page: { margin: { top: 1080, right: 900, bottom: 1080, left: 900 } } },
      footers: { default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.RIGHT, children: [run(words.title + " | ", { size: 16, color: COLORS.muted }),
          new TextRun({ children: [PageNumber.CURRENT], font: FONT_OPTIONS, size: 16, color: COLORS.muted })],
      })] }) },
      children: elements,
    }],
  });
  return Packer.toBuffer(document);
}

// Adapted from report-pptx.ts wrapLineCount and overflow splitting. Wide Korean
// glyphs count as two units, and slides have a fixed number of display lines.
function wrapLines(value, width = 100) {
  const result = [];
  for (const line of text(value).split(/\r?\n/)) {
    let current = "", units = 0;
    for (const char of line) {
      const next = char.codePointAt(0) >= 0x2e80 ? 2 : 1;
      if (units + next > width) { result.push(current); current = ""; units = 0; }
      current += char; units += next;
    }
    result.push(current);
  }
  return result;
}

function presentationLines(markdown) {
  let fenced = false;
  return String(markdown).split(/\r?\n/).flatMap((value) => {
    if (/^\s*```/.test(value)) { fenced = !fenced; return []; }
    if (fenced) return wrapLines(value);
    const line = classifyLine(value);
    if (["divider", "table-sep", "blank"].includes(line.type)) return [];
    const body = line.cells ? line.cells.map(stripMd).join(" | ") : (line.type === "list" ? "- " : "") + stripMd(line.raw);
    return wrapLines(body);
  });
}

async function renderPptx(prepared) {
  const { record, words, metadata } = prepared;
  const pages = [], linesPerPage = 18;
  let anyTruncated = false;
  const addSection = (title, lines, maximum) => {
    if (!lines.length) lines = [words.none];
    const capacity = maximum * linesPerPage;
    const truncated = lines.length > capacity;
    const selected = lines.slice(0, truncated ? capacity - 2 : capacity);
    if (truncated) {
      anyTruncated = true;
      selected.push(`${words.truncated}: ${lines.length - selected.length} ${words.en ? "display lines omitted." : "표시 줄 생략."}`,
        words.en ? "Full text is in the Evidence slide notes." : "전체 내용은 근거 슬라이드의 발표자 노트에 있습니다.");
    }
    for (let offset = 0; offset < selected.length; offset += linesPerPage) {
      pages.push({ title: offset ? `${title} (${Math.floor(offset / linesPerPage) + 1})` : title,
        lines: selected.slice(offset, offset + linesPerPage) });
    }
  };
  addSection(words.title, metadata.flatMap(([key, value]) => wrapLines(`${key}: ${stripMd(value)}`)), 3);
  const coverage = record.evidence.filter((item) => item.service !== "sts").flatMap((item) => [
    ...wrapLines(`${item.service} / ${item.tool}: ${item.status}`),
    ...wrapLines(`resource_count: ${["ok", "empty", "partial"].includes(item.status) ? item.resource_count ?? words.none : words.none}, pagination_complete: ${item.pagination_complete === true}, truncated: ${item.truncated === true}`),
    ...wrapLines(`scope: ${text(JSON.stringify(item.scope || {}))}`),
    ...wrapLines(`UTC: ${item.observed_at || words.none} / Asia/Seoul: ${historyTimeKst(item.observed_at)}`),
  ]);
  addSection(words.scope, coverage.length ? coverage : [words.notQueried], 8);
  addSection(words.errors, errorLines(record.errors).flatMap((error) => wrapLines(error)), 4);
  addSection(words.answer, presentationLines(record.answer), 20);
  pages.push({ title: words.evidence, lines: [
    ...wrapLines(words.notes), ...wrapLines(words.limits),
    ...(anyTruncated ? [words.truncated] : []),
    `UTC: ${record.created_at || words.none}`, `Asia/Seoul: ${historyTimeKst(record.created_at)}`,
    `${words.en ? "Saved tool results" : "저장된 도구 결과"}: ${record.evidence.length}`,
  ], notes: text(JSON.stringify({ ...record,
    export_notes: { full_saved_evidence: true, presentation_summary_truncated: anyTruncated,
      created_at_kst: historyTimeKst(record.created_at),
      observed_times: record.evidence.map((item) => ({ tool: item.tool, utc: item.observed_at,
        asia_seoul: historyTimeKst(item.observed_at) })) } }, null, 2)) });
  if (pages.length > OFFICE_LIMITS.maxSlides) throw new Error("OfficeReportTooLarge");
  const presentation = new PptxGenJS();
  presentation.layout = "LAYOUT_WIDE";
  presentation.author = "AWS operations"; presentation.subject = words.limits; presentation.title = words.title;
  presentation.lang = words.en ? "en-US" : "ko-KR";
  presentation.theme = { headFontFace: FONT, bodyFontFace: FONT, lang: presentation.lang };
  pages.forEach((page, index) => {
    const slide = presentation.addSlide();
    slide.background = { color: "FFFFFF" };
    slide.addShape(presentation.ShapeType.rect, {
      x: 0, y: 0, w: 13.333333, h: 0.09, fill: { color: COLORS.accent }, line: { color: COLORS.accent },
    });
    slide.addText(text(page.title), { x: 0.55, y: 0.35, w: 12.2, h: 0.5, fontFace: FONT,
      fontSize: 24, bold: true, color: COLORS.primary, margin: 0, breakLine: false });
    slide.addText(page.lines.map(text).join("\n"), { x: 0.55, y: 1.1, w: 12.2, h: 5.6,
      fontFace: FONT, fontSize: 14, color: COLORS.text, margin: 0, valign: "top", fit: "shrink",
      paraSpaceAfterPt: 5, lang: presentation.lang });
    slide.addText(`${words.title} | ${index + 1}/${pages.length}`, {
      x: 0.55, y: 7.02, w: 12.2, h: 0.2, fontFace: FONT, fontSize: 9, color: COLORS.muted,
      margin: 0, align: "right",
    });
    if (page.notes) slide.addNotes(page.notes);
  });
  return presentation.write({ outputType: "nodebuffer", compression: true });
}

export async function renderOfficeReport(record, format, { accountIds = [] } = {}) {
  if (!Object.hasOwn(OFFICE_MIME, format)) throw new Error("UnsupportedOfficeFormat");
  const prepared = prepare(record, accountIds);
  const output = Buffer.from(await (format === "docx" ? renderDocx(prepared) : renderPptx(prepared)));
  if (output.length > OFFICE_LIMITS.maxOutputBytes) throw new Error("OfficeReportTooLarge");
  return output;
}
