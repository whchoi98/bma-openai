from datetime import datetime, timedelta, timezone

from aws_inventory.engine import AwsInventory

from .bma import BmaClient, BmaError
from .evidence import public_items
from .reports import summarize

END_EVENTS = {"agent.session.turn.completed", "agent.session.completed"}
FAILURE_EVENTS = {
    "agent.session.turn.failed", "agent.session.turn.cancelled", "agent.session.failed",
    "agent.session.environment.failed", "error",
}


class SampleRunner:
    def __init__(self, settings):
        self.inventory = AwsInventory(settings.inventory)

    def _results(self, prompt):
        engine = self.inventory
        yield engine.invoke("get_account_context")
        text = prompt.lower()
        all_services = any(k in text for k in ["보고서", "report"]) and not any(
            k in text for k in ["ec2", "rds", "ecs", "lambda", "알람", "alarm"]
        )
        if "ec2" in text or all_services:
            instances = engine.invoke("list_ec2_instances")
            yield instances
            if any(k in text for k in ["점검", "실패", "health", "status check", "failed"]) or all_services:
                ids = instances["resource_ids"][:20]
                if ids:
                    yield engine.invoke("get_ec2_instance_health", {"instance_ids": ids})
        if "rds" in text or all_services:
            yield engine.invoke("list_rds_instances")
        if "ecs" in text or all_services:
            clusters = engine.invoke("list_ecs_clusters")
            yield clusters
            for cluster in clusters["resource_ids"][:2]:
                services = engine.invoke("list_ecs_services", {"cluster": cluster})
                yield services
                if services["resource_ids"]:
                    yield engine.invoke("get_ecs_service_health", {
                        "cluster": cluster, "services": services["resource_ids"][:10]
                    })
        if "lambda" in text or "람다" in text or all_services:
            functions = engine.invoke("list_lambda_functions")
            yield functions
            end = datetime.now(timezone.utc)
            for function in functions["resource_ids"][:5]:
                yield engine.invoke("get_resource_metrics", {
                    "service": "lambda", "resource_id": function,
                    "start_time": (end - timedelta(hours=1)).isoformat(), "end_time": end.isoformat(),
                })
        if "알람" in text or "alarm" in text or "cloudwatch" in text or all_services:
            yield engine.invoke("list_cloudwatch_alarms", {"state": "ALARM"})

    def stream(self, prompt, language="ko"):
        evidence = []
        for result in self._results(prompt):
            evidence.append(result)
            yield {"type": "tool_result", "result": result}
        answer = "샘플 데이터로 실행한 결과입니다. 실제 AWS 및 BMA 모델은 호출하지 않았습니다.\n\n"
        if len(evidence) == 1:
            answer += "이 질문은 샘플 분기에서 지원하지 않습니다. 화면의 지원 예제 질문을 선택하세요."
        else:
            answer += summarize(evidence)
        if language == "en":
            answer = "Sample data. No AWS APIs or models were called.\n\n" + "\n".join(
                f"- {r['tool']}: {r['status']}, {r['resource_count']} resources returned."
                for r in evidence if r["service"] != "sts"
            ) + "\n\nMissing metrics are not zero. Application health was not assessed."
        yield {"type": "result", "answer": answer, "evidence": evidence, "errors": [], "status": "complete"}


class LiveRunner:
    def __init__(self, settings, aws_session, client_factory=BmaClient):
        self.settings = settings
        self.aws_session = aws_session
        self.client_factory = client_factory

    def stream(self, prompt, language="ko"):
        client = self.client_factory(self.settings, aws_session=self.aws_session)
        session_id, terminal, cancelled = None, False, False
        items, errors, emitted = [], [], set()
        try:
            session_id = client.create_session(prompt, language="en") if language == "en" else client.create_session(prompt)
            yield {"type": "progress", "message": "BMA 세션에서 조회 절차를 실행하고 있습니다."}
            try:
                for event in client.events(session_id):
                    kind = event.get("type")
                    if kind == "heartbeat":
                        yield {"type": "heartbeat"}
                    elif kind == "agent.session.turn.item.done" and isinstance(event.get("item"), dict):
                        item = event["item"]
                        items.append(item)
                        parsed = public_items([item], self.settings.inventory)
                        errors.extend(parsed["evidence_errors"])
                        for evidence in parsed["evidence"]:
                            identity = evidence.get("item_id")
                            if identity not in emitted:
                                emitted.add(identity)
                                yield {"type": "tool_result", "result": evidence}
                            if evidence["status"] == "account_mismatch":
                                raise BmaError("RuntimeAccountMismatch")
                            if any(c.get("api") == "GetCallerIdentity" and c.get("success") is False
                                   for c in evidence.get("api_calls", [])):
                                raise BmaError("RuntimeIdentityVerificationFailed")
                        if len(emitted) >= 30:
                            raise BmaError("ToolCallLimitReached")
                    elif kind in END_EVENTS:
                        terminal = True
                        break
                    elif kind in FAILURE_EVENTS:
                        terminal = True
                        errors.append("BmaTurnFailed")
                        break
                if not terminal:
                    errors.append("EventStreamEnded")
            except BmaError as exc:
                errors.append(exc.code)
            if not terminal:
                cancelled = True
                try:
                    client.cancel(session_id)
                except BmaError:
                    errors.append("CancelRequestFailed")
            try:
                durable, complete = client.list_items(session_id)
                items.extend(durable)
                if not complete:
                    errors.append("ItemsPartiallyRetrieved")
            except BmaError as exc:
                errors.append(exc.code)
            parsed = public_items(items, self.settings.inventory)
            errors.extend(parsed["evidence_errors"])
            for evidence in parsed["evidence"]:
                identity = evidence.get("item_id")
                if identity not in emitted:
                    emitted.add(identity)
                    yield {"type": "tool_result", "result": evidence}
            evidence = parsed["evidence"]
            answer = parsed["answer"]
            resource_queries = [r for r in evidence if r["service"] != "sts"]
            if not resource_queries:
                answer = "실제 리소스 조회 근거가 없습니다. 지원 서비스와 실행 오류를 확인하세요."
                errors.append("NoResourceEvidence")
            if any(r["status"] == "account_mismatch" for r in evidence):
                answer = "Runtime 실행 계정이 EXPECTED_ACCOUNT_ID와 달라 조회를 차단했습니다."
                errors.append("RuntimeAccountMismatch")
            if "RuntimeIdentityVerificationFailed" in errors:
                answer = "Runtime의 STS 계정 검증에 실패하여 조회를 중단했습니다."
            if not answer:
                answer = summarize(evidence)
                errors.append("NoFinalAssistantMessage")
            partial = errors or any(r["status"] not in {"ok", "empty"} for r in evidence)
            status = "partial" if partial else "complete"
            if not resource_queries:
                status = "failed"
            yield {"type": "result", "answer": answer, "evidence": evidence,
                   "errors": list(dict.fromkeys(errors)), "status": status}
        finally:
            if session_id and not terminal and not cancelled:
                try:
                    client.cancel(session_id)
                except BmaError:
                    pass
            client.close()
