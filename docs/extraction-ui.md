# AWSops 화면 추출 기록

원본: `/home/ec2-user/my-project/awsops` (awsops_v2가 아님). 원본 파일은 수정하지 않았다.

| 원본 | SHA-256 |
| --- | --- |
| `src/app/topology/page.tsx` | `d276a3216229e14ef286a0a566e79c9f229486834a6a2e8bd95b896ec6fbc8f9` |
| `src/lib/queries/relationships.ts` | `efcf6340bf49581c0f0de7156d2c2d552f85a4345fefb4f54b9a470e7ff8a105` |
| `src/app/inventory/page.tsx` | `1a7ac63241c9b071e19b4e16f0eedb881e1374f22092f0607825f342dd6f5fb9` |
| `src/lib/queries/security.ts` | `c984335e2bc949a99fe2d7f7097bbec546363f115e2109d91127f0d4d602af9e` |

`src/app/topology/page.tsx`와 `relationships.ts`의 VPC/서브넷/게이트웨이/리소스 참조 관계를
`web/resource-insights.js`로 추출했다. 기존 SQL POST 호출과 전역 데이터 수집은 가져오지 않았다.
현재 MCP가 실제 반환한 ID만 노드로 만들고, 양쪽 ID가 모두 관측된 관계만 연결한다.
빠진 리소스, 관계, 페이지와 노드 100개 제한은 부분 범위로 표시한다.

화면은 기존 React 화면과 CSP에 맞게 `web/ui/resource-insights.js`의 SVG로 구현했다.
확대/축소, 키보드 선택, 선택 리소스의 정규화된 근거 표시를 제공한다.
관계도는 구성 참조이며 실제 통신 시험 결과가 아니다.

원본 인벤토리 화면의 저장 시각별 탐색 개념은 `web/ui/history-panel.js`에 적용했다.
원본의 비용 추정 상수와 계정 전체 추세 추정은 가져오지 않았다.
현재 S3의 고정 계정/리전 이력을 불러오며, 이력 로드와 문서 변환은 리소스/모델 재조회를 하지 않는다.

보안 표시에서는 실제 도구의 `security_checks`만 사용한다.
확인되지 않은 값은 unknown으로 남기며, 원본의 MFA 0 상수나 전체 보안 점수는 사용하지 않는다.
