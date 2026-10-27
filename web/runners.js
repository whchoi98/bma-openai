import { BmaClient, BmaError } from "./bma.js";
import { publicItems } from "./evidence.js";
import { summarize } from "./reports.js";
import samples from "./sample-data.json" with { type: "json" };
import { cleanMarkdownProse } from "./presentation.js";

export class SampleRunner {
  async *stream(prompt, { language = "ko" } = {}) {
    const text = prompt.toLowerCase();
    const all = (text.includes("보고서") || text.includes("report")) &&
      !["ec2", "rds", "ecs", "lambda", "알람", "alarm", "vpc", "ebs", "ecr", "s3", "dynamodb",
        "elasticache", "opensearch", "msk", "kafka"].some((s) => text.includes(s));
    const security = ["보안", "security"].some((s) => text.includes(s));
    const configuration = ["설정", "점검", "configuration", "check", "health"].some((s) => text.includes(s));
    const names = ["get_account_context"];
    if (all || text.includes("ec2")) {
      names.push("list_ec2_instances");
      if (all || ["점검", "실패", "health", "status check", "failed"].some((s) => text.includes(s))) names.push("get_ec2_instance_health");
    }
    if (all || text.includes("rds")) names.push("list_rds_instances");
    if (all || text.includes("ecs")) names.push("list_ecs_clusters", "list_ecs_services", "get_ecs_service_health");
    if (all || text.includes("lambda") || text.includes("람다")) names.push("list_lambda_functions", "get_resource_metrics:sample-worker", "get_resource_metrics:sample-idle");
    if (all || ["알람", "alarm", "cloudwatch"].some((s) => text.includes(s))) names.push("list_cloudwatch_alarms");
    if (all || ["vpc", "관계도", "topology", "relationship"].some((s) => text.includes(s))) {
      names.push("list_vpcs");
      if (all || ["관계도", "topology", "relationship"].some((s) => text.includes(s))) names.push("get_vpc_topology");
      if (all || security || text.includes("security group") || text.includes("보안 그룹")) names.push("list_security_groups");
    }
    if (all || text.includes("ebs")) names.push("list_ebs_volumes");
    if (all || text.includes("ecr")) names.push("list_ecr_repositories");
    if (all || text.includes("s3")) {
      names.push("list_s3_buckets");
      if (all || configuration || security) names.push("get_s3_bucket_configuration");
    }
    if (all || text.includes("dynamodb")) {
      names.push("list_dynamodb_tables");
      if (all || configuration || security) names.push("get_dynamodb_table_configuration");
    }
    if (all || ["elasticache", "valkey", "redis"].some((s) => text.includes(s))) names.push("list_elasticache_clusters");
    if (all || text.includes("opensearch")) {
      names.push("list_opensearch_domains");
      if (all || configuration || security) names.push("get_opensearch_domain_configuration");
    }
    if (all || text.includes("msk") || text.includes("kafka")) names.push("list_msk_clusters");
    const evidence = names.map((name) => structuredClone(samples[name]));
    for (const result of evidence) yield { type: "tool_result", result };
    const answer = (language === "en" ? "Sample data. No AWS APIs or models were called.\n\n"
      : "샘플 데이터입니다. AWS API와 모델을 호출하지 않았습니다.\n\n")
      + (names.length === 1 ? (language === "en" ? "Choose a supported example question." : "지원하는 예제 질문을 선택하세요.")
        : summarize(evidence, language));
    yield { type: "result", answer, evidence, errors: [], status: "complete" };
  }
}

const END = new Set(["agent.session.turn.completed", "agent.session.completed"]);
const FAILED = new Set(["agent.session.turn.failed", "agent.session.turn.cancelled", "agent.session.failed", "agent.session.environment.failed", "error"]);

