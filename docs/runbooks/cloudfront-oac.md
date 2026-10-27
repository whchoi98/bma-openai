# Runbook: CloudFront and OAC for Both Web Functions

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

Put a separate CloudFront distribution in front of the Operations Desk and AI Document Studio, and protect the
existing regional endpoints with OAC. This document describes the configuration and the operating procedure.
Confirm completion from the actual results in `artifacts/cloudfront/verification.json`; the 2026-10-27 deployment
and its verification are recorded in [cloudfront-deployment.md](../cloudfront-deployment.md).

## Scope

| App | CloudFormation stack | Web Function endpoint | Deployment record |
| --- | --- | --- | --- |
| Operations Desk | `bma-seoul-inventory` | `demo` | `artifacts/aws-deployment.json` |
| Document Studio | `bma-office-studio` | `studio` | `artifacts/studio/deployment.json` |

`WebUrl` is the CloudFront viewer URL and `OriginWebUrl` is the protected regional URL.
`DistributionId` and `OriginAccessControlId` are also stack outputs.
After the OAC cutover, users must open `WebUrl`. The existing access key stays the same.

`PriceClass_All` includes Seoul edge locations. CloudFront handles TLS near the user and caches static files, but
BMA and the Runtimes still run in `us-east-1`. Neither the information read from Seoul resources nor model
processing of uploaded documents moves to Seoul.

## Authentication and Cache

OAC settings for the regional `HomeRegion` origin:

- Origin type: `lambda`
- Signing protocol: `sigv4`
- Signing behavior: `always-amz-auth`
- Final endpoint auth: `IamAuth`

The CloudFront signature and the app's Bearer access key are separate checks. `always-amz-auth` does not overwrite
the viewer's `Authorization`. The resource policy allows the CloudFront service principal only
`lambda:InvokeWebFunctionEndpoint` on the designated endpoint, with `aws:SourceArn` set to that app's exact
CloudFront distribution ARN.

No native CloudFormation resource for the Web Function resource policy was found in the reviewed schema, so
`scripts/deploy_cloudfront.py` manages it separately through `lambda-web.put_resource_policy`. The policy is attached
to the function ARN and its Resource is limited to the endpoint ARN. The raw response of any existing policy is
backed up first, and the script stops if it finds an unexpected policy statement.

| Path | CloudFront TTL: min / default / max | Origin Cache-Control |
| --- | --- | --- |
| `/` | `0 / 0 / 3600` | `public, max-age=0, s-maxage=60, must-revalidate` |
| `/static/*` | `0 / 0 / 3600` | `public, max-age=300, s-maxage=3600, must-revalidate` |
| Other paths | `0 / 0 / 0` | `no-store` |

When a static request carries Authorization or a Cookie, the origin also returns `no-store`. Static responses include
`Vary: Authorization, Cookie`. Uploads, APIs, SSE, private document downloads, HTML previews, health checks and error
responses are not cached.

All 20 custom cache-policy slots in the account were in use, and no existing policy forwarded Authorization as
required. To avoid changing other services' policies, the distributions use CloudFront's inline `ForwardedValues` and
TTLs instead of new CachePolicy resources.

Every path forwards Authorization, cookies and query strings. Dynamic paths also forward Content-Type, X-File-Name,
Last-Event-ID, Origin and Accept. The viewer Host is not in the forwarding list, so CloudFront uses the origin
hostname. The inline configuration is not combined with a separate `OriginRequestPolicyId`.

CloudFront compression is off for dynamic responses and the origin read timeout is 60 seconds. The apps send SSE
heartbeats every 10 or 15 seconds. Keep this timeout separate from the total BMA job time.

## Preflight

Change only the two apps approved in the current session. Stop if the account in either deployment record differs
from `STS GetCallerIdentity`. The BMA model, Runtimes, query permissions and data buckets are out of scope.
This work does not require rebuilding a Runtime image.

```bash
.venv/bin/python -m pytest tests/test_cloudfront.py tests/test_iam.py tests/test_investigation_iam.py tests/test_region_migration.py
node --test web/tests/cache-control.test.js studio/tests/cache-control.test.js
.venv/bin/cfn-lint infra/template.yaml studio/infra/template.yaml
.venv/bin/python scripts/build_web.py
.venv/bin/python studio/scripts/build_web.py
```

Resolve errors and account/region mismatches before continuing. Record tool-schema warnings for the new service
features separately from the results of real AWS API checks.

