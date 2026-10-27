# ADR-003: Serve Both Web Functions through CloudFront with Lambda Web OAC

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Status
Accepted (deployed and verified 2026-10-27 UTC; record in [cloudfront-deployment.md](../cloudfront-deployment.md), plan in [2026-10-27-cloudfront-oac.md](../superpowers/plans/2026-10-27-cloudfront-oac.md))

## Context
Users of the Operations Desk and AI Document Studio are in Seoul, while both Lambda Web Functions, BMA and the
Runtimes must stay in `us-east-1` (Web Functions, BMA and Runtime V2 are used there, and model processing is pinned
to that region). Every page load crossed the Pacific, and both regional `*.lambda-web.us-east-1.on.aws` endpoints
were public, protected only by the shared application key. CloudFront can now use a Lambda Web Function as an
origin with Origin Access Control. The design had to keep Bearer authentication, SSE streaming, file uploads and
private downloads working, and must never cache an authenticated or model-produced response.

## Options Considered

### Option 1: Keep the public regional endpoints
- **Pros**: No new resources or deployment steps.
- **Cons**: Every TLS handshake and static file crosses to `us-east-1`; the origin stays reachable by anyone who has or guesses the key.

### Option 2: CloudFront in front of a still-public origin
- **Pros**: Edge TLS and static caching with a simple setup.
- **Cons**: The regional endpoint remains a bypass around the distribution, so its protections are optional.

### Option 3: One distribution per app with Lambda Web OAC and an `IamAuth` origin
- **Pros**: The origin accepts only SigV4 requests from its own distribution (exact `aws:SourceArn`); edge TLS and public static caching for Seoul (`PriceClass_All`); each app keeps an independent stack, URL and rollback.
- **Cons**: A staged rollout (prepare, policy, cutover) managed by `scripts/deploy_cloudfront.py`, because no native CloudFormation resource for the Web Function resource policy was found; code releases now need a cache invalidation.

## Decision
Adopt Option 3 for both apps. OAC uses origin type `lambda`, `sigv4` and `always-amz-auth`, which signs the
origin request without replacing the viewer's `Authorization` header, so the app key is still checked.
Only `/` (60-second edge TTL) and `/static/*` (up to 3,600 seconds) cache public content; every other path has
minimum/default/maximum TTL zero, the origin sends `no-store`, and dynamic compression is off for SSE.
The account's 20 custom cache-policy slots were all used and none forwarded `Authorization`, so each distribution
uses inline `ForwardedValues` and TTLs instead of new cache policies, without changing unrelated policies.
The viewer `Host` header is never forwarded.

## Consequences

### Positive
- Direct origin requests return `403`, even with a valid app key; the key still guards the CloudFront path.
- From one Seoul EC2 instance, cached HTML first byte fell from about 580-590 ms to about 11 ms and font downloads from 1.6-2.3 s to about 20 ms.
- BMA, Runtime, storage and document generation do not move; no model, Runtime or resource-query permission changed.

### Negative
- Static asset names are not content-hashed: invalidate both recorded distributions after each Web release.
- The resource policy lives outside CloudFormation; `prepare`/`cutover` keep backups and use revision-aware writes.
- The measurement covers one EC2 vantage and cache hits only, not cache misses, other networks or model time; a long active SSE generation was not re-run through CloudFront.

