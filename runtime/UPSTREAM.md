# BMA lifecycle 서버 출처

`lifecycle/server.py`는 공식 `@aws/agentcore` npm 패키지 **1.0.0**의
`dist/assets/templates/bedrock-managed-agents/lifecycle/server.py`를 변경 없이 포함했다.

- 패키지: https://registry.npmjs.org/@aws/agentcore/-/agentcore-1.0.0.tgz
- 공식 절차: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-bma.html
- 원본 SHA-256: `d128afec9bd1b5025643fba21b1ed000cf212a34267250d1151d323ade400d7f`
- 확인일: 2026-10-26
- 원본 Apache 2.0 라이선스: [LICENSE-AGENTCORE](LICENSE-AGENTCORE). 컨테이너에도 함께 포함한다.

원본 HTTP `/invocations`는 BMA lifecycle 프로토콜이다.
이 서버가 `codex exec-server`를 시작하고, BMA가 로컬 STDIO MCP를 연결한다.
`ProtocolConfiguration: HTTP`, `PlatformVersion: V2`를 사용한다.

현재 이미지의 진입점은 프로젝트의 `mcp_bridge.py`다. 원본 lifecycle을 상속하고
`application/vnd.seoul-aws.mcp+json` 요청에만 제한된 `tools/list`·`tools/call` bridge를 제공한다.
이는 BMA의 표준 MCP 연결 방식을 변경하거나 원본 파일을 수정한 것이 아니다.
Converse 경로가 IAM으로 보호된 InvokeAgentRuntime을 사용해 이 bridge를 호출하며,
bridge는 실제 MCP ClientSession과 STDIO 자식 프로세스를 사용한다.
요청 64 KiB, 실행 90초, 동시 4개로 제한하고 다른 입력은 거부한다.

컨테이너에는 Linux ARM64 Codex CLI 0.164.0 바이너리를 별도로 준비한다.
`scripts/prepare_runtime.py`가 버전·ELF 아키텍처·SHA-256을 확인한 후 복사한다.
실제 바이너리와 build manifest는 `.gitignore`로 제외한다.

런타임은 이미지 안의 읽기 전용 Skills를 사용한다. S3 Files, VPC, NAT Gateway,
리전 간 Peering을 생성하지 않는다. BMA 경로는 질문마다 새 BMA 세션을 사용하고,
Converse 경로는 질문마다 새 Runtime 세션을 사용한다.
최종 앱 결과는 Web Function 역할로 us-east-1 S3에 저장한다.

추가 ADOT exporter는 비활성화한다. 기본 Runtime 로그와 API 결과에 포함된 실행 기록을
사용하며 내부 추론을 웹으로 전달하지 않는다.