## 1. Prepare

```bash
.venv/bin/python scripts/deploy_cloudfront.py prepare --app both
```

For each app, the following records are kept in `artifacts/cloudfront/desk/` and `artifacts/cloudfront/studio/`.

- `before-deployment.json`: the original deployment record
- `before-template.txt`: the CloudFormation template before the change
- `before-policy.json`: the existing resource policy response, or `null` when there was none
- `pending-artifact.json`: the S3 key and version of the code ZIP
- `prepare-changes.json`: the reviewed Change Set

`prepare` uploads the code ZIP and deploys CloudFront and OAC, but keeps the current endpoint auth type. Changes are
limited to the Web code/endpoint, the worker that uses the same code ZIP, and the CloudFront resources; the script stops
on any unexpected replacement or permission change. An endpoint that is already `IamAuth` is never switched back to
`ApplicationManaged`.

## 2. Cutover

```bash
.venv/bin/python scripts/deploy_cloudfront.py cutover --app both
```

The script checks that CloudFront is `Deployed` and that the origin is that app's endpoint. It applies the resource
policy restricted to the exact distribution ARN, reads it back and compares it. When a policy already exists, it uses
the current `revisionId` so other changes are not overwritten.

After confirming that the existing access key works on the new CloudFront URL, it switches only
`WebEndpointAuthType=IamAuth` through a Change Set. It then checks that an authenticated API request through
CloudFront returns `200`, that the direct origin returns `403`, and that the Runtime version is unchanged.

To recover or retry a single app, use `--app desk` or `--app studio`.
The full deployment mapping is stored in `artifacts/cloudfront/deployment.json`.

## 3. Verify

```bash
.venv/bin/python scripts/deploy_cloudfront.py inspect --app both
.venv/bin/python scripts/verify_cloudfront.py
```

After confirming the STS account, the verifier checks:

- The actual CloudFront/OAC configuration and edge response headers of both apps
- Direct origin access denied for both anonymous requests and requests with a valid access key
- Through CloudFront, a valid key allowed and a missing or wrong key rejected
- Cache hits on repeated JS and font requests; cache misses and `no-store` on APIs
- SSE, file downloads and the query-string HTML preview of an existing completed job
- A small Document Studio CSV upload with a UTF-8 file name and matching stored bytes

No new model generation request is sent. The uploaded check file follows the normal 7-day Studio retention.
The SSE check reads an existing completed result, so it does not replace a streaming test of a long active job or a
Seoul user latency measurement. The execution location and verification scope are recorded in the results.
`scripts/verify_cloudfront_browser.py` repeats the sign-in, model display, account masking, language, dark mode and
mobile checks in Chromium through the CloudFront URLs.

## Failure and Recovery

A CloudFormation failure in `prepare` is handled with rollback enabled. Fix the cause and rerun `prepare` for that
app. Retries do not overwrite the `before-*` backups.

If an HTTP follow-up check fails after `cutover` completes, the endpoint stays `IamAuth`. The script never reopens the
origin automatically. Check distribution propagation, the exact origin domain, the OAC signing behavior, the
distribution ARN and endpoint ARN in the resource policy, and Authorization forwarding, then rerun `cutover` for
that app.

If the previous policy text must be restored, first compare the policy in `before-policy.json` with the current
policy, then update it conditionally with the current `revisionId`. Never reuse an old revision ID. Do not delete a
live OAC policy or switch the auth type to public just because the backup is `null`.

## Later Code Releases and Cache Invalidation

Asset URLs do not include a content hash. After a new code release and origin check, invalidate the cache of both
distributions. The following code reads the actual IDs from the deployment records and checks the account.

```bash
.venv/bin/python - <<'PY'
import json
import time
from pathlib import Path
import boto3

root = Path.cwd()
mapping = json.loads((root / "artifacts/cloudfront/deployment.json").read_text())
session = boto3.Session(region_name="us-east-1")
account = session.client("sts").get_caller_identity()["Account"]
cloudfront = session.client("cloudfront")
for name, app in mapping["apps"].items():
    manifest = json.loads((root / app["deployment_manifest"]).read_text())
    assert manifest["outputs"]["ExpectedAccountId"] == account, "AccountMismatch"
    result = cloudfront.create_invalidation(
        DistributionId=app["distribution_id"],
        InvalidationBatch={
            "CallerReference": f"release-{name}-{time.time_ns()}",
            "Paths": {"Quantity": 1, "Items": ["/*"]},
        },
    )
    print(name, result["Invalidation"]["Id"], result["Invalidation"]["Status"])
PY
```

