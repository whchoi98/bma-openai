# BMA 운영 조사

사용자의 “새로운 기능 추가” 요청을 앞서 추천한 세 기능의 구현으로 해석한다.
별도 범위 응답이 없으면 조사 이어가기, 재접속 복구, 운영 절차 카탈로그를 구현한다.
변경 전후 비교 보고서는 이번 범위에 포함하지 않는다.

## 사용자 경험

- 기존 단일 질문 화면은 유지하고 “운영 조사” 모드를 추가한다.
- 운영 절차를 선택해 조사를 시작하고 같은 조사에 후속 질문을 보낸다.
- 선택한 절차의 이름, 버전, 단계와 실제 실행 상태를 표시한다.
- 조사 목록에서 진행 중이거나 끝난 조사를 다시 연다. 새로고침 후에는 접속 키를
  다시 입력하며 마지막으로 열었던 조사 ID만 브라우저에 보관한다.
- 진행 답변과 도구 결과를 SSE로 표시한다. 재접속 시 저장된 스냅샷을 먼저 표시한다.
- 조사별 질문과 결과를 구분하고 기존 Markdown/HTML/DOCX/PPTX 내보내기를 사용한다.
- “조사 중단”은 BMA turn만 취소한다. AWS 리소스의 중지/변경 도구는 추가하지 않는다.

## 고정된 경계

- APP_REGION=us-east-1, TARGET_REGION=ap-northeast-2.
- AGENT_BACKEND=bma, BMA_MODEL=openai.gpt-6-luna.
- Runtime은 기존 24개 읽기 도구와 Skills 4개를 유지한다. upstream lifecycle은 수정하지 않는다.
- 계정은 Web/worker의 STS와 도구의 STS로 확인한다. 사용자 입력 계정/리전은 받지 않는다.
- 계정 ID 마스킹, NanumSquare OTF Bold, 다크 모드, 한국어/영어, 장식 기호 없는 문체를 유지한다.
- 기존 배포 갱신과 소규모 실조회 검증은 이전 사용자 승인 범위에서 진행한다.

## 실행 구조

Web Function은 입력을 검증하고 S3에 조사를 예약한 뒤 지정 Lambda Event Function을
비동기로 호출한다. 별도 worker는 BMA 세션을 만들거나 재사용하고 한 turn을 실행한다.
브라우저 연결이 없어도 worker는 제한 시간 안에서 계속 실행한다.
worker는 공개 답변과 정규화된 도구 결과만 S3 스냅샷에 저장한다.
Web Function의 SSE는 저장된 스냅샷을 최대 초당 한 번 읽어 바뀐 답변과 결과를 전달한다.
모델 토큰마다 S3를 쓰지 않으며 중간 저장도 초당 최대 한 번이다. 기존 단일 질문 경로는
BMA의 직접 스트리밍을 그대로 사용한다.

worker는 300초 turn 예산과 취소 여유 시간을 가지며 함수 timeout은 360초다.
worker 동시 실행은 2개다. 비동기 중복 전달은 S3 조건부 쓰기와 worker lease로 차단한다.
새 비용 항목은 Lambda Event Function 실행과 S3의 제한된 스냅샷 읽기/쓰기다.

## 데이터와 동시성

S3 prefix는 `investigations/ACCOUNT/ap-northeast-2/`로 고정한다.

- `sessions/UUID.json`: 조사 메타데이터, 선택한 절차 snapshot, BMA session ID,
  active_run_id, turn 목록. 최대 128 KiB, 10 turns, 후속 질문 유효 기간 6시간.
- `turns/UUID.json`: 입력, 단계, worker lease, BMA turn ID, 공개 진행 스냅샷,
  terminal result. 최대 4 MB. 원문 BMA 이벤트/추론은 저장하지 않는다.
- `index/REVERSE_TIMESTAMP-UUID.json`: 목록용 작은 메타데이터.
- 최종 보고서는 기존 `runs/UUID.json`, `history/ACCOUNT/ap-northeast-2/`에 저장한다.
- 데이터는 7일 후 만료하며 비현재 버전은 1일 후 만료한다.

공통 metadata는 `id`, `account_id`, `app_region`, `target_region`, `mode`, `created_at`이다.
클라이언트의 `request_id`는 UUID이며 최초 조사 ID와 첫 run ID로 사용한다. 동일 ID와
동일 입력은 기존 예약을 반환하고 다른 입력은 409다. 후속 질문 ID도 UUID다.
조사의 `active_run_id`는 조건부 교체로 한 번에 하나의 turn만 허용한다.

S3의 If-None-Match와 If-Match를 사용한다. transport 오류를 동시성 충돌로 숨기지 않는다.
외부 BMA 요청 직전에 `creating_session` 또는 `submitting`을 영속화한다.
생성/입력 POST는 자동 재시도하지 않는다. 응답이 불명확하면 고유 조사/turn 표식으로
세션/사용자 item을 조회하고 기존 실행을 찾는다. 확인되지 않으면 `uncertain`으로 표시하고
중복 실행하지 않는다.

