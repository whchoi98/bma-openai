// Controlled local SSE fixture: completion waits for the browser test to release it.
import { createApp } from "../server.js";
import { settingsFromEnv } from "../settings.js";
import samples from "../sample-data.json" with { type: "json" };

let release;
const gate = new Promise((resolve) => { release = resolve; });
const first = [
  "## 서울 리소스", "",
  "| 리소스 | 구성 상태 | 근거 |", "| --- | --- | --- |",
  "| **EC2** | `running` | DescribeInstances |",
  "| RDS | `available` | DescribeDBInstances |", "",
  "- [x] 계정 확인", "- [ ] 애플리케이션 추가 점검", "",
  "> 구성 상태만으로 정상 여부를 판정하지 않습니다.", "",
  "오리건 — EC2·RDS 확인", "",
  "```json", '{"account_id":"000000000000","region":"ap-northeast-2"}', "```", "",
  '<script>window.markdownUnsafe=true</script>', "",
  "[실행 금지](javascript:alert%281%29)", "",
  "![외부 이미지](https://example.invalid/should-not-load)", "",
].join("\n");
const last = "\n### 조회 한계\n\n**관측한 범위만** 표시했습니다. ~~전체 계정 정상~~ 같은 결론은 내리지 않습니다.";
const runner = {
  async *stream(prompt, { language = "ko" } = {}) {
    if (prompt === "__disconnect__") {
      yield { type: "tool_result", result: samples.get_account_context };
      yield { type: "answer_delta", delta: "## Partial result\n\nAccount ID: 000000", sequence: 1 };
      throw new Error("Fixture stream interruption");
    }
    const start = language === "en"
      ? `## Seoul resources\n\nAccount: \`${samples.get_account_context.account_id}\`\n\n| Resource | State |\n| --- | --- |\n| EC2 | running |\n`
      : first;
    const end = language === "en" ? "\n### Scope\n\nApplication health was not assessed." : last;
    yield { type: "tool_result", result: samples.get_account_context };
    yield { type: "tool_result", result: samples.list_ec2_instances };
    yield { type: "answer_delta", delta: start, sequence: 1 };
    await gate;
    yield { type: "answer_delta", delta: end, sequence: 2 };
    yield { type: "result", answer: start + end, evidence: [samples.get_account_context, samples.list_ec2_instances],
      errors: [], status: "complete" };
  },
};
const app = createApp(settingsFromEnv({ DATA_MODE: "sample" }), { runner });
const handler = app.listeners("request")[0];
app.removeAllListeners("request");
app.on("request", (req, res) => {
  if (req.url === "/__test/release") { release(); res.end("released"); }
  else handler(req, res);
});
app.listen(Number(process.env.TEST_PORT), "127.0.0.1");
process.on("SIGTERM", () => app.close(() => process.exit(0)));
