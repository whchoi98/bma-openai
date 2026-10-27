import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import test from "node:test";
import JSZip from "jszip";

const account = "123456789012";
function record(extra = {}) {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    created_at: "2026-10-27T03:00:00Z", mode: "live", language: "en", status: "partial",
    account_id: account, app_region: "us-east-1", target_region: "ap-northeast-2",
    supported_services: ["ec2", "vpc", "s3"], requested_services: ["vpc", "s3"],
    model: "global.openai.gpt-6-luna", model_processing_scope: "global",
    prompt: `Account ID: ${account}, review VPCs`,
    answer: `## Observations\nAccount ID: 1234**5678**9012\nEC2 — VPC·configuration\n\n| Check | Result |\n| --- | --- |\n| Network | partial |\n\n- **Inspect** \`vpc-1\`\n`,
    errors: ["AccessDenied"],
    evidence: [{ tool: "list_vpcs", service: "vpc", status: "partial", account_id: account,
      region: "ap-northeast-2", mode: "live", observed_at: "2026-10-27T02:59:00Z",
      resource_count: 1, pagination_complete: false, truncated: true, permission_denied: false,
      scope: { max_pages: 1, unqueried_kinds: ["route_tables"] },
      api_calls: [{ service: "ec2", api: "DescribeVpcs", region: "ap-northeast-2", success: true }],
      data: [{ id: "vpc-1", label: "exact—evidence", arn: `arn:aws:ec2:ap-northeast-2:${account}:vpc/vpc-1` }],
      errors: [{ code: "AccessDenied", api: "DescribeRouteTables" }] }],
    ...extra,
  };
}

async function inspect(buffer) {
  assert.ok(Buffer.isBuffer(buffer));
  assert.equal(buffer.subarray(0, 2).toString(), "PK");
  const zip = await JSZip.loadAsync(buffer);
  const entries = await Promise.all(Object.values(zip.files).filter((f) => !f.dir && /\.(?:xml|rels)$/.test(f.name))
    .map(async (file) => [file.name, await file.async("string")]));
  const xml = Object.fromEntries(entries);
  execFileSync("python3", ["-c",
    "import io,sys,zipfile,xml.etree.ElementTree as E\nz=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))\nfor n in z.namelist():\n if n.endswith(('.xml','.rels')): E.fromstring(z.read(n))"], { input: buffer });
  return { xml, all: entries.map(([, value]) => value).join("\n"),
    visible: entries.filter(([name]) => /word\/document\.xml|ppt\/slides\/slide\d+\.xml/.test(name)).map(([, value]) => value).join("\n"),
    notes: entries.filter(([name]) => /ppt\/notesSlides\/notesSlide\d+\.xml/.test(name)).map(([, value]) => value).join("\n") };
}