lease는 worker_token과 lease_until로 관리하고 heartbeat로 갱신한다.
중복 worker는 유효 lease가 있으면 종료한다. 이전 단계가 이미 submitting/running인 경우
재시작은 조회/복구만 하며 같은 입력을 다시 보내지 않는다.
worker가 멈춘 조사는 GET/재접속에서 lease 만료를 확인한 뒤 같은 run을 다시 dispatch할 수 있다.

## HTTP 계약

기존 Bearer 접속 키와 계정 검증을 모든 새 API에 적용한다.

- GET `/api/procedures`: `{procedures:[{id,version,sha256,name:{ko,en},description:{ko,en},
  steps:[{id,label:{ko,en},tools:[...]}]}], enabled:true}`.
- POST `/api/investigations`: `{request_id,procedure_id,prompt,language}`.
  202 `{investigation,run}`. 요청 ID가 조사 ID와 첫 run ID가 된다.
- GET `/api/investigations?limit=10&cursor=...`: `{investigations,next_cursor,complete}`.
- GET `/api/investigations/:id`: `{investigation,run}`. run은 현재/마지막 turn snapshot.
- POST `/api/investigations/:id/turns`: `{request_id,prompt,language}`. 202 `{investigation,run}`.
- GET `/api/investigations/:id/turns/:run_id/events`: SSE.
- POST `/api/investigations/:id/turns/:run_id/cancel`: 빈 JSON, 202.

공개 investigation에는 BMA ID, lease, 내부 표식, 자격증명을 포함하지 않는다.
공개 필드는 `id,title,created_at,updated_at,status,procedure,turns,active_run_id,expires_at`.
turn 목록 항목은 `id,prompt,language,status,created_at`이며 최대 10개다.
공개 run에는 `id,investigation_id,status,phase,prompt,language,created_at,updated_at,
answer,evidence,errors,procedure_steps,result`를 제공한다.
status는 `queued,running,complete,partial,failed,cancelled,uncertain` 중 하나다.

SSE 이벤트:

- `{type:"snapshot",investigation,run}`: 시작 시 또는 전체 진행 갱신.
- `{type:"complete",...기존 보고서 record}`: 최종 결과. 기존 UI 렌더러를 재사용한다.
- `{type:"heartbeat"}`: 변화가 없을 때.
- `{type:"error",code}`: 인증/저장/조회 오류. 실행 완료로 위장하지 않는다.

UI는 snapshot의 answer를 교체 렌더링하고 evidence 전체를 교체해 재접속 중복을 방지한다.
snapshot은 reasoning을 포함하지 않는다. 기존 보고서 버튼은 최종 result에만 활성화한다.
HTTP 목록은 계정 번호를 노출하지 않는 표시용 필드만 반환한다.

## BMA turn 구분

한 조사에 하나의 BMA 세션을 연결한다. agent 지침에는 승인된 절차의 고정 snapshot과
고유 조사 표식을 넣는다. 사용자 입력에는 고유 turn 표식과 선택 언어를 서버가 추가한다.
GET items는 원본 ID를 커서로 페이지네이션하고 500 items 상한을 적용한다.
turn_id 또는 현재 입력 item의 위치로 이번 turn을 구분한다. 이전 turn의 답변/도구를
이번 새 관측으로 합치지 않는다. 구분을 입증할 수 없으면 오류로 표시한다.

후속 질문이 새 도구를 호출하지 않고 이전 근거를 요약한 경우 해당 근거의 원본 시각을
보존하고 `evidence_reused`, `source_run_ids`를 기록한다. 답변 앞에 근거 재사용 안내를
서버가 추가해 모든 보고서 형식에도 남긴다. 새 관측과 이전 문맥이 섞인 경우
현재 evidence와 source_run_ids를 구분한다.

계정 불일치, STS 실패, 금지된 근거, 과다 도구 호출은 취소하고 실패로 처리한다.
지원하지 않는 계정/리전/임의 도구/경로 입력은 거부한다. 권한 제어는 IAM과 코드에 둔다.

## 절차와 단계

기존 네 Skills에 대응하는 `inventory`, `service-health`, `security-review`,
`operations-report`를 제공한다. version=1.0.0이며 관련 Skill sha256을 포함한
정규화된 snapshot의 hash를 사용한다. 선택한 절차는 조사 중 바꾸지 않는다.
단계는 account, discovery, checks, report이며 관련 실제 도구 결과와 완료 여부로
`pending,running,complete,partial,failed,not_requested`를 계산한다.
단계가 완료됐다는 뜻은 애플리케이션 정상 판정이 아니다.

## 검증

로컬: 동시 turn 충돌, 중복 request/worker, 불명확한 POST, session/turn 범위 격리,
오류/빈 결과/부분 결과, 재사용 근거 시각, snapshot 재접속, 계정/리전 불일치,
raw reasoning 제거, 저장 실패, 취소/timeout, 허용 IAM, 기존 351개 회귀 검사.
샘플 모드는 AWS/모델을 호출하지 않고 같은 조사 UI와 복구 인터페이스를 제공한다.
실제: 새 조사에서 제한된 EC2/RDS 또는 ALARM 조회, 같은 BMA 세션 후속 질문,
스트림 중단 후 다른 Web 인스턴스/새 브라우저 재접속, 과거 근거 원본 시각,
두 언어/테마/문서 내보내기. 실조회는 소수 리소스와 짧은 기간으로 유지한다.
