# 서울 리전 조회 서비스 구현 계획

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

**목표:** 공식 BMA + Web Functions + Runtime V2 구성에 읽기 전용 AWS MCP와
Skills, 근거 중심 화면·보고서, 재현 가능한 검증을 추가한다.

**설계:** [design.md](design.md).
**기술:** Python 3.12, boto3/Stubber, MCP STDIO, Node.js 24 Web Function, 로컬 FastAPI 참조 구현, AWS SigV4,
CloudFormation, HTML/CSS/JavaScript.

1. `tests/test_inventory.py`에 잘못된 계정·리전, 빈 결과, 권한 거부,
   페이지 경계·실패, 지표 없음 및 민감 필드 제거 테스트를 작성한다.
   실패를 확인하고 `aws_inventory/config.py`, `engine.py`, `tools.py`를 구현한다.
2. `tests/test_mcp.py`에서 initialize → tools/list → tools/call을 실제 STDIO로
   검증한다. 도구 허용 목록과 잘못된 인자 거부를 확인하고 `mcp_server.py`를 구현한다.
3. `tests/test_bma.py`에서 공식 REST 스키마·SigV4 리전·MCP 설정·출력 필터를
   검증한다. `webapp/bma.py`, 상태 저장과 HTTP API를 구현한다.
4. `tests/test_reports.py`에서 부분 실패·결측·KST 시각·HTML escaping을 검증한다.
   3개 Skills, 보고서 생성 및 한국어 대시보드를 구현한다.
5. Runtime Dockerfile, Web Function 패키지와 역할별 IAM 정책 및 배포 준비 명령을
   작성한다. 공식 SDK 모델로 IaC/API 입력을 검사한다.
6. 전체 로컬 테스트와 제한된 라이브 조회를 실행한다. API/IAM 표, 한국어 시나리오,
   데이터 흐름, 네트워크·과금 한도·미지원 범위와 실제 검증 결과를 문서화한다.

위 구현과 사용자가 요청한 AWS 배포·실제 BMA 종단 간 검증을 완료했다.

후속 변경도 배포·검증했다.

7. react-markdown v10 + remark-gfm 답변 컴포넌트, 로컬 나눔스퀘어 OTF Bold와 라이선스를 포함한다.
8. 요청 모델의 API 지원 범위를 실제 호출로 확인하고, `global.openai.gpt-6-luna`용
   ConverseStreamCommand → SSE 경로를 추가한다. 기존 BMA 경로를 선택 가능하게 유지한다.
9. Runtime HTTP→STDIO MCP bridge와 지정 세션 역할 AssumeRole을 추가하되,
   AWS 조회 권한은 RuntimeRole에만 둔다. 글로벌 모델의 데이터 흐름을 표시한다.
10. 134개 회귀 검사, 현재 모델의 5개 실조회 시나리오, 실제 브라우저의 완료 전 렌더링,
    BMA→새 Runtime 호환성을 검증한다. 최종 근거는 [검증 결과](verification.md)에 기록한다.
