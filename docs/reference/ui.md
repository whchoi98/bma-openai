# UI / UI 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The UI layer is the single-page "AI-Powered AWS Operations Desk" served from `webapp/static/`. It shows the verified account (last 3 digits only), the app and target regions, sample or live mode, the real model ID, query steps and tool records, a streaming Markdown answer, report history and the investigations panel, with Korean/English and light/dark toggles. It exists to make the data processing scope visible to the user while keeping every asset local (no CDN).

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Page shell | `webapp/static/index.html` | Layout, `language-toggle` and `theme-toggle` buttons, sandboxed report preview iframe |
| Bundled script | `webapp/static/app.js` | Generated from `web/ui/app.js` by `npm run build --prefix web`; do not edit by hand |
| App styles | `webapp/static/style.css` | Design tokens on `:root`, dark palette under `[data-theme=dark]` |
| Report styles | `webapp/static/report.css` | Styles shared by HTML report preview and downloads |
| Font and license | `webapp/static/fonts/NanumSquareB.otf`, `webapp/static/fonts/OFL.txt` | Local NAVER NanumSquare OTF Bold under the SIL OFL |
| Localization | `web/ui/i18n.js` | `translate()` and `applyLanguage()` for `ko` and `en` strings |
| Display rules | `web/presentation.js` | `maskAccountIds()` and narrative cleanup applied to answers, records and reports |
| Markdown renderer | `web/markdown.js` | `MarkdownResult` with `skipHtml`, safe links and image placeholders |

### 3. Key Decisions
- Bundle the NanumSquare OTF and its OFL license as static assets — the page and downloaded reports render the same font without any external request, and the CSP stays `default-src 'self'`.
- Mask account IDs to the last 3 digits in the UI and in Markdown, HTML, DOCX and PPTX reports, including IDs split across streaming chunks — the screen can be shown in demos while STS comparison and S3 evidence keep the full 12-digit ID (`docs/data-and-scope.md`).
- Render answers with `skipHtml: true` and replace images with their alt text — model output cannot inject raw HTML, scripts or remote image beacons.
- Preview stored HTML reports in an iframe with `sandbox="allow-same-origin"` (no `allow-scripts`) — the report is readable in place but cannot execute code.
- Persist only display preferences (theme, language) in `localStorage` with try/catch fallbacks — the page works when storage is blocked and never stores the access key.

### 4. Code Pointers
- `webapp/static/index.html:16` — language and theme toggle buttons
- `webapp/static/index.html:170` — sandboxed report preview iframe
- `webapp/static/style.css:94` — dark theme tokens
- `web/ui/app.js:18` — theme preference with `prefers-color-scheme` fallback
- `web/ui/i18n.js:185` — `translate()` lookup
- `web/presentation.js:15` — `maskAccountIds()`
- `web/markdown.js:32` — image placeholder instead of remote image loading

### 5. Cross-references
- Related modules: `webapp/`, `web/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [frontend.md](frontend.md), [security.md](security.md), [extraction-ui.md](../extraction-ui.md), [data-and-scope.md](../data-and-scope.md)

<a id="korean"></a>
## 한국어

### 1. 개요
UI 계층은 `webapp/static/`에서 제공하는 단일 페이지 "AI-Powered AWS Operations Desk"입니다. 확인된 계정(마지막 3자리만), 앱과 조회 대상 리전, 샘플 또는 실제 모드, 실제 모델 ID, 조회 단계와 도구 기록, 스트리밍 Markdown 답변, 보고서 이력과 운영 조사 패널을 표시하며 한국어/English와 라이트/다크 전환을 제공합니다. 모든 자산을 로컬에 두고(CDN 없음) 데이터 처리 범위를 사용자에게 보여 주기 위해 존재합니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Page shell | `webapp/static/index.html` | 레이아웃, `language-toggle`과 `theme-toggle` 버튼, sandbox 보고서 미리보기 iframe |
| Bundled script | `webapp/static/app.js` | `npm run build --prefix web`으로 `web/ui/app.js`에서 생성하며 직접 수정하지 않음 |
| App styles | `webapp/static/style.css` | `:root`의 디자인 토큰, `[data-theme=dark]` 아래 다크 팔레트 |
| Report styles | `webapp/static/report.css` | HTML 보고서 미리보기와 다운로드가 공유하는 스타일 |
| Font and license | `webapp/static/fonts/NanumSquareB.otf`, `webapp/static/fonts/OFL.txt` | SIL OFL 라이선스의 로컬 NAVER 나눔스퀘어 OTF Bold |
| Localization | `web/ui/i18n.js` | `ko`, `en` 문자열을 위한 `translate()`와 `applyLanguage()` |
| Display rules | `web/presentation.js` | 답변, 기록, 보고서에 적용하는 `maskAccountIds()`와 문장 정리 |
| Markdown renderer | `web/markdown.js` | `skipHtml`, 안전한 링크, 이미지 대체 텍스트를 적용한 `MarkdownResult` |

### 3. 주요 결정
- 나눔스퀘어 OTF와 OFL 라이선스를 정적 자산으로 포함합니다 — 화면과 다운로드한 보고서가 외부 요청 없이 같은 폰트로 표시되고 CSP를 `default-src 'self'`로 유지합니다.
- 화면과 Markdown, HTML, DOCX, PPTX 보고서에서 계정 ID를 마지막 3자리만 표시하며 스트리밍 중 나뉜 번호도 가립니다 — 데모에서 화면을 보여 줄 수 있고, STS 비교와 S3 근거에는 12자리 전체 ID가 남습니다(`docs/data-and-scope.md`).
- 답변은 `skipHtml: true`로 렌더링하고 이미지는 alt 텍스트로 바꿉니다 — 모델 출력이 raw HTML, 스크립트, 원격 이미지 추적을 주입할 수 없습니다.
- 저장된 HTML 보고서는 `sandbox="allow-same-origin"`(`allow-scripts` 없음) iframe에서 미리 봅니다 — 보고서를 그 자리에서 읽을 수 있지만 코드는 실행되지 않습니다.
- 표시 설정(테마, 언어)만 try/catch로 감싼 `localStorage`에 저장합니다 — 저장소가 차단돼도 화면이 동작하며 접속 키는 저장하지 않습니다.

### 4. 코드 포인터
- `webapp/static/index.html:16` — 언어와 테마 전환 버튼
- `webapp/static/index.html:170` — sandbox 보고서 미리보기 iframe
- `webapp/static/style.css:94` — 다크 테마 토큰
- `web/ui/app.js:18` — `prefers-color-scheme`을 기본값으로 쓰는 테마 설정
- `web/ui/i18n.js:185` — `translate()` 조회
- `web/presentation.js:15` — `maskAccountIds()`
- `web/markdown.js:32` — 원격 이미지 로드 대신 이미지 대체 텍스트 표시

### 5. 상호 참조
- 관련 모듈: `webapp/`, `web/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [frontend.md](frontend.md), [security.md](security.md), [extraction-ui.md](../extraction-ui.md), [data-and-scope.md](../data-and-scope.md)