## References
- [cloudfront-deployment.md](../cloudfront-deployment.md) — deployed identifiers, cache scope, verification and Seoul measurements
- [runbooks/cloudfront-oac.md](../runbooks/cloudfront-oac.md) — prepare, cutover, verify, recovery and invalidation
- [architecture.md](../architecture.md#cloudfront-front-doors) — front-door design
- [Restricting access to a Lambda Web Function origin](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda-web.html)

---

<a id="korean"></a>

# 한국어

## 상태
채택(2026-10-27 UTC 배포·검증, 기록은 [cloudfront-deployment.md](../cloudfront-deployment.md), 계획은 [2026-10-27-cloudfront-oac.md](../superpowers/plans/2026-10-27-cloudfront-oac.md))

## 배경
운영 데스크와 AI Document Studio의 사용자는 서울에 있지만, 두 Lambda Web Function과 BMA, Runtime은
`us-east-1`에 있어야 합니다(Web Functions, BMA, Runtime V2를 그 리전에서 사용하고 모델 처리를 그 리전에 고정).
화면을 열 때마다 태평양을 건넜고, 두 리전 엔드포인트 `*.lambda-web.us-east-1.on.aws`는 공유 이용 키만으로 보호되는
공개 주소였습니다. 이제 CloudFront는 Origin Access Control로 Lambda Web Function을 오리진으로 사용할 수 있습니다.
설계는 Bearer 인증, SSE 스트리밍, 파일 업로드, 개인 다운로드를 유지해야 하고, 인증된 응답이나 모델 결과를
절대 캐시하지 않아야 했습니다.

## 검토한 옵션

### 옵션 1: 공개 리전 엔드포인트 유지
- **장점**: 새 리소스나 배포 단계가 없습니다.
- **단점**: 모든 TLS 연결과 정적 파일이 `us-east-1`까지 가고, 키를 가졌거나 추측한 누구나 오리진에 접근할 수 있습니다.

### 옵션 2: 공개 오리진 앞에 CloudFront만 추가
- **장점**: 간단한 구성으로 엣지 TLS와 정적 캐시를 얻습니다.
- **단점**: 리전 엔드포인트가 배포를 우회하는 경로로 남아, CloudFront의 보호가 선택 사항이 됩니다.

### 옵션 3: 앱마다 Lambda Web OAC를 연결한 배포 하나와 `IamAuth` 오리진
- **장점**: 오리진은 자기 배포(정확한 `aws:SourceArn`)의 SigV4 요청만 받습니다. 서울을 포함한 엣지(`PriceClass_All`)에서 TLS와 공개 정적 캐시를 제공하고, 앱마다 스택, 주소, 롤백이 독립적입니다.
- **단점**: Web Function 리소스 정책용 네이티브 CloudFormation 리소스를 찾지 못해 `scripts/deploy_cloudfront.py`가 단계별 적용(prepare, 정책, cutover)을 관리합니다. 코드 배포 뒤에는 캐시 무효화가 필요합니다.

## 결정
두 앱 모두 옵션 3을 채택합니다. OAC는 오리진 유형 `lambda`, `sigv4`, `always-amz-auth`를 사용하며,
사용자의 `Authorization` 헤더를 바꾸지 않고 오리진 요청에 서명하므로 앱 이용 키 검사가 그대로 유지됩니다.
공개 콘텐츠는 `/`(엣지 TTL 60초)와 `/static/*`(최대 3,600초)만 캐시합니다. 나머지 경로는 최소/기본/최대 TTL이
모두 0이고 오리진도 `no-store`를 보내며, SSE를 위해 동적 압축을 끕니다.
계정의 사용자 지정 캐시 정책 20개가 모두 사용 중이었고 `Authorization`을 전달하는 정책이 없었으므로,
관련 없는 정책을 바꾸지 않고 배포마다 인라인 `ForwardedValues`와 TTL을 사용합니다. 사용자 `Host` 헤더는 전달하지 않습니다.

## 영향

### 긍정적
- 오리진 직접 요청은 올바른 앱 이용 키가 있어도 `403`을 반환하며, CloudFront 경로는 계속 이용 키로 보호됩니다.
- 서울 EC2 한 대에서 측정한 캐시 HIT 기준 HTML 첫 응답은 약 580-590ms에서 약 11ms로, 폰트 수신은 1.6-2.3초에서 약 20ms로 줄었습니다.
- BMA, Runtime, 저장소, 문서 생성 위치는 바뀌지 않으며 모델, Runtime, 리소스 조회 권한도 변경하지 않았습니다.

### 부정적
- 정적 자산 이름에 내용 해시가 없으므로 Web 배포마다 기록된 두 배포의 캐시를 무효화해야 합니다.
- 리소스 정책이 CloudFormation 밖에 있어 `prepare`/`cutover`가 백업과 revision 기반 갱신을 담당합니다.
- 측정은 EC2 한 곳의 캐시 HIT만 다루며 캐시 MISS, 다른 회선, 모델 시간은 포함하지 않습니다. 긴 활성 SSE 생성을 CloudFront로 다시 실행하지는 않았습니다.

## 참고 자료
- [cloudfront-deployment.md](../cloudfront-deployment.md) — 배포 식별자, 캐시 범위, 검증, 서울 측정
- [runbooks/cloudfront-oac.md](../runbooks/cloudfront-oac.md) — prepare, cutover, verify, 복구, 무효화
- [architecture.md](../architecture.md#cloudfront-접속-경로) — 접속 경로 설계
- [Lambda Web Function 오리진 접근 제한](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda-web.html)
