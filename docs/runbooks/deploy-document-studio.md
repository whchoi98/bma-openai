# Runbook: Deploy AI Document Studio

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Overview
Build the document Runtime image and the Studio Web Function ZIP, then create or update the
`bma-office-build` and `bma-office-studio` CloudFormation stacks in `us-east-1` with
`studio/scripts/deploy.py`. The script never touches the Operations Desk stacks
(`bma-seoul-build`, `bma-seoul-inventory`). Usage and limits: [document-studio.md](../document-studio.md).

Studio's public `WebUrl` is a CloudFront address. Complete the
[OAC setup and release invalidation](cloudfront-oac.md) before handing over a
new deployment. Its `OriginWebUrl` uses `IamAuth` and is not a browser entry point.

## When to Use
- Releasing a change to `studio/document_tools/`, `studio/skills/`, `studio/web/` or `web/bma.js`
- Changing `studio/infra/template.yaml` or the Studio model (`BmaModel`)

## Prerequisites
- An existing Operations Desk deployment: `deploy.py` reads the account and the shared access-key file from `artifacts/aws-deployment.json` and stops when STS returns another account
- AWS credentials for that account, Docker with `linux/arm64` builds, `.venv`, `.studio-venv`, `web/node_modules` and the `studio/node_modules` link (see `studio/CLAUDE.md`)
- `runtime/bin/codex` placed by `.venv/bin/python scripts/prepare_runtime.py`
- Real account and model cost: confirm with the account owner before running any `deploy.py` phase or live verification

## Procedure

### 1. Tests and lint (no AWS calls)
```bash
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
.venv/bin/cfn-lint studio/infra/bootstrap.yaml studio/infra/template.yaml
```
cfn-lint exits 4 with `W3037` warnings for the `bedrock-mantle:*` actions, as for the desk templates. Any `E` code blocks the deployment.

### 2. Build artifacts
```bash
docker build --platform linux/arm64 -f studio/RuntimeDockerfile -t bma-office-runtime:0.1.0 .
.venv/bin/python studio/scripts/build_web.py      # artifacts/studio/web-function.zip + web-build.json
```
`deploy.py artifacts` always pushes the local `bma-office-runtime:0.1.0` image under a content-derived tag `studio-<image id>`; rebuild that local tag for every release.

### 3. Bootstrap (first deployment only)
```bash
.venv/bin/python studio/scripts/deploy.py bootstrap
```
Creates `bma-office-build` (ECR `bma-office-runtime`, code bucket) and the state file `artifacts/studio/deployment.json`.

### 4. Select the model
`deploy.py` starts `model` at `openai.gpt-6-luna`, which is also the template and `studio/web/config.js` default.
The live deployment uses `openai.gpt-6.1-sol`. Before `main` or `update`, check the value:
```bash
jq -r .model artifacts/studio/deployment.json
```
Allowed values: `openai.gpt-6-luna`, `openai.gpt-6.1-sol`, `openai.gpt-6.1-terra`. Terra has not been quality-checked for this app.

### 5. Publish and deploy
```bash
jq '{runtime_image_uri, code_key, code_version_id}' artifacts/studio/deployment.json > artifacts/studio/previous-release.json
.venv/bin/python studio/scripts/deploy.py artifacts   # push image by digest, upload ZIP (S3 VersionId)
.venv/bin/python studio/scripts/deploy.py main        # first deployment: create bma-office-studio
.venv/bin/python studio/scripts/deploy.py update      # later releases: new image, ZIP version and model
```
`update` keeps every other stack parameter (including `AppAccessToken`) and runs with rollback enabled. Both `main` and `update` finish with `inspect`.

## Verification
- `.venv/bin/python studio/scripts/deploy.py inspect` reports Runtime, Web endpoint and worker status
- Live flows (model cost): `.venv/bin/python studio/scripts/verify_live.py --case excel|presentation|notes`
- Live browser check (model cost): `.venv/bin/python studio/scripts/verify_browser.py`
- Evidence goes to `artifacts/studio/` (gitignored); update [document-studio.md](../document-studio.md) with verified results

## Rollback
- A failed `update` rolls back automatically (CloudFormation rollback is never disabled)
- To return to the previous release, copy `runtime_image_uri`, `code_key` and `code_version_id` from `artifacts/studio/previous-release.json` back into `artifacts/studio/deployment.json` and run `deploy.py update`

## Notes
- The Studio access key is the Operations Desk `APP_ACCESS_TOKEN`; never print it or the secret file
- Data bucket objects expire after 7 days (noncurrent versions after 1 day); BMA session retention is separate
- README screenshots do not need a deployment: `.venv/bin/python scripts/capture_screenshots.py studio`

---

<a id="korean"></a>

# 한국어

## 개요
문서 Runtime 이미지와 Studio Web Function ZIP을 빌드한 뒤 `studio/scripts/deploy.py`로 `us-east-1`의
`bma-office-build`, `bma-office-studio` CloudFormation 스택을 만들거나 갱신합니다. 이 스크립트는
운영 데스크 스택(`bma-seoul-build`, `bma-seoul-inventory`)을 건드리지 않습니다. 사용법과 한도는
[document-studio.md](../document-studio.md)를 참고합니다.