for (const format of ["docx", "pptx"]) {
  test(`${format} contains valid Office XML, scope, UTC/KST, failures and redacted evidence`, async () => {
    const { renderOfficeReport, OFFICE_MIME } = await import("../office-reports.js");
    const source = record(), original = structuredClone(source);
    const output = await inspect(await renderOfficeReport(source, format, { accountIds: [account] }));
    assert.deepEqual(source, original);
    assert.match(OFFICE_MIME[format], /^application\/vnd\.openxmlformats-officedocument\./);
    assert.doesNotMatch(output.all, /123456789012|1234|5678|9012/);
    assert.match(output.all, /\*{9}012/);
    for (const expected of ["2026-10-27T03:00:00Z", "2026-10-27 12:00:00 KST",
      "2026-10-27T02:59:00Z", "ap-northeast-2", "us-east-1", "DescribeVpcs", "DescribeRouteTables",
      "AccessDenied", "pagination_complete", "unqueried_kinds", "route_tables", "vpc-1", "NanumSquare"]) {
      assert.ok(output.all.includes(expected), `missing ${expected}`);
    }
    assert.match(output.all, /exact—evidence/);
    assert.doesNotMatch(output.visible, /EC2 —|VPC·configuration/);
    assert.match(output.visible, /AWS operations report/);
    if (format === "docx") assert.match(output.xml["word/document.xml"], /<w:tbl>/);
    else assert.match(output.notes, /DescribeVpcs/);
  });

  test(`${format} redacts known accounts in failed reports with no evidence and split Markdown`, async () => {
    const { renderOfficeReport } = await import("../office-reports.js");
    const source = record({ account_id: undefined, evidence: [], errors: ["StreamInterrupted"],
      status: "failed", prompt: "Account ID: **1234-5678**",
      answer: `Account ID: 123456789\n1234 **5678** 9012\n\`${account}\`\n[Account](${account})` });
    const output = await inspect(await renderOfficeReport(source, format, { accountIds: [account] }));
    assert.doesNotMatch(output.all, /123456789|1234|5678|9012/);
    assert.match(output.all, /StreamInterrupted/);
    assert.match(output.all, /\*{9}/);
  });

  test(`${format} redacts numeric identities and independently discovered ARN accounts`, async () => {
    const { renderOfficeReport } = await import("../office-reports.js");
    const source = record();
    source.evidence[0].data[0].owner_id = 999988887777;
    source.evidence[0].scope.related_account = 123456789012;
    source.evidence[0].data[0].related = "arn:aws:ec2:ap-northeast-2:222233334444:vpc/vpc-2";
    const output = await inspect(await renderOfficeReport(source, format, { accountIds: [account] }));
    assert.doesNotMatch(output.all, /123456789012|999988887777|222233334444/);
    assert.match(output.all, /\*{9}777/);
    assert.match(output.all, /\*{9}444/);
  });

  test(`${format} redacts account digits embedded in resource names and keys`, async () => {
    const { renderOfficeReport } = await import("../office-reports.js");
    const source = record({ prompt: "Inspect logs123456789012", answer: "Resource `logs123456789012`",
      errors: ["Error123456789012"] });
    source.evidence[0].data[0].id = "logs123456789012";
    source.evidence[0].data[0]["key123456789012tail"] = "logs123456789012";
    const original = structuredClone(source);
    const output = await inspect(await renderOfficeReport(source, format, { accountIds: [account] }));
    assert.doesNotMatch(output.all, /123456789012/);
    assert.match(output.all, /logs\*{9}012/);
    assert.match(output.all, /key\*{9}012tail/);
    assert.deepEqual(source, original);
  });
}

test("presentation size is bounded and visibly discloses summary truncation while preserving notes", async () => {
  const { renderOfficeReport, OFFICE_LIMITS } = await import("../office-reports.js");
  const answer = "ANSWER_START " + "Observed configuration requires follow-up. ".repeat(1400) + " ANSWER_END";
  const output = await inspect(await renderOfficeReport(record({ answer }), "pptx", { accountIds: [account] }));
  const slideNames = Object.keys(output.xml).filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name));
  assert.ok(slideNames.length <= OFFICE_LIMITS.maxSlides);
  assert.match(output.visible, /Presentation summary truncated/);
  assert.match(output.notes, /ANSWER_START/); assert.match(output.notes, /ANSWER_END/);
});

test("Office exports fail explicitly for unsupported formats and excessive input", async () => {
  const { renderOfficeReport, OFFICE_LIMITS } = await import("../office-reports.js");
  await assert.rejects(renderOfficeReport(record(), "pdf"), /UnsupportedOfficeFormat/);
  await assert.rejects(renderOfficeReport(record({ answer: "x".repeat(OFFICE_LIMITS.maxInputBytes + 1) }), "docx"),
    /OfficeReportTooLarge/);
});

test("Office notes preserve a validated routing UUID under sample account redaction", async () => {
  const { renderOfficeReport } = await import("../office-reports.js");
  const source = record({ account_id: "000000000000", mode: "sample", evidence: [], errors: [],
    status: "complete", prompt: "Account ID: 000000000000", answer: "No resources" });
  const output = await inspect(await renderOfficeReport(source, "pptx", { accountIds: ["000000000000"] }));
  assert.ok(output.notes.includes(source.id));
  assert.match(output.visible, /Account ID: \*{9}000/);
});

test("Office redaction never exempts invalid routing IDs", async () => {
  const { renderOfficeReport } = await import("../office-reports.js");
  await assert.rejects(renderOfficeReport(record({ id: "report-" + account }), "pptx", { accountIds: [account] }),
    /InvalidOfficeRecord/);
});

test("Korean Office reports keep Korean labels and sample scope", async () => {
  const { renderOfficeReport } = await import("../office-reports.js");
  const output = await inspect(await renderOfficeReport(record({
    language: "ko", mode: "sample", answer: "오리건 — VPC·구성을 확인했습니다.",
  }), "docx", { accountIds: [account] }));
  assert.match(output.visible, /AWS 운영 조회 보고서/);
  assert.match(output.visible, /샘플/);
  assert.match(output.visible, /오레곤, VPC, 구성을 확인했습니다/);
});