A CloudFront invalidation does not clear files already stored in browsers. The browser TTL for static assets is at
most 300 seconds, so reload or use a new browser context to check immediately. CloudFront requests, data transfer
and invalidations beyond the free allowance can incur charges. The command above invalidates one wildcard path per app.

## Official References

- AWS announcement: `https://aws.amazon.com/ko/about-aws/whats-new/2026/10/cloudfront-lambda-web-functions-origin/`
- Lambda Web Function OAC: `https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda-web.html`
- Inline forwarding settings: `https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cloudfront-distribution-forwardedvalues.html`

---

<a id="korean"></a>

# 한국어

운영 데스크와 문서 스튜디오 앞에 각각 CloudFront를 두고, 기존 리전 엔드포인트는 OAC로 보호합니다.
이 문서는 구성과 운영 절차를 설명합니다. 배포 완료 여부는
`artifacts/cloudfront/verification.json`의 실제 결과로 확인하며, 2026-10-27 배포와 검증 결과는
[cloudfront-deployment.md](../cloudfront-deployment.md)에 기록했습니다.

## 범위

| 앱 | CloudFormation 스택 | Web Function 엔드포인트 | 배포 기록 |
| --- | --- | --- | --- |
| 운영 데스크 | `bma-seoul-inventory` | `demo` | `artifacts/aws-deployment.json` |
| 문서 스튜디오 | `bma-office-studio` | `studio` | `artifacts/studio/deployment.json` |

`WebUrl`은 CloudFront 사용자 주소, `OriginWebUrl`은 보호된 리전 주소입니다.
`DistributionId`와 `OriginAccessControlId`도 스택 출력에 포함됩니다.
OAC 전환 뒤 사용자는 `WebUrl`로 접속해야 합니다. 기존 이용 키는 유지합니다.

`PriceClass_All`은 서울 엣지 위치를 포함합니다. CloudFront가 사용자와 가까운 곳에서 TLS를
처리하고 정적 파일을 캐시하지만, BMA와 Runtime의 실행 리전은 계속 `us-east-1`입니다.
서울 리소스를 조회한 정보와 사용자가 올린 문서의 모델 처리가 서울로 옮겨가는 것은 아닙니다.

## 인증과 캐시

리전 `HomeRegion` 오리진의 OAC 설정은 다음과 같습니다.

- 오리진 유형: `lambda`
- 서명 프로토콜: `sigv4`
- 서명 동작: `always-amz-auth`
- 최종 엔드포인트 인증: `IamAuth`

CloudFront 서명과 앱의 Bearer 이용 키는 별도 검증입니다. `always-amz-auth`는 사용자
`Authorization`을 덮어쓰지 않습니다. 리소스 정책은 CloudFront 서비스 주체에 지정
엔드포인트의 `lambda:InvokeWebFunctionEndpoint`만 허용하며, 조건의 `aws:SourceArn`은
해당 앱의 정확한 CloudFront 배포 ARN입니다.

확인한 CloudFormation 스키마에서 Web Function 리소스 정책을 위한 네이티브 리소스를
찾지 못했으므로, `scripts/deploy_cloudfront.py`가 `lambda-web.put_resource_policy`로 별도
관리합니다. 함수 ARN에 정책을 연결하고, 정책의 Resource는 엔드포인트 ARN으로 제한합니다.
기존 정책의 원문 응답은 먼저 백업하며 예상하지 않은 다른 정책 문장이 있으면 중단합니다.

| 경로 | CloudFront TTL: 최소 / 기본 / 최대 | 오리진 Cache-Control |
| --- | --- | --- |
| `/` | `0 / 0 / 3600` | `public, max-age=0, s-maxage=60, must-revalidate` |
| `/static/*` | `0 / 0 / 3600` | `public, max-age=300, s-maxage=3600, must-revalidate` |
| 나머지 경로 | `0 / 0 / 0` | `no-store` |

정적 요청에 Authorization이나 Cookie가 있으면 오리진도 `no-store`를 반환합니다.
정적 응답에는 `Vary: Authorization, Cookie`가 있습니다. 업로드, API, SSE, 개인 문서
다운로드, HTML 미리보기, 상태 확인, 오류 응답은 캐시하지 않습니다.