export class LiveRunner {
  constructor(settings, clientFactory = (options) => new BmaClient(settings, options)) {
    this.settings = settings; this.clientFactory = clientFactory;
  }
  async *stream(prompt, { signal, language = "ko" } = {}) {
    const text = (ko, en) => language === "en" ? en : ko;
    const client = this.clientFactory({ signal });
    let sessionId, terminal = false, cancelled = false;
    const items = [], errors = [], emitted = new Set();
    let streamedCharacters = 0, deltaSequence = 0;
    try {
      let stream;
      if (typeof client.createSessionEvents === "function") {
        yield { type: "progress", message: text("에이전트 연결 중", "Connecting to the agent") };
        stream = client.createSessionEvents(prompt, language);
      } else {
        sessionId = await client.createSession(prompt, language);
        stream = client.events(sessionId);
        yield { type: "progress", message: text("조회 중", "Querying resources") };
      }
      try {
        for await (const event of stream) {
          if (event.type === "agent.session.created") {
            const id = event.session?.id;
            if (typeof id !== "string" || !id || id.length > 256) throw new BmaError("InvalidSessionId");
            sessionId = id;
            yield { type: "progress", message: text("조회 준비 중", "Preparing the query") };
          } else if (event.type === "agent.session.turn.output_text.delta" &&
              [undefined, null, "final"].includes(event.channel) && typeof event.delta === "string") {
            streamedCharacters += event.delta.length;
            if (streamedCharacters > 60_000) throw new BmaError("AnswerTooLarge");
            if (event.delta) yield { type: "answer_delta", delta: event.delta, sequence: ++deltaSequence };
          } else if (event.type === "agent.session.turn.item.done" && event.item) {
            if (items.length >= 500) throw new BmaError("ItemLimitReached");
            items.push(event.item);
            const parsed = publicItems([event.item], this.settings);
            errors.push(...parsed.evidence_errors);
            if (parsed.evidence_errors.some((e) => ["EvidenceAccountMismatch", "EvidenceRegionMismatch", "EvidenceModeMismatch"].includes(e))) {
              throw new BmaError("EvidenceScopeMismatch");
            }
            for (const result of parsed.evidence) {
              if (!emitted.has(result.item_id)) { emitted.add(result.item_id); yield { type: "tool_result", result }; }
              if (result.status === "account_mismatch") throw new BmaError("RuntimeAccountMismatch");
              if (result.api_calls.some((c) => c.api === "GetCallerIdentity" && c.success === false)) throw new BmaError("RuntimeIdentityVerificationFailed");
            }
            if (emitted.size >= 30) throw new BmaError("ToolCallLimitReached");
          } else if (END.has(event.type)) { terminal = true; break; }
          else if (FAILED.has(event.type)) { terminal = true; errors.push("BmaTurnFailed"); break; }
        }
        if (!terminal) errors.push("EventStreamEnded");
      } catch (error) { errors.push(error.code || "EventStreamDisconnected"); }
      if (!sessionId) throw new BmaError(errors[0] || "MissingSessionId");
      if (!terminal) {
        cancelled = true;
        try { await client.cancel(sessionId); } catch { errors.push("CancelRequestFailed"); }
      }
      if (signal?.aborted) return;
      yield { type: "progress", message: text("조회 결과 정리 중", "Preparing the results") };
      try {
        const durable = await client.listItems(sessionId);
        items.push(...durable.items);
        if (!durable.complete) errors.push("ItemsPartiallyRetrieved");
        if (durable.error) errors.push(durable.error);
      } catch (error) { errors.push(error.code || "ItemRetrievalFailed"); }
      const parsed = publicItems(items, this.settings);
      errors.push(...parsed.evidence_errors);
      for (const result of parsed.evidence) if (!emitted.has(result.item_id)) {
        emitted.add(result.item_id); yield { type: "tool_result", result };
      }
      const evidence = parsed.evidence;
      const resources = evidence.filter((r) => r.service !== "sts");
      let answer = parsed.answer;
      if (!resources.length) { answer = text("리소스 조회 결과를 받지 못했습니다.", "No resource query evidence was returned."); errors.push("NoResourceEvidence"); }
      if (evidence.some((r) => r.status === "account_mismatch")) { answer = text("실행 계정이 달라 조회를 차단했습니다.", "Query blocked because the execution account differs."); errors.push("RuntimeAccountMismatch"); }
      if (errors.includes("RuntimeIdentityVerificationFailed")) answer = text("STS 계정 확인에 실패하여 조회를 중단했습니다.", "Query stopped because STS account verification failed.");
      if (!answer) { answer = summarize(evidence, language); errors.push("NoFinalAssistantMessage"); }
      const partial = errors.length || evidence.some((r) => !["ok", "empty"].includes(r.status));
      yield { type: "result", answer: cleanMarkdownProse(answer), evidence, errors: [...new Set(errors)], bma_session_id: sessionId,
        status: !resources.length ? "failed" : partial ? "partial" : "complete",
        model: this.settings.model, agent_backend: "bma", model_processing_scope: "app_region" };
    } finally {
      if (sessionId && !terminal && !cancelled) await client.cancel(sessionId).catch(() => {});
    }
  }
}
