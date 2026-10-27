# Runbook: Deploy to us-east-1

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Overview
Build the Runtime image and Web Function ZIP, publish them under new immutable versions, and update the
`bma-seoul-build` and `bma-seoul-inventory` CloudFormation stacks in `us-east-1`. The query target stays
`ap-northeast-2`. Commands are taken from the README deployment section and the verified deployment in
[aws-deployment.md](../aws-deployment.md).

Both public apps now use CloudFront. Follow the [OAC rollout runbook](cloudfront-oac.md)
for first-time distribution/policy setup and for cache invalidation after Web releases.
`WebUrl` is the public CDN address; `OriginWebUrl` requires IAM and is not a browser entry point.

## When to Use
- Releasing a new version of `aws_inventory/`, `skills/`, `runtime/` or `web/`
- Changing `infra/template.yaml` parameters, IAM or limits (`MAX_*`)
- Rotating `APP_ACCESS_TOKEN`

## Prerequisites
- AWS credentials for the deployment account (the account pinned in `artifacts/deployment-context.json`)
- Docker with `linux/arm64` build support, `jq`, AWS CLI v2
- `.venv` and `web/node_modules` installed (`bash scripts/setup.sh`)
- Official Codex 0.164.0 Linux ARM64 binary available to `scripts/prepare_runtime.py`
- A new version string `VERSION` (ECR tags are `IMMUTABLE`; never reuse a tag)

## Procedure

### 1. Preflight and tests
```bash
.venv/bin/python -m pytest
npm test --prefix web
.venv/bin/cfn-lint infra/bootstrap.yaml infra/template.yaml
.venv/bin/python scripts/preflight.py --list-models
```
cfn-lint currently exits 4 with `W3037` warnings for the `bedrock-mantle:*` IAM actions (its IAM spec predates
them). Warnings are expected; any `E` code blocks the deployment.

### 2. Build artifacts
```bash
export VERSION=0.1.0   # replace with the new version
.venv/bin/python scripts/export_web_contract.py
.venv/bin/python scripts/prepare_runtime.py
docker build --platform linux/arm64 -f runtime/Dockerfile -t "bma-seoul-runtime:$VERSION" .
.venv/bin/python scripts/check_runtime.py
.venv/bin/python scripts/build_web.py
```
`scripts/check_runtime.py` inspects the hardcoded tag `bma-seoul-runtime:0.1.0` (`IMAGE` at line 11).
When `VERSION` differs, update `IMAGE` first so the check runs against the image you just built.

### 3. Bootstrap stack and environment
```bash
export APP_REGION=us-east-1 TARGET_REGION=ap-northeast-2
export EXPECTED_ACCOUNT_ID="$(jq -r .expected_account_id artifacts/deployment-context.json)"
export BMA_MODEL=openai.gpt-6-luna
export AGENT_BACKEND=bma MODEL_PROCESSING_SCOPE=app_region

aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-build --template-file infra/bootstrap.yaml \
  --parameter-overrides WebFunctionName=bma-seoul-inventory-web

export BMA_CODE_BUCKET="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`CodeBucket`].OutputValue | [0]' --output text)"
export BMA_ECR_URI="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRepositoryUri`].OutputValue | [0]' --output text)"
```

### 4. Publish the image and ZIP
```bash
aws ecr get-login-password --region "$APP_REGION" |
  docker login --username AWS --password-stdin "${BMA_ECR_URI%%/*}"
docker tag "bma-seoul-runtime:$VERSION" "$BMA_ECR_URI:$VERSION"
docker push "$BMA_ECR_URI:$VERSION"
export BMA_IMAGE_DIGEST="$(aws ecr describe-images --region "$APP_REGION" \
  --repository-name bma-seoul-runtime --image-ids imageTag="$VERSION" --query 'imageDetails[0].imageDigest' --output text)"

aws s3api put-object --region "$APP_REGION" --bucket "$BMA_CODE_BUCKET" \
  --key "web/$VERSION.zip" --body artifacts/web-function.zip > artifacts/code-upload.json
export BMA_CODE_VERSION="$(jq -r .VersionId artifacts/code-upload.json)"
```

### 5. Deploy the application stack
Record the rollback target first: the image digest in `runtime_image_uri` and the `code_version_id` from the
current `artifacts/aws-deployment.json`.

Type the access key yourself; it must not appear in shell history, source or logs.
```bash
read -rs APP_ACCESS_TOKEN
export APP_ACCESS_TOKEN
.venv/bin/python scripts/deployment_parameters.py   # writes artifacts/deploy-parameters.json (mode 0600)
aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-inventory --template-file infra/template.yaml \
  --capabilities CAPABILITY_IAM --parameter-overrides file://artifacts/deploy-parameters.json