계정의 사용자 지정 캐시 정책 한도 20개가 모두 사용 중이었으며, 기존 정책 중 필요한
Authorization 전달 정책이 없었습니다. 다른 서비스의 정책을 바꾸지 않기 위해 새
CachePolicy 리소스 대신 CloudFront의 인라인 `ForwardedValues`와 TTL을 사용합니다.

모든 경로에서 Authorization, 쿠키, 쿼리 문자열을 전달합니다. 동적 경로는 Content-Type,
X-File-Name, Last-Event-ID, Origin, Accept도 전달합니다. 사용자 Host는 전달 목록에 넣지
않아 CloudFront가 오리진 호스트 이름을 사용하도록 합니다. 인라인 설정에는 별도의
`OriginRequestPolicyId`를 함께 지정하지 않습니다.

동적 응답의 CloudFront 압축은 끄고 오리진 읽기 제한을 60초로 둡니다. 앱의 SSE heartbeat는
10초 또는 15초 간격입니다. 이 제한은 BMA 작업 전체 시간과 구분해야 합니다.

## 사전 확인

현재 세션에서 승인된 두 앱만 변경합니다. 두 배포 기록의 계정과 `STS GetCallerIdentity`가
다르면 중단합니다. BMA 모델, Runtime, 조회 권한과 데이터 버킷은 변경 대상이 아닙니다.
이 작업에 Runtime 이미지 재빌드는 필요하지 않습니다.

```bash
.venv/bin/python -m pytest tests/test_cloudfront.py tests/test_iam.py tests/test_investigation_iam.py tests/test_region_migration.py
node --test web/tests/cache-control.test.js studio/tests/cache-control.test.js
.venv/bin/cfn-lint infra/template.yaml studio/infra/template.yaml
.venv/bin/python scripts/build_web.py
.venv/bin/python studio/scripts/build_web.py
```

오류와 계정/리전 불일치는 해결하고 진행합니다. 새 서비스 기능에 대한 도구 스키마 경고는
실제 AWS API 검증 결과와 구분해 기록합니다.

## 1. Prepare

```bash
.venv/bin/python scripts/deploy_cloudfront.py prepare --app both
```

앱별 `artifacts/cloudfront/desk/`, `artifacts/cloudfront/studio/`에 다음 기록을 남깁니다.

- `before-deployment.json`: 최초 배포 기록
- `before-template.txt`: 변경 전 CloudFormation 템플릿
- `before-policy.json`: 기존 리소스 정책 응답. 기존 정책이 없으면 `null`
- `pending-artifact.json`: 코드 ZIP의 S3 키와 버전
- `prepare-changes.json`: 검토한 Change Set

`prepare`는 코드 ZIP을 업로드하고 CloudFront와 OAC를 배포하지만, 현재 엔드포인트 인증
방식은 유지합니다. 변경은 Web 코드/엔드포인트, 같은 코드 ZIP을 사용하는 worker,
CloudFront 리소스로 제한하며 예상하지 않은 교체나 권한 변경은 중단합니다.
이미 `IamAuth`인 엔드포인트를 `ApplicationManaged`로 되돌리지 않습니다.

## 2. Cutover

```bash
.venv/bin/python scripts/deploy_cloudfront.py cutover --app both
```

CloudFront가 `Deployed`이고 오리진이 해당 앱의 엔드포인트인지 확인합니다. 정확한 배포
ARN으로 제한한 리소스 정책을 적용하고 다시 읽어 대조합니다. 기존 정책이 있으면 현재
`revisionId`를 사용하여 다른 변경을 덮어쓰지 않습니다.

새 CloudFront 주소에서 기존 이용 키가 동작하는 것을 먼저 확인한 뒤, Change Set으로
`WebEndpointAuthType=IamAuth`만 전환합니다. 이후 CloudFront의 인증된 API 응답은 `200`,
직접 오리진은 `403`인지 확인하고 Runtime 버전이 그대로인지 대조합니다.

한 앱만 복구하거나 재시도할 때는 `--app desk` 또는 `--app studio`를 사용합니다.
전체 배포 매핑은 `artifacts/cloudfront/deployment.json`에 저장됩니다.

## 3. Verify

```bash
.venv/bin/python scripts/deploy_cloudfront.py inspect --app both
.venv/bin/python scripts/verify_cloudfront.py
```

검증기는 STS 계정을 확인한 뒤 아래 항목을 검사합니다.

