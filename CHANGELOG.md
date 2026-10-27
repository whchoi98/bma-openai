# Changelog

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add the BMA agent path that answers natural-language questions with Mantle's `openai.gpt-6-luna` model through AgentCore Runtime V2.
- Add 24 read-only MCP tools that query `ap-northeast-2` control APIs only after STS confirms the expected account.
- Add 4 Skills for resource inventory, service health, security posture, and operations reports.
- Add SSE streaming of public answer text rendered with react-markdown 10.1.0 + remark-gfm 4.0.1, with query steps and tool records.
- Add Markdown, HTML, DOCX, and PPTX reports from saved results that show only the last 3 digits of the account ID.
- Add operations investigations with follow-up questions in the same BMA session, reconnection recovery, and a versioned procedure catalog.
- Add the optional `AGENT_BACKEND=converse` path that uses the `global.openai.gpt-6-luna` inference profile.
- Add CloudFormation bootstrap and application stacks for the Runtime, Web Function, investigation worker, IAM roles, and app S3 bucket.
- Add AI Document Studio, a separate demo that turns one XLSX/CSV/TXT/MD file or pasted notes into charts, diagrams, and editable PPTX/DOCX through BMA with `openai.gpt-6.1-sol`.
- Add a job-bound document MCP with 6 tools that aggregate source values in code and render PNG/SVG, PPTX/DOCX, and a sandboxed HTML preview in three styles.
- Add separate Studio stacks (`bma-office-build`, `bma-office-studio`) with their own Web Function, worker, document Runtime, roles, and 7-day data bucket, without AWS resource-query permissions.

### Changed

- Move the app, BMA, Runtime, and result storage from the deleted Oregon deployment to `us-east-1`.

[Unreleased]: https://github.com/whchoi98/bma-openai/commits/main

---

<a id="korean"></a>

# 한국어

이 프로젝트의 모든 주요 변경 사항은 이 파일에 기록됩니다.
이 문서는 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)를 기반으로 하며,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html)을 따릅니다.

## [Unreleased]

### Added

- AgentCore Runtime V2를 통해 Mantle의 `openai.gpt-6-luna` 모델로 자연어 질문에 답하는 BMA 에이전트 경로 추가
- STS로 기대 계정을 확인한 뒤에만 `ap-northeast-2` 제어 API를 조회하는 읽기 전용 MCP 도구 24개 추가
- 리소스 인벤토리, 서비스 상태, 보안 상태, 운영 보고서용 Skills 4개 추가
- 조회 단계와 도구 기록을 포함해 react-markdown 10.1.0 + remark-gfm 4.0.1로 렌더링하는 공개 답변 SSE 스트리밍 추가
- 계정 ID 마지막 3자리만 표시하는 저장 결과 기반 Markdown, HTML, DOCX, PPTX 보고서 추가
- 같은 BMA 세션의 후속 질문, 재접속 복구, 버전이 있는 절차 카탈로그를 갖춘 운영 조사 추가
- `global.openai.gpt-6-luna` 추론 프로파일을 사용하는 선택형 `AGENT_BACKEND=converse` 경로 추가
- Runtime, Web Function, 조사 worker, IAM 역할, 앱 S3 버킷용 CloudFormation bootstrap 스택과 애플리케이션 스택 추가
- 엑셀/CSV/TXT/MD 파일 하나나 붙여 넣은 메모로 BMA(`openai.gpt-6.1-sol`)를 통해 차트, 다이어그램, 편집 가능한 PPTX/DOCX를 만드는 별도 데모 AI Document Studio 추가
- 원본 값을 코드로 집계하고 PNG/SVG, PPTX/DOCX, sandbox HTML 미리보기를 세 가지 스타일로 만드는 작업 고정 문서 MCP 도구 6개 추가
- 자체 Web Function, worker, 문서 Runtime, 역할, 7일 보관 데이터 버킷을 갖추고 AWS 리소스 조회 권한이 없는 별도 Studio 스택(`bma-office-build`, `bma-office-studio`) 추가

### Changed

- 앱, BMA, Runtime, 결과 저장 위치를 삭제한 오레곤 배포에서 `us-east-1`로 이전

[Unreleased]: https://github.com/whchoi98/bma-openai/commits/main