## 사용 시점
- `studio/document_tools/`, `studio/skills/`, `studio/web/` 또는 `web/bma.js` 변경을 배포할 때
- `studio/infra/template.yaml`이나 Studio 모델(`BmaModel`)을 바꿀 때

## 사전 요구 사항
- 운영 데스크 배포가 있어야 합니다. `deploy.py`는 `artifacts/aws-deployment.json`에서 계정과 공유 이용 키 파일을 읽고, STS 계정이 다르면 중단합니다
- 해당 계정의 AWS 자격증명, `linux/arm64` 빌드가 가능한 Docker, `.venv`, `.studio-venv`, `web/node_modules`, `studio/node_modules` 링크(`studio/CLAUDE.md` 참고)
- `.venv/bin/python scripts/prepare_runtime.py`로 배치한 `runtime/bin/codex`
- 실제 계정과 모델 비용이 발생합니다. `deploy.py`의 모든 단계와 실제 검증은 계정 소유자에게 먼저 확인합니다

## 절차

### 1. 테스트와 lint(AWS 호출 없음)
```bash
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
.venv/bin/cfn-lint studio/infra/bootstrap.yaml studio/infra/template.yaml
```
운영 데스크 템플릿과 마찬가지로 cfn-lint는 `bedrock-mantle:*` 액션에 대한 `W3037` 경고와 함께 종료 코드 4를 반환합니다. `E` 코드가 하나라도 있으면 배포하지 않습니다.

### 2. 산출물 빌드
```bash
docker build --platform linux/arm64 -f studio/RuntimeDockerfile -t bma-office-runtime:0.1.0 .
.venv/bin/python studio/scripts/build_web.py      # artifacts/studio/web-function.zip + web-build.json
```
`deploy.py artifacts`는 항상 로컬 `bma-office-runtime:0.1.0` 이미지를 내용 기반 태그 `studio-<image id>`로 push합니다. 배포할 때마다 이 로컬 태그를 다시 빌드합니다.

### 3. Bootstrap(최초 배포만)
```bash
.venv/bin/python studio/scripts/deploy.py bootstrap
```
`bma-office-build`(ECR `bma-office-runtime`, 코드 버킷)와 상태 파일 `artifacts/studio/deployment.json`을 만듭니다.

### 4. 모델 선택
`deploy.py`는 `model`을 `openai.gpt-6-luna`로 시작하며, 이는 템플릿과 `studio/web/config.js`의 기본값이기도 합니다.
현재 배포는 `openai.gpt-6.1-sol`을 사용합니다. `main`이나 `update` 전에 값을 확인합니다.
```bash
jq -r .model artifacts/studio/deployment.json
```
허용 값은 `openai.gpt-6-luna`, `openai.gpt-6.1-sol`, `openai.gpt-6.1-terra`입니다. Terra는 이 앱에서 품질을 검증하지 않았습니다.

### 5. 게시와 배포
```bash
jq '{runtime_image_uri, code_key, code_version_id}' artifacts/studio/deployment.json > artifacts/studio/previous-release.json
.venv/bin/python studio/scripts/deploy.py artifacts   # push image by digest, upload ZIP (S3 VersionId)
.venv/bin/python studio/scripts/deploy.py main        # first deployment: create bma-office-studio
.venv/bin/python studio/scripts/deploy.py update      # later releases: new image, ZIP version and model
```
`update`는 나머지 스택 파라미터(`AppAccessToken` 포함)를 그대로 유지하고 rollback을 켠 상태로 실행합니다. `main`과 `update`는 마지막에 `inspect`를 실행합니다.

## 검증
- `.venv/bin/python studio/scripts/deploy.py inspect`로 Runtime, Web endpoint, worker 상태를 확인합니다
- 실제 생성 흐름(모델 비용 발생): `.venv/bin/python studio/scripts/verify_live.py --case excel|presentation|notes`
- 실제 브라우저 확인(모델 비용 발생): `.venv/bin/python studio/scripts/verify_browser.py`
- 근거는 `artifacts/studio/`(gitignore 대상)에 저장되며, 검증한 결과로 [document-studio.md](../document-studio.md)를 갱신합니다

## 롤백
- `update`가 실패하면 자동으로 롤백됩니다(CloudFormation rollback을 끄지 않습니다)
- 이전 릴리스로 되돌리려면 `artifacts/studio/previous-release.json`의 `runtime_image_uri`, `code_key`, `code_version_id`를 `artifacts/studio/deployment.json`에 다시 넣고 `deploy.py update`를 실행합니다

## 참고
- Studio 이용 키는 운영 데스크의 `APP_ACCESS_TOKEN`입니다. 키와 비밀 파일 내용을 출력하지 않습니다
- 데이터 버킷 객체는 7일 뒤(이전 버전은 1일 뒤) 만료되며, BMA 세션 보관은 이와 별도입니다
- README 화면은 배포 없이 만듭니다: `.venv/bin/python scripts/capture_screenshots.py studio`