- 두 앱의 실제 CloudFront/OAC 설정과 엣지 응답 헤더
- 익명 요청과 올바른 이용 키 요청 모두에서 직접 오리진 접근 거부
- CloudFront 경유 시 올바른 키 허용, 누락되거나 잘못된 키 거부
- JS와 폰트의 반복 요청에서 캐시 적중, API에서 캐시 비적중과 `no-store`
- 기존 완료 작업의 SSE, 파일 다운로드, 쿼리 문자열을 사용하는 HTML 미리보기
- 문서 스튜디오의 작은 CSV 업로드와 UTF-8 파일명 및 저장 바이트 일치

새 모델 생성 요청은 보내지 않습니다. 업로드 검증 파일은 정상적인 Studio 7일 보관
정책을 따릅니다. SSE 검증은 기존 완료 결과를 읽으므로 긴 활성 작업의 스트리밍 시험이나
서울 사용자 지연 시간 측정을 대신하지 않습니다. 실행 위치와 검증 범위는 결과에 기록합니다.
`scripts/verify_cloudfront_browser.py`는 CloudFront 주소로 로그인, 모델 표시, 계정 마스킹, 언어,
다크 모드, 모바일 화면을 Chromium에서 다시 확인합니다.

## 실패와 복구

`prepare`의 CloudFormation 실패는 rollback을 켠 상태로 처리합니다. 원인을 고친 뒤
해당 앱의 `prepare`를 재실행합니다. `before-*` 백업은 재시도로 덮어쓰지 않습니다.

`cutover`가 완료된 후 HTTP 후속 검증이 실패하면 엔드포인트는 `IamAuth`로 유지합니다.
스크립트가 오리진을 자동으로 공개하지 않습니다. 배포 전파 상태, 정확한 오리진 도메인,
OAC 서명 방식, 리소스 정책의 배포 ARN/엔드포인트 ARN, Authorization 전달을 확인한 뒤
해당 앱의 `cutover`를 다시 실행합니다.

정책의 이전 원문을 복구해야 하면 `before-policy.json`의 정책 내용과 현재 정책을 먼저
대조하고 현재 `revisionId`로 조건부 갱신합니다. 이전 revision ID를 그대로 재사용하지
않습니다. 백업이 `null`이라는 이유만으로 운영 중인 OAC 정책을 삭제하거나 인증 방식을
공개로 바꾸지 않습니다.

## 이후 코드 배포와 캐시 무효화

현재 자산 URL은 파일 내용 해시를 포함하지 않습니다. 새 코드 배포와 오리진 확인이 끝나면
두 배포의 캐시를 무효화합니다. 다음 코드는 배포 기록에서 실제 ID를 읽고 계정을 확인합니다.

```bash
.venv/bin/python - <<'PY'
import json
import time
from pathlib import Path
import boto3

root = Path.cwd()
mapping = json.loads((root / "artifacts/cloudfront/deployment.json").read_text())
session = boto3.Session(region_name="us-east-1")
account = session.client("sts").get_caller_identity()["Account"]
cloudfront = session.client("cloudfront")
for name, app in mapping["apps"].items():
    manifest = json.loads((root / app["deployment_manifest"]).read_text())
    assert manifest["outputs"]["ExpectedAccountId"] == account, "AccountMismatch"
    result = cloudfront.create_invalidation(
        DistributionId=app["distribution_id"],
        InvalidationBatch={
            "CallerReference": f"release-{name}-{time.time_ns()}",
            "Paths": {"Quantity": 1, "Items": ["/*"]},
        },
    )
    print(name, result["Invalidation"]["Id"], result["Invalidation"]["Status"])
PY
```

CloudFront 무효화는 브라우저에 이미 저장된 파일을 지우지 않습니다. 브라우저의 정적 자산
TTL은 최대 300초이므로 즉시 확인할 때는 새로고침 또는 새 브라우저 컨텍스트를 사용합니다.
CloudFront 요청과 데이터 전송, 무료 범위 초과 무효화에는 비용이 발생할 수 있습니다.
위 명령은 앱마다 와일드카드 경로 한 개를 무효화합니다.

## 공식 자료

- AWS 발표: `https://aws.amazon.com/ko/about-aws/whats-new/2026/10/cloudfront-lambda-web-functions-origin/`
- Lambda Web Function OAC: `https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-restricting-access-to-lambda-web.html`
- 인라인 전달 설정: `https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-properties-cloudfront-distribution-forwardedvalues.html`