```
Do not pass `--disable-rollback` for Web Revision replacements. If the stack name changes, keep the
bootstrap `WebFunctionName` equal to the real function name.

## Verification
- [ ] `aws cloudformation describe-stacks --region us-east-1 --stack-name bma-seoul-inventory --query 'Stacks[0].StackStatus'` returns `UPDATE_COMPLETE` (or `CREATE_COMPLETE`)
- [ ] `curl -s "$WEB_URL/health"` returns `{"status":"ok"}` and `curl -s -o /dev/null -w '%{http_code}' "$WEB_URL/api/context"` returns `401`
- [ ] With the user's approval (live model and AWS calls): `.venv/bin/python scripts/verify_deployed.py` passes (reads `artifacts/aws-deployment.json`)
- [ ] `docs/aws-deployment.md` updated with the new image digest, ZIP `VersionId`, Web Revision and verification evidence

## Rollback
1. CloudFormation rolls back a failed update automatically; confirm with `aws cloudformation describe-stack-events --region us-east-1 --stack-name bma-seoul-inventory --max-items 20`.
2. To revert a successful but bad release, export the rollback target recorded in step 5 as `BMA_IMAGE_DIGEST` and `BMA_CODE_VERSION` (keep `BMA_CODE_BUCKET`), re-run `scripts/deployment_parameters.py`, and repeat the `aws cloudformation deploy` command of step 5.
3. Never delete ECR images or code ZIP versions during an incident; they are the rollback targets.

## Notes
- Last verified: 2026-10-27 (us-east-1 deployment with operations investigations, see [aws-deployment.md](../aws-deployment.md))
- The deployment limits `MAX_RESOURCES`, `MAX_PAGES`, `MAX_METRIC_HOURS`, `MAX_DATAPOINTS`, `MAX_TURN_SECONDS` are read from the environment by `scripts/deployment_parameters.py`. Set `BMA_CODE_KEY` to use a content-hash code path.

---

<a id="korean"></a>

# 한국어

## 개요
Runtime 이미지와 Web Function ZIP을 빌드해 새 불변 버전으로 게시하고, `us-east-1`의 `bma-seoul-build`,
`bma-seoul-inventory` CloudFormation 스택을 업데이트합니다. 조회 대상은 계속 `ap-northeast-2`입니다.
명령은 README의 배포 절차와 [aws-deployment.md](../aws-deployment.md)에 기록된 검증된 배포에서 가져왔습니다.

## 사용 시점
- `aws_inventory/`, `skills/`, `runtime/`, `web/`의 새 버전을 배포할 때
- `infra/template.yaml`의 파라미터, IAM, 한도(`MAX_*`)를 바꿀 때
- `APP_ACCESS_TOKEN`을 교체할 때

## 사전 요구 사항
- 배포 계정(`artifacts/deployment-context.json`에 고정된 계정)의 AWS 자격증명
- `linux/arm64` 빌드를 지원하는 Docker, `jq`, AWS CLI v2
- 설치된 `.venv`와 `web/node_modules`(`bash scripts/setup.sh`)
- `scripts/prepare_runtime.py`가 찾을 수 있는 공식 Codex 0.164.0 Linux ARM64 바이너리
- 새 버전 문자열 `VERSION`(ECR 태그는 `IMMUTABLE`이므로 재사용하지 않습니다)

## 절차

### 1. 사전 확인과 테스트
```bash
.venv/bin/python -m pytest
npm test --prefix web
.venv/bin/cfn-lint infra/bootstrap.yaml infra/template.yaml
.venv/bin/python scripts/preflight.py --list-models
```
현재 cfn-lint는 `bedrock-mantle:*` IAM action에 대해 `W3037` 경고와 함께 exit 4를 반환합니다(cfn-lint의 IAM
스펙이 해당 action보다 오래되었기 때문입니다). 경고는 예상된 결과이며, `E` 코드가 하나라도 있으면 배포를 중단합니다.

### 2. 산출물 빌드
```bash
export VERSION=0.1.0   # replace with the new version
.venv/bin/python scripts/export_web_contract.py
.venv/bin/python scripts/prepare_runtime.py
docker build --platform linux/arm64 -f runtime/Dockerfile -t "bma-seoul-runtime:$VERSION" .
.venv/bin/python scripts/check_runtime.py
.venv/bin/python scripts/build_web.py
```
`scripts/check_runtime.py`는 하드코딩된 태그 `bma-seoul-runtime:0.1.0`(11행의 `IMAGE`)을 검사합니다.
`VERSION`이 다르면 먼저 `IMAGE`를 고쳐 방금 빌드한 이미지를 검사하게 합니다.

### 3. Bootstrap 스택과 환경 변수
```bash
export APP_REGION=us-east-1 TARGET_REGION=ap-northeast-2
export EXPECTED_ACCOUNT_ID="$(jq -r .expected_account_id artifacts/deployment-context.json)"
export BMA_MODEL=openai.gpt-6-luna
export AGENT_BACKEND=bma MODEL_PROCESSING_SCOPE=app_region

aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-build --template-file infra/bootstrap.yaml \
  --parameter-overrides WebFunctionName=bma-seoul-inventory-web

export BMA_CODE_BUCKET="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`CodeBucket`].OutputValue | [0]' --output text)"
export BMA_ECR_URI="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRepositoryUri`].OutputValue | [0]' --output text)"
```

### 4. 이미지와 ZIP 게시
```bash
aws ecr get-login-password --region "$APP_REGION" |
  docker login --username AWS --password-stdin "${BMA_ECR_URI%%/*}"
docker tag "bma-seoul-runtime:$VERSION" "$BMA_ECR_URI:$VERSION"
docker push "$BMA_ECR_URI:$VERSION"
export BMA_IMAGE_DIGEST="$(aws ecr describe-images --region "$APP_REGION" \
  --repository-name bma-seoul-runtime --image-ids imageTag="$VERSION" --query 'imageDetails[0].imageDigest' --output text)"

aws s3api put-object --region "$APP_REGION" --bucket "$BMA_CODE_BUCKET" \
  --key "web/$VERSION.zip" --body artifacts/web-function.zip > artifacts/code-upload.json
export BMA_CODE_VERSION="$(jq -r .VersionId artifacts/code-upload.json)"
```

### 5. 애플리케이션 스택 배포
먼저 롤백 대상을 기록합니다. 현재 `artifacts/aws-deployment.json`의 `runtime_image_uri`에 있는 이미지 digest와
`code_version_id`입니다.

접속 키는 직접 입력합니다. 셸 이력, 소스, 로그에 남기지 않습니다.
```bash
read -rs APP_ACCESS_TOKEN
export APP_ACCESS_TOKEN
.venv/bin/python scripts/deployment_parameters.py   # writes artifacts/deploy-parameters.json (mode 0600)
aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-inventory --template-file infra/template.yaml \
  --capabilities CAPABILITY_IAM --parameter-overrides file://artifacts/deploy-parameters.json
```
Web Revision 교체 업데이트에는 `--disable-rollback`을 사용하지 않습니다. 스택 이름을 바꾸면
bootstrap의 `WebFunctionName`도 실제 함수 이름과 일치시킵니다.

## 검증
- [ ] `aws cloudformation describe-stacks --region us-east-1 --stack-name bma-seoul-inventory --query 'Stacks[0].StackStatus'` 결과가 `UPDATE_COMPLETE`(또는 `CREATE_COMPLETE`)입니다
- [ ] `curl -s "$WEB_URL/health"` 결과가 `{"status":"ok"}`이고 `curl -s -o /dev/null -w '%{http_code}' "$WEB_URL/api/context"` 결과가 `401`입니다
- [ ] 사용자 승인 후(실제 모델과 AWS 호출) `.venv/bin/python scripts/verify_deployed.py`가 통과합니다(`artifacts/aws-deployment.json`을 읽습니다)
- [ ] `docs/aws-deployment.md`에 새 이미지 digest, ZIP `VersionId`, Web Revision, 검증 근거를 반영했습니다

## 롤백
1. 실패한 업데이트는 CloudFormation이 자동으로 롤백합니다. `aws cloudformation describe-stack-events --region us-east-1 --stack-name bma-seoul-inventory --max-items 20`으로 확인합니다.
2. 배포는 성공했지만 문제가 있는 릴리스를 되돌리려면 5단계에서 기록한 롤백 대상을 `BMA_IMAGE_DIGEST`, `BMA_CODE_VERSION`으로 설정하고(`BMA_CODE_BUCKET`은 유지) `scripts/deployment_parameters.py`를 다시 실행한 뒤 5단계의 `aws cloudformation deploy` 명령을 반복합니다.
3. 장애 대응 중에는 ECR 이미지나 코드 ZIP 버전을 삭제하지 않습니다. 롤백 대상이기 때문입니다.

## 참고
- 최종 검증일: 2026-10-27(운영 조사를 포함한 us-east-1 배포, [aws-deployment.md](../aws-deployment.md) 참고)
- 배포 한도 `MAX_RESOURCES`, `MAX_PAGES`, `MAX_METRIC_HOURS`, `MAX_DATAPOINTS`, `MAX_TURN_SECONDS`는 `scripts/deployment_parameters.py`가 환경 변수에서 읽습니다. 내용 해시 기반 코드 경로를 쓰려면 `BMA_CODE_KEY`를 설정합니다.
