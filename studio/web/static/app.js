(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const all = selector => [...document.querySelectorAll(selector)];
  const PREF_KEY = 'documentStudio.preferences';
  const LAST_KEY = 'documentStudio.lastJobId';
  const terminal = new Set(['complete', 'partial', 'failed', 'cancelled', 'uncertain']);
  const phases = ['queued', 'reading', 'analyzing', 'charting', 'diagramming', 'writing', 'packaging', 'done'];
  const i18n = {
    ko: {
      skip: '작업 공간으로 이동', newDocument: '새 문서 만들기', recent: '최근 작업', refresh: '새로고침', historyEmpty: '완성한 문서를 여기에서 다시 열 수 있어요.', loadMore: '이전 작업 더 보기', sidebarNote: '메모에서 문서까지.<br>생각을 전하는 일에 집중하세요.', retention: '작업과 파일은 7일 동안 보관됩니다.', workspace: '작업 공간', documentBuilder: '문서 만들기', connectAccess: '이용 키 연결', accessKey: '스튜디오 이용 키', accessHelp: '관리자에게 받은 이용 키를 입력하세요. 이 브라우저에 저장하지 않습니다.', accessPlaceholder: '이용 키 입력', connect: '연결하기', disconnect: '연결 해제', language: '언어', eyebrow: '생각을 꺼내면, 문서가 됩니다', heading: '좋은 문서의 시작.', intro: '자료를 넣고 원하는 결과를 알려주세요. 함께 정리해 드릴게요.', introChip: '일하는 당신을 위한 스튜디오', yourBrief: 'YOUR BRIEF', editorHeading: '어떤 문서를 만들까요?', revisionTitle: '이전 자료로 새 버전 만들기', revisionHelp: '원본 결과는 최근 작업에 그대로 남아요.', sourceLabel: '자료 추가', sourceOptional: '파일 또는 메모', dropTitle: '파일을 놓거나 눌러서 선택하세요', dropHelp: 'XLSX, CSV, TXT, MD / 최대 5 MB / 파일 1개', notesLabel: '메모를 바로 붙여 넣어도 좋아요', notesPlaceholder: '회의 메모, 보고서 초안, 전달하고 싶은 내용을 넣어주세요.', notesHint: '업로드한 자료와 메모를 함께 활용해요.', promptLabel: '원하는 결과', required: '필수', promptPlaceholder: '예: 이 분기 실적을 임원 보고용으로 정리하고, 월별 추이를 차트로 보여주세요.', meetingExample: '회의 내용 정리', reportExample: '실적 보고서', processExample: '업무 흐름 설명', outputsLabel: '만들 파일', chartOption: '차트<small>PNG + SVG</small>', diagramOption: '다이어그램<small>PNG + SVG</small>', styleLabel: '문서 스타일', generate: '문서 만들기', generateHint: '결과를 확인하고 스타일과 내용을 다시 다듬을 수 있어요.', yourCanvas: 'YOUR CANVAS', resultHeading: '결과 미리보기', ready: '준비됨', emptyTitle: '자료가 이야기가 되는 곳', emptyCopy: '표는 한눈에 들어오는 차트로,<br>흩어진 메모는 잘 읽히는 문서로 정리해요.', stepSource: '자료 넣기', stepDescribe: '원하는 결과 설명', stepDownload: '확인하고 다운로드', elapsed: '걸린 시간', reconnect: '진행 상황 다시 확인', cancel: '작업 중단', downloadAll: '파일 모두 받기', previewLoading: '미리보기를 불러오는 중...', reviseHeading: '조금 다르게 만들어 볼까요?', reviseCopy: '같은 자료로 스타일이나 내용을 바꿔보세요.', revise: '새 버전 만들기', canvasFooter: '편집 가능한 문서와 바로 쓸 수 있는 이미지', reviewReminder: '공유하기 전에 수치와 내용을 한 번 더 확인하세요.', connected: '연결됨', connecting: '연결 중...', submitting: '자료 전달 중...', working: '문서를 만드는 중...', reviseGenerate: '새 버전 만들기', retryGenerate: '같은 요청 다시 확인', dark: '어두운 화면으로 전환', light: '밝은 화면으로 전환', removeFile: '파일 제거', clearRevision: '새 버전 취소', preview: '미리보기', download: '다운로드', contentPreview: '문서 내용 미리보기', officeNote: '문서 내용 미리보기입니다. PowerPoint와 Word의 실제 배치, 글꼴, 페이지 나눔은 내려받은 파일에서 확인하세요.', imageNote: '생성된 이미지 미리보기입니다. 원본 파일을 내려받아 사용할 수 있어요.', noPreview: '이 파일은 내려받아 PowerPoint 또는 Word에서 확인하세요.', fileCount: '{count}개 파일', untitled: '제목 없는 문서', original: '원본 자료로 만든 새 버전', sourceNeeded: '파일을 추가하거나 메모를 입력해주세요.', promptNeeded: '어떤 결과가 필요한지 알려주세요.', outputNeeded: '만들 파일을 하나 이상 선택해주세요.', wrongFile: 'XLSX, CSV, TXT, MD 파일을 선택해주세요.', tooLarge: '파일은 5 MB까지 올릴 수 있어요. 자료를 나누거나 크기를 줄여주세요.', tooManyFiles: '한 번에 파일 하나를 올릴 수 있어요.', notesLong: '메모는 50,000자까지 입력할 수 있어요.', promptLong: '요청은 4,000자 안으로 적어주세요.', keyNeeded: '먼저 스튜디오 이용 키를 입력해주세요.', authError: '이용 키를 확인해주세요. 키가 만료됐다면 관리자에게 새 키를 요청하세요.', networkError: '연결이 원활하지 않아요. 잠시 후 다시 시도해주세요.', missing: '이 작업 또는 파일을 찾을 수 없어요. 보관 기간이 지났을 수 있습니다.', busyError: '지금 다른 문서를 만들고 있어요. 잠시 후 다시 시도해주세요.', inputError: '자료나 요청을 읽을 수 없어요. 파일 형식과 내용을 확인해주세요.', unavailable: '지금 문서를 만들 수 없어요. 잠시 후 다시 시도해주세요.', timeout: '응답을 기다리는 시간이 길어졌어요. 진행 상황을 다시 확인해주세요.', noData: '차트를 만들 숫자 데이터가 부족해요. 자료에 숫자와 항목 이름이 있는지 확인해주세요.', cancelledMessage: '작업을 중단했어요. 같은 자료로 새 버전을 만들 수 있습니다.', failedMessage: '문서를 완성하지 못했어요. 아래 내용을 확인하고 요청을 다듬어주세요.', partialMessage: '일부 파일이 준비됐어요. 경고를 확인한 후 필요한 파일을 내려받으세요.', uncertainMessage: '작업 완료 여부를 아직 확인하지 못했어요. 최근 작업을 새로고침해 확인해주세요.', reconnected: '진행 상황을 다시 연결했어요.', reconnecting: '연결을 다시 확인하고 있어요. 이미 시작한 작업은 새로 만들지 않습니다.', retryNote: '응답을 확인하지 못했어요. 다시 누르면 같은 요청으로 확인하므로 작업이 중복되지 않습니다.', filesStarted: '{count}개 파일의 다운로드를 시작했어요.', browserDownloads: '브라우저에서 여러 파일 다운로드 허용을 요청하면 허용해주세요.', downloadFailed: '파일을 내려받지 못했어요. 연결을 확인한 후 다시 시도해주세요.', preparingDownload: '파일을 준비하는 중...', sourceReuse: '이전 작업의 자료를 사용합니다. 바꾸고 싶은 내용을 알려주세요.', cancelFailed: '중단 여부를 확인하지 못했어요. 진행 상황을 다시 확인해주세요.', noArtifacts: '내려받을 파일이 아직 없어요.', moreHistoryError: '최근 작업을 불러오지 못했어요. 새로고침을 눌러주세요.', fileExpired: '원본 자료의 보관 기간이 지났을 수 있어요. 새 파일로 시작해주세요.', phase: { queued: '작업 순서를 기다리고 있어요', reading: '자료를 읽고 있어요', analyzing: '핵심 내용을 정리하고 있어요', charting: '데이터를 차트로 만들고 있어요', diagramming: '흐름을 그림으로 정리하고 있어요', writing: '문서를 작성하고 있어요', packaging: '파일을 준비하고 있어요', done: '파일이 준비됐어요' }, completePhase: { queued: '작업 시작', reading: '자료 읽기 완료', analyzing: '내용 정리 완료', charting: '차트 작성 완료', diagramming: '다이어그램 작성 완료', writing: '문서 작성 완료', packaging: '파일 준비 완료', done: '작업 완료' }, status: { queued: '대기 중', running: '작성 중', complete: '완료', partial: '일부 완료', failed: '완료하지 못함', cancelled: '중단됨', uncertain: '상태 확인 필요' }, help: { queued: ['자료를 전달했어요. 차례가 되면 작업을 시작합니다.', '진행 상태는 이 화면에서 확인할 수 있어요.'], reading: ['파일과 메모에서 사용할 내용을 살펴봅니다.', '스프레드시트의 항목과 값, 메모의 내용을 확인합니다.'], analyzing: ['요청한 목적에 맞게 내용과 구성을 정리합니다.', '어떤 내용과 수치를 보여줄지 자료를 바탕으로 정리합니다.'], charting: ['자료에 있는 숫자로 비교와 추이를 표현합니다.', '원본에 없는 수치는 만들지 않습니다. 누락된 값은 경고에서 확인할 수 있어요.'], diagramming: ['단계 사이의 관계를 읽기 쉬운 그림으로 정리합니다.', '업무의 순서와 연결 관계를 살펴보고 있어요.'], writing: ['선택한 스타일에 맞춰 읽기 쉬운 문서를 구성합니다.', '완성되면 내용을 확인하고 새 버전으로 다듬을 수 있어요.'], packaging: ['내려받을 문서와 이미지 파일을 준비합니다.', '문서의 최종 배치는 내려받은 파일에서 확인해주세요.'], done: ['파일이 준비됐어요. 공유하기 전에 내용을 확인해주세요.'] }, examples: { meeting: '회의 메모를 핵심 논의 사항, 결정 사항, 담당자별 다음 할 일로 정리해주세요.', report: '첨부한 실적 자료를 바탕으로 핵심 결과와 주요 변화, 확인할 사항을 보고서로 정리해주세요.', process: '자료에 나온 업무 순서를 정리하고, 단계별 연결 관계를 다이어그램으로 보여주세요.' }, styles: { business: ['비즈니스', '차분하고 명확하게'], 'aws-desk': ['AWS Desk', '구조적이고 정돈되게'], presentation: ['프레젠테이션', '핵심이 돋보이게'] }
    },
    en: {
      skip: 'Skip to workspace', newDocument: 'Create a document', recent: 'RECENT WORK', refresh: 'Refresh', historyEmpty: 'Your documents will be here when you want to revisit them.', loadMore: 'Show earlier work', sidebarNote: 'From notes to documents.<br>Focus on the ideas you want to share.', retention: 'Work and files are kept for 7 days.', workspace: 'Workspace', documentBuilder: 'Document builder', connectAccess: 'Connect access key', accessKey: 'Studio access key', accessHelp: 'Enter the access key from your administrator. It is never saved in this browser.', accessPlaceholder: 'Enter your access key', connect: 'Connect', disconnect: 'Disconnect', language: 'Language', eyebrow: 'FROM A FIRST THOUGHT TO A FINISHED DOCUMENT', heading: 'Good work starts here.', intro: 'Add your material and describe what you need. We’ll help put it together.', introChip: 'A little more clarity in your workday', yourBrief: 'YOUR BRIEF', editorHeading: 'What are we making today?', revisionTitle: 'A new version, with the same material', revisionHelp: 'Your original stays in recent work.', sourceLabel: 'Add your material', sourceOptional: 'A file or your notes', dropTitle: 'Drop a file here, or click to browse', dropHelp: 'XLSX, CSV, TXT, MD / Up to 5 MB / One file', notesLabel: 'Or paste your notes right here', notesPlaceholder: 'Meeting notes, a report draft, or the ideas you want to get across.', notesHint: 'Your file and notes can be used together.', promptLabel: 'Describe the result', required: 'Required', promptPlaceholder: 'For example: Turn these quarterly results into an executive summary and show the monthly trend in a chart.', meetingExample: 'Meeting summary', reportExample: 'Performance report', processExample: 'Explain a process', outputsLabel: 'Choose your files', chartOption: 'Charts<small>PNG + SVG</small>', diagramOption: 'Diagrams<small>PNG + SVG</small>', styleLabel: 'Choose a document style', generate: 'Create my documents', generateHint: 'You can review the result and refine the style or content.', yourCanvas: 'YOUR CANVAS', resultHeading: 'Your work, taking shape', ready: 'Ready when you are', emptyTitle: 'Make the story in your material clear.', emptyCopy: 'Turn tables into charts you can understand.<br>Bring scattered notes together in a thoughtful document.', stepSource: 'Add material', stepDescribe: 'Describe the result', stepDownload: 'Review and download', elapsed: 'Time elapsed', reconnect: 'Check progress again', cancel: 'Stop this task', downloadAll: 'Download all files', previewLoading: 'Opening the preview...', reviseHeading: 'A little more like you?', reviseCopy: 'Use the same material with a new style or direction.', revise: 'Make a new version', canvasFooter: 'Editable documents and images ready to use', reviewReminder: 'Review the content and figures before sharing.', connected: 'Connected', connecting: 'Connecting...', submitting: 'Sending your material...', working: 'Creating your documents...', reviseGenerate: 'Create a new version', retryGenerate: 'Check the same request again', dark: 'Switch to dark appearance', light: 'Switch to light appearance', removeFile: 'Remove file', clearRevision: 'Cancel new version', preview: 'Preview', download: 'Download', contentPreview: 'Document content preview', officeNote: 'This is a content preview. Open the downloaded PowerPoint or Word file to check the actual layout, fonts and page breaks.', imageNote: 'Preview of the generated image. Download the original file to use it in your work.', noPreview: 'Download this file to open it in PowerPoint or Word.', fileCount: '{count} files', untitled: 'Untitled document', original: 'A new version using the original material', sourceNeeded: 'Add a file or paste some notes to get started.', promptNeeded: 'Describe the result you would like.', outputNeeded: 'Choose at least one type of file.', wrongFile: 'Choose an XLSX, CSV, TXT or MD file.', tooLarge: 'Files can be up to 5 MB. Split the material or choose a smaller file.', tooManyFiles: 'You can add one file at a time.', notesLong: 'Notes can be up to 50,000 characters.', promptLong: 'Keep your request within 4,000 characters.', keyNeeded: 'Connect your Studio access key first.', authError: 'Check your access key. If it has expired, ask your administrator for a new one.', networkError: 'The connection is taking a break. Please try again shortly.', missing: 'This task or file could not be found. Its storage period may have ended.', busyError: 'Other documents are being created right now. Please try again shortly.', inputError: 'We could not read the material or request. Check the file format and content.', unavailable: 'We cannot create documents right now. Please try again shortly.', timeout: 'The response is taking longer than expected. Check the progress again.', noData: 'There is not enough numeric data for a chart. Check that your material includes numbers and category names.', cancelledMessage: 'This task was stopped. You can make a new version with the same material.', failedMessage: 'We could not finish these documents. Review the details below and adjust your request.', partialMessage: 'Some files are ready. Check the notes below before downloading.', uncertainMessage: 'We could not confirm whether the task finished. Refresh recent work to check again.', reconnected: 'Progress updates are connected again.', reconnecting: 'Reconnecting to your task. We will not create it again.', retryNote: 'We could not confirm the response. Try again to check the same request without creating a duplicate.', filesStarted: 'Started downloading {count} files.', browserDownloads: 'Allow multiple downloads if your browser asks.', downloadFailed: 'The file could not be downloaded. Check your connection and try again.', preparingDownload: 'Preparing your files...', sourceReuse: 'Using the original material. Describe what you would like to change.', cancelFailed: 'We could not confirm that the task stopped. Check its progress again.', noArtifacts: 'There are no files to download yet.', moreHistoryError: 'Recent work could not be loaded. Select Refresh to try again.', fileExpired: 'The original material may have expired. Start with a new file.', phase: { queued: 'Waiting for a place at the desk', reading: 'Reading your material', analyzing: 'Finding the main ideas', charting: 'Giving your numbers a clear shape', diagramming: 'Bringing the process into view', writing: 'Putting your document together', packaging: 'Preparing your files', done: 'Your files are ready' }, completePhase: { queued: 'Task started', reading: 'Material read', analyzing: 'Content organized', charting: 'Charts created', diagramming: 'Diagrams created', writing: 'Documents written', packaging: 'Files prepared', done: 'Task complete' }, status: { queued: 'Waiting', running: 'In progress', complete: 'Complete', partial: 'Partly complete', failed: 'Not completed', cancelled: 'Stopped', uncertain: 'Needs a status check' }, help: { queued: ['Your material is ready. Work will begin when a place is available.', 'You can follow the actual progress here as it happens.'], reading: ['Looking through the file and notes for material to work with.', 'Checking the labels, values and ideas in your source material.'], analyzing: ['Organizing the content around the result you asked for.', 'Using your material to decide what information to highlight.'], charting: ['Showing comparisons and trends using numbers from your material.', 'Missing numbers are not invented. Check any data notes with your result.'], diagramming: ['Turning the relationships between steps into a clear picture.', 'Looking at the order of the work and how the steps connect.'], writing: ['Laying out the document in your chosen style.', 'When it is ready, you can review it and create a refined version.'], packaging: ['Preparing the documents and images for download.', 'Check the final document layout in the downloaded file.'], done: ['Your files are ready. Review the content before sharing.'] }, examples: { meeting: 'Organize these meeting notes into key discussion points, decisions, and next actions for each owner.', report: 'Use the provided performance data to create a report covering the key results, major changes, and items to review.', process: 'Organize the workflow described in the material and show how the steps connect in a diagram.' }, styles: { business: ['Business', 'Calm and considered'], 'aws-desk': ['AWS Desk', 'Structured and precise'], presentation: ['Presentation', 'Let the key ideas lead'] }
    }
  };
  let preferences = {};
  try { preferences = JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); } catch (_) { /* Storage is optional. */ }
  const state = { language: preferences.language === 'en' ? 'en' : 'ko', theme: preferences.theme === 'dark' ? 'dark' : 'light', key: '', connected: false, config: null, file: null, upload: null, sourceJobId: null, job: null, jobs: [], nextCursor: null, busy: false, pending: null, watch: null, poll: null, previewURL: null, previewId: null, previewEpoch: 0, progress: new Map(), helpIndex: 0, artifactSignature: '', downloadBusy: false };
  const text = key => i18n[state.language][key] || key;
  const icon = name => { const element = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); const use = document.createElementNS('http://www.w3.org/2000/svg', 'use'); use.setAttribute('href', '#i-' + name); element.append(use); return element; };
  const active = job => job && !terminal.has(job.status);
  const hide = (id, value = true) => { $(id).hidden = value; };
  function persist(key, value) { try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (_) { /* Private mode can disable storage. */ } }
  function savePreferences() { persist(PREF_KEY, JSON.stringify({ language: state.language, theme: state.theme })); }
  function showNotice(message, error = true) { $('notice').textContent = message; $('notice').classList.toggle('error', error); hide('notice', !message); }
  let toastTimer;
  let selectionEpoch = 0;
  function toast(message) { $('toast').textContent = message; hide('toast', false); clearTimeout(toastTimer); toastTimer = setTimeout(() => hide('toast'), 5500); }
  function formatBytes(size) { return size >= 1048576 ? (size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(size / 1024)) + ' KB'; }
  function dateLabel(value) { const date = new Date(value); return Number.isNaN(+date) ? '' : new Intl.DateTimeFormat(state.language, { month: 'short', day: 'numeric' }).format(date); }
  function friendly(error) {
    const code = String(error?.code || error?.message || '').toLowerCase();
    if (error?.status === 401 || error?.status === 403 || /unauthor|authentic|access.key/.test(code)) return text('authError');
    if (error?.status === 404 || /notfound|not_found/.test(code)) return text('missing');
    if (error?.status === 413 || /toolarge|too_large|upload_limit|size.limit/.test(code)) return text('tooLarge');
    if (error?.status === 429 || /throttl|concurrency|busy/.test(code)) return text('busyError');
    if (/no[_ -]?numeric|numeric.data|chart.*data|empty.chart/.test(code)) return text('noData');
    if (/expired|source.*missing/.test(code)) return text('fileExpired');
    if (error?.status === 400 || error?.status === 422 || /invalid|unsupported|validation/.test(code)) return text('inputError');
    if (/timeout|timed.out|abort/.test(code)) return text('timeout');
    if (error?.status >= 500) return text('unavailable');
    return text('networkError');
  }
  async function request(path, options = {}) {
    const controller = options.signal ? null : new AbortController();
    const timer = controller ? setTimeout(() => controller.abort(), 25000) : null;
    try {
      const response = await fetch(path, { ...options, signal: options.signal || controller.signal, cache: 'no-store', headers: { Authorization: 'Bearer ' + state.key, ...(options.headers || {}) } });
      if (!response.ok) {
        let body = {}; try { body = await response.json(); } catch (_) { /* The friendly status message still applies. */ }
        const error = new Error(typeof body.error === 'string' ? body.error : body.error?.code || body.code || 'RequestFailed');
        error.code = error.message; error.status = response.status;
        if (response.status === 401 || response.status === 403) { state.connected = false; updateControls(); $('access-control').open = true; }
        throw error;
      }
      return options.blob ? await response.blob() : await response.json();
    } finally { clearTimeout(timer); }
  }
  function updateControls() {
    $('generate').disabled = !state.connected || state.busy || Boolean(active(state.job));
    $('generate-label').textContent = state.busy ? text('submitting') : active(state.job) ? text('working') : state.pending ? text('retryGenerate') : state.sourceJobId ? text('reviseGenerate') : text('generate');
    $('access-status').textContent = text(state.connected ? 'connected' : 'connectAccess');
    $('connection-dot').classList.toggle('connected', state.connected);
    hide('disconnect', !state.connected);
    all('#document-form input, #document-form textarea, #document-form button').forEach(element => { if (element.id !== 'generate') element.disabled = state.busy; });
    $('new-document').disabled = state.busy;
    $('refresh-history').disabled = !state.connected;
  }
  function translate() {
    document.documentElement.lang = state.language;
    document.documentElement.dataset.theme = state.theme;
    $('language').value = state.language;
    all('[data-i18n]').forEach(element => { element.innerHTML = text(element.dataset.i18n); });
    all('[data-i18n-placeholder]').forEach(element => { element.placeholder = text(element.dataset.i18nPlaceholder); });
    $('theme-toggle').title = text(state.theme === 'dark' ? 'light' : 'dark');
    $('theme-toggle').setAttribute('aria-label', $('theme-toggle').title);
    $('theme-toggle').replaceChildren(icon(state.theme === 'dark' ? 'sun' : 'moon'));
    $('remove-file').setAttribute('aria-label', text('removeFile'));
    $('clear-revision').setAttribute('aria-label', text('clearRevision'));
    $('preview-frame').title = text('contentPreview');
    renderStyles(); renderHistory(); updateControls();
    if (state.job) renderJob(state.job, true);
    if (state.sourceJobId) $('prompt').placeholder = text('sourceReuse');
  }
  function renderStyles() {
    $('model-info').textContent = state.config?.model
      ? (state.language === 'en' ? 'Model: ' : '사용 모델: ') + state.config.model +
        (state.language === 'en' ? '\nFiles are processed in the US East region.' : '\n자료는 미국 동부 리전에서 처리됩니다.')
      : '';
    Object.entries(i18n[state.language].styles).forEach(([id, fallback]) => {
      const configured = state.config?.styles?.find(style => style.id === id);
      document.querySelector(`[data-style-name="${id}"]`).textContent = configured?.name?.[state.language] || fallback[0];
      document.querySelector(`[data-style-description="${id}"]`).textContent = configured?.description?.[state.language] || fallback[1];
    });
  }
  async function connect(event) {
    event.preventDefault();
    if (!$('access-key').value.trim()) { $('access-error').textContent = text('keyNeeded'); hide('access-error', false); return; }
    stopWatching(); state.key = $('access-key').value.trim(); $('connect').disabled = true; $('connect').textContent = text('connecting'); hide('access-error');
    try {
      state.config = await request('/api/config'); state.connected = true;
      $('prompt').maxLength = state.config.limits?.promptCharacters || 4000;
      $('notes').maxLength = state.config.limits?.notesCharacters || 50000;
      $('access-key').value = ''; $('access-control').open = false;
      renderStyles(); updateControls();
      await loadHistory();
      let lastId; try { lastId = localStorage.getItem(LAST_KEY); } catch (_) { /* Optional history restoration. */ }
      if (lastId) await selectJob(lastId);
    } catch (error) { $('access-error').textContent = friendly(error); hide('access-error', false); if (!state.connected) $('access-control').open = true; }
    finally { $('connect').disabled = false; $('connect').textContent = text('connect'); updateControls(); }
  }
  function disconnect() {
    selectionEpoch++; stopWatching(); clearPreview(); state.key = ''; state.connected = false; state.job = null; state.jobs = []; state.config = null; state.sourceJobId = null; state.pending = null; state.file = null; state.upload = null;
    $('access-key').value = ''; $('notes').value = ''; $('prompt').value = ''; $('file-input').value = ''; $('note-count').textContent = '0 / 50,000'; hide('revision-banner'); hide('source-section', false); hide('selected-file'); hide('drop-zone', false);
    renderHistory(); renderEmpty(); updateControls(); $('access-control').open = true;
  }
  async function loadHistory(append = false) {
    if (!state.connected) return;
    const query = append && state.nextCursor ? '&cursor=' + encodeURIComponent(state.nextCursor) : '';
    try {
      const response = await request('/api/jobs?limit=10' + query);
      const previous = append ? state.jobs : [];
      state.jobs = [...new Map([...previous, ...(response.jobs || [])].map(job => [job.id, job])).values()];
      state.nextCursor = response.next_cursor || null; renderHistory();
    } catch (error) { showNotice(friendly(error) || text('moreHistoryError')); }
  }
  function renderHistory() {
    $('history').replaceChildren();
    if (!state.jobs.length) { const p = document.createElement('p'); p.className = 'empty-history'; p.textContent = text('historyEmpty'); $('history').append(p); }
    state.jobs.forEach(job => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'history-item' + (state.job?.id === job.id ? ' selected' : ''); button.dataset.jobId = job.id;
      if (state.job?.id === job.id) button.setAttribute('aria-current', 'true');
      const content = document.createElement('div'), title = document.createElement('strong'), meta = document.createElement('small');
      title.textContent = job.title || job.prompt || text('untitled'); meta.textContent = dateLabel(job.created_at) + ' / ' + (i18n[state.language].status[job.status] || text('working'));
      content.append(title, meta); button.append(icon('document'), content); button.addEventListener('click', () => selectJob(job.id)); $('history').append(button);
    });
    hide('load-more', !state.nextCursor);
  }
  async function selectJob(id) {
    if (state.busy || !state.connected) return;
    stopWatching(); showNotice(''); const epoch = ++selectionEpoch;
    try { const response = await request('/api/jobs/' + encodeURIComponent(id)); if (epoch !== selectionEpoch) return; applyJob(response.job); if (active(response.job)) watchJob(id); }
    catch (error) { showNotice(friendly(error)); if (error.status === 404) persist(LAST_KEY, null); }
  }
  function recordProgress(job) {
    const progress = state.progress.get(job.id) || { completed: new Set(), last: null };
    if (Array.isArray(job.completed_steps)) {
      progress.completed = new Set();
      job.completed_steps.forEach(step => { const phase = typeof step === 'string' ? step : step.phase || step.id; if (phases.includes(phase)) progress.completed.add(phase); });
    }
    if (phases.includes(job.phase)) progress.last = job.phase;
    state.progress.set(job.id, progress);
  }
  function applyJob(job) {
    if (!job?.id) return;
    const previous = state.job;
    if (previous?.id !== job.id) { clearPreview(); state.artifactSignature = ''; }
    recordProgress(job); state.job = job; persist(LAST_KEY, job.id);
    state.jobs = [job, ...state.jobs.filter(item => item.id !== job.id)];
    renderHistory(); renderJob(job); updateControls();
    if (terminal.has(job.status)) stopWatching();
  }
  function renderEmpty() { hide('empty-result', false); hide('progress-panel'); hide('job-result'); $('result-badge').textContent = text('ready'); $('result-badge').classList.remove('active'); }
  function renderJob(job, force = false) {
    hide('empty-result'); $('result-badge').textContent = i18n[state.language].status[job.status] || text('working'); $('result-badge').classList.toggle('active', Boolean(active(job)));
    if (active(job)) { hide('progress-panel', false); hide('job-result'); renderProgress(); return; }
    hide('progress-panel'); hide('job-result', false); $('job-title').textContent = job.title || text('untitled'); $('job-answer').textContent = job.answer || '';
    $('result-origin').textContent = job.source_job_id ? text('original') : (job.upload?.name || '');
    $('job-messages').replaceChildren();
    const statusMessage = { cancelled: 'cancelledMessage', partial: 'partialMessage', failed: 'failedMessage', uncertain: 'uncertainMessage' }[job.status];
    if (statusMessage) appendMessage(text(statusMessage), job.status === 'failed');
    (job.warnings || []).forEach(warning => appendMessage(safeMessage(warning), false));
    (job.errors || []).forEach(error => appendMessage(safeMessage(error, true), true));
    const artifacts = job.artifacts || [];
    $('artifact-count').textContent = artifacts.length ? text('fileCount').replace('{count}', artifacts.length) : text('noArtifacts');
    $('download-all').disabled = !artifacts.length || state.downloadBusy;
    $('revise').disabled = !state.connected;
    const signature = JSON.stringify([job.id, artifacts, state.language]);
    if (signature !== state.artifactSignature || force) {
      state.artifactSignature = signature; renderArtifacts(artifacts);
      const preview = artifacts.find(item => item.id === state.previewId && previewable(item)) || artifacts.find(item => item.mime === 'text/html') || artifacts.find(previewable);
      if (preview && preview.id !== state.previewId) previewArtifact(preview);
      else if (preview) {
        const html = preview.mime.split(';')[0] === 'text/html';
        $('preview-note').textContent = text(html ? 'officeNote' : 'imageNote');
        $('preview-format').textContent = html ? text('contentPreview') : (preview.filename || '').split('.').pop().toUpperCase();
      }
      if (!preview) clearPreview();
    }
  }
  function safeMessage(value, error = false) {
    if (typeof value === 'string') {
      if ((error && /^[A-Za-z0-9_:-]+$/.test(value)) || /^[A-Za-z_]+(?:Error|Exception|NotFound|Failed)$/.test(value) || /traceback|arn:aws|access.?key|stacktrace|bedrock|lambda|bma session/i.test(value)) return error ? friendly({ code: value }) : text('inputError');
      return value;
    }
    return value?.message && !/arn:aws|traceback|bedrock|lambda/i.test(value.message) ? value.message : friendly({ code: value?.code || value?.error });
  }
  function appendMessage(message, error) { if (!message) return; const p = document.createElement('p'); p.classList.toggle('error', error); p.textContent = message; $('job-messages').append(p); }
  function renderProgress() {
    const job = state.job; if (!active(job)) return;
    const phase = phases.includes(job.phase) ? job.phase : 'queued';
    $('phase-title').textContent = i18n[state.language].phase[phase];
    const help = i18n[state.language].help[phase]; $('phase-help').textContent = help[state.helpIndex % help.length];
    $('completed-steps').replaceChildren();
    const completed = state.progress.get(job.id)?.completed || new Set();
    phases.filter(item => completed.has(item)).forEach(item => { const li = document.createElement('li'); li.append(icon('check'), document.createTextNode(i18n[state.language].completePhase[item])); $('completed-steps').append(li); });
    if (!completed.has(phase)) { const li = document.createElement('li'), dot = document.createElement('span'); li.className = 'current'; dot.className = 'step-dot'; li.append(dot, document.createTextNode(i18n[state.language].phase[phase])); $('completed-steps').append(li); }
    renderTime();
  }
  function renderTime() {
    if (!active(state.job)) return;
    const start = Date.parse(state.job.created_at), seconds = Number.isFinite(start) ? Math.max(0, Math.floor((Date.now() - start) / 1000)) : 0;
    $('elapsed-time').textContent = Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  }
  function stopWatching() { state.watch?.abort(); state.watch = null; clearInterval(state.poll); state.poll = null; }
  async function refreshJob(id, signal) {
    const response = await request('/api/jobs/' + encodeURIComponent(id), signal ? { signal } : {});
    if (!signal?.aborted && state.job?.id === id) applyJob(response.job);
    return response.job;
  }
  async function watchJob(id) {
    stopWatching(); const controller = new AbortController(); state.watch = controller;
    $('connection-message').textContent = ''; hide('reconnect');
    let polling = false;
    state.poll = setInterval(async () => {
      if (polling || controller.signal.aborted) return; polling = true;
      try { await refreshJob(id, controller.signal); } catch (_) { if (!controller.signal.aborted) { $('connection-message').textContent = text('reconnecting'); hide('reconnect', false); } } finally { polling = false; }
    }, 5000);
    while (!controller.signal.aborted && state.job?.id === id && active(state.job) && state.connected) {
      try {
        const response = await fetch('/api/jobs/' + encodeURIComponent(id) + '/events', { headers: { Authorization: 'Bearer ' + state.key, Accept: 'text/event-stream' }, cache: 'no-store', signal: controller.signal });
        if (!response.ok || !response.body) { const error = new Error('StreamUnavailable'); error.status = response.status; throw error; }
        const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = '';
        try {
          while (!controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
            let end;
            while ((end = buffer.indexOf('\n\n')) !== -1) {
              const block = buffer.slice(0, end); buffer = buffer.slice(end + 2);
              const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
              if (!data) continue;
              let event; try { event = JSON.parse(data); } catch (_) { continue; }
              if (event.type === 'error') throw Object.assign(new Error(event.code || 'StreamError'), { code: event.code });
              if (event.job?.id === id && state.job?.id === id) { $('connection-message').textContent = ''; hide('reconnect'); applyJob(event.job); }
            }
          }
        } finally { reader.cancel().catch(() => {}); }
        if (controller.signal.aborted || !active(state.job)) break;
        $('connection-message').textContent = text('reconnecting'); hide('reconnect', false);
        await refreshJob(id, controller.signal);
      } catch (error) {
        if (controller.signal.aborted) break;
        if (error.status === 401 || error.status === 403) { state.connected = false; $('access-control').open = true; showNotice(text('authError')); updateControls(); stopWatching(); break; }
        $('connection-message').textContent = text('reconnecting'); hide('reconnect', false);
        try { await refreshJob(id, controller.signal); } catch (_) { /* Retry reads; never resubmit a job. */ }
      }
      if (!controller.signal.aborted) await new Promise(resolve => { const timer = setTimeout(resolve, 1500); controller.signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true }); });
    }
  }
  function selectFile(fileList) {
    if (!fileList?.length) return;
    if (fileList.length > 1) { showNotice(text('tooManyFiles')); return; }
    const file = fileList[0];
    if (!/\.(xlsx|csv|txt|md)$/i.test(file.name)) { showNotice(text('wrongFile')); $('file-input').value = ''; return; }
    if (file.size > (state.config?.limits?.fileBytes || 5242880)) { showNotice(text('tooLarge')); $('file-input').value = ''; return; }
    state.file = file; state.upload = null; state.pending = null;
    $('file-name').textContent = file.name; $('file-size').textContent = formatBytes(file.size); hide('selected-file', false); hide('drop-zone'); showNotice('');
  }
  function removeFile() { state.file = null; state.upload = null; state.pending = null; $('file-input').value = ''; hide('selected-file'); hide('drop-zone', false); }
  function newDocument() {
    if (state.busy) return;
    selectionEpoch++; stopWatching(); clearPreview(); state.job = null; state.sourceJobId = null; state.pending = null; state.artifactSignature = ''; removeFile();
    $('notes').value = ''; $('prompt').value = ''; $('prompt').placeholder = text('promptPlaceholder'); $('note-count').textContent = '0 / 50,000'; hide('revision-banner'); hide('source-section', false); showNotice(''); persist(LAST_KEY, null); renderEmpty(); renderHistory(); updateControls(); $('prompt').focus({ preventScroll: true });
  }
  function revise() {
    if (!state.job || active(state.job)) return;
    state.sourceJobId = state.job.id; state.pending = null;
    $('revision-name').textContent = state.job.title || text('untitled'); hide('revision-banner', false); hide('source-section');
    $('prompt').value = ''; $('prompt').placeholder = text('sourceReuse');
    all('input[name="style"]').forEach(input => { input.checked = input.value === state.job.style; });
    all('input[name="output"]').forEach(input => { input.checked = (state.job.outputs || ['pptx', 'docx']).includes(input.value); });
    updateControls(); $('editor-heading').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' }); $('prompt').focus({ preventScroll: true });
  }
  async function generate(event) {
    event.preventDefault(); if (state.busy || active(state.job)) return;
    if (!state.connected) { showNotice(text('keyNeeded')); $('access-control').open = true; return; }
    const notes = $('notes').value.trim(), prompt = $('prompt').value.trim(), outputs = all('input[name="output"]:checked').map(input => input.value), style = document.querySelector('input[name="style"]:checked')?.value || 'business';
    if (!state.sourceJobId && !state.file && !notes) { showNotice(text('sourceNeeded')); $('notes').focus(); return; }
    if (!prompt) { showNotice(text('promptNeeded')); $('prompt').focus(); return; }
    if (!outputs.length) { showNotice(text('outputNeeded')); return; }
    if (notes.length > (state.config?.limits?.notesCharacters || 50000)) { showNotice(text('notesLong')); return; }
    if (prompt.length > (state.config?.limits?.promptCharacters || 4000)) { showNotice(text('promptLong')); return; }
    state.busy = true; updateControls(); showNotice('');
    let posting = false;
    try {
      if (state.file && !state.upload && !state.sourceJobId) {
        const response = await request('/api/uploads', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(state.file.name) }, body: state.file });
        state.upload = response.upload;
      }
      const input = { ...(state.sourceJobId ? {} : { notes }), prompt, outputs, style, language: state.language };
      if (state.sourceJobId) input.source_job_id = state.sourceJobId;
      else if (state.upload) input.upload_id = state.upload.id;
      const fingerprint = JSON.stringify(input);
      if (!state.pending || state.pending.fingerprint !== fingerprint) state.pending = { fingerprint, body: { request_id: crypto.randomUUID(), ...input } };
      posting = true; let response;
      for (let attempt = 0; attempt < 2; attempt++) {
        try { response = await request('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(state.pending.body) }); break; }
        catch (error) { if (attempt || (error.status && error.status < 500 && error.status !== 429)) throw error; await new Promise(resolve => setTimeout(resolve, 800)); }
      }
      if (!response?.job?.id) throw new Error('MissingJob');
      state.pending = null; state.sourceJobId = null; hide('revision-banner'); hide('source-section', false); $('prompt').placeholder = text('promptPlaceholder');
      applyJob(response.job); if (active(response.job)) watchJob(response.job.id);
    } catch (error) { if (error.status && error.status < 500 && error.status !== 429) state.pending = null; showNotice(friendly(error) + (posting && state.pending ? '\n' + text('retryNote') : '')); }
    finally { state.busy = false; updateControls(); }
  }
  async function cancelJob() {
    const job = state.job; if (!active(job)) return;
    $('cancel-job').disabled = true;
    try { const response = await request('/api/jobs/' + encodeURIComponent(job.id) + '/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); if (state.job?.id === job.id && response.job) applyJob(response.job); else await refreshJob(job.id); }
    catch (error) { showNotice(text('cancelFailed') + ' ' + friendly(error)); }
    finally { $('cancel-job').disabled = false; }
  }
  function previewable(artifact) { return ['text/html', 'image/png', 'image/svg+xml', 'image/jpeg', 'image/webp'].includes((artifact.mime || '').split(';')[0]); }
  function artifactURL(artifact, inline = false, jobId = state.job?.id) { return '/api/jobs/' + encodeURIComponent(jobId) + '/artifacts/' + encodeURIComponent(artifact.id) + (inline ? '?view=inline' : ''); }
  function renderArtifacts(artifacts) {
    $('artifact-list').replaceChildren();
    artifacts.forEach(artifact => {
      const card = document.createElement('div'); card.className = 'artifact-card' + (state.previewId === artifact.id ? ' selected' : ''); card.dataset.artifactId = artifact.id;
      const main = document.createElement('button'); main.type = 'button'; main.className = 'artifact-main';
      const label = document.createElement('div'), title = document.createElement('strong'), meta = document.createElement('small');
      title.textContent = artifact.filename || artifact.title || text('untitled'); meta.textContent = ((artifact.filename || '').split('.').pop() || artifact.kind || 'FILE').toUpperCase() + (artifact.size ? ' / ' + formatBytes(artifact.size) : '');
      main.setAttribute('aria-label', (previewable(artifact) ? text('preview') : text('download')) + ': ' + title.textContent);
      label.append(title, meta); main.append(icon(artifact.kind === 'chart' ? 'chart' : artifact.kind === 'diagram' ? 'diagram' : artifact.kind === 'pptx' ? 'slides' : 'document'), label);
      main.addEventListener('click', () => previewable(artifact) ? previewArtifact(artifact) : downloadArtifact(artifact));
      const download = document.createElement('button'); download.type = 'button'; download.className = 'icon-button'; download.dataset.download = artifact.id; download.title = text('download') + ': ' + title.textContent; download.setAttribute('aria-label', download.title); download.append(icon('download')); download.addEventListener('click', () => downloadArtifact(artifact, download));
      card.append(main, download); $('artifact-list').append(card);
    });
  }
  function clearPreview() {
    state.previewEpoch++; state.previewId = null;
    if (state.previewURL) URL.revokeObjectURL(state.previewURL); state.previewURL = null;
    $('preview-frame').removeAttribute('src'); $('preview-image').removeAttribute('src'); hide('preview-frame'); hide('preview-image'); hide('preview-shell'); hide('preview-error');
  }
  async function previewArtifact(artifact) {
    if (!previewable(artifact)) { toast(text('noPreview')); return; }
    clearPreview(); state.previewId = artifact.id; const epoch = state.previewEpoch, jobId = state.job.id;
    hide('preview-shell', false); hide('preview-loading', false); $('preview-title').textContent = artifact.title || artifact.filename;
    const html = artifact.mime.split(';')[0] === 'text/html'; $('preview-format').textContent = html ? text('contentPreview') : (artifact.filename || '').split('.').pop().toUpperCase();
    $('preview-note').textContent = text(html ? 'officeNote' : 'imageNote');
    all('.artifact-card').forEach(card => card.classList.toggle('selected', card.dataset.artifactId === artifact.id));
    try {
      const blob = await request(artifactURL(artifact, true), { blob: true });
      if (epoch !== state.previewEpoch || state.job?.id !== jobId) return;
      // Force the declared safe preview type; the iframe has no permissions, including scripts.
      const type = html ? 'text/html' : artifact.mime.split(';')[0];
      state.previewURL = URL.createObjectURL(new Blob([blob], { type }));
      if (html) { $('preview-frame').src = state.previewURL; hide('preview-frame', false); }
      else { $('preview-image').src = state.previewURL; $('preview-image').alt = artifact.title || artifact.filename; hide('preview-image', false); }
    } catch (error) { if (epoch === state.previewEpoch) { $('preview-error').textContent = friendly(error); hide('preview-error', false); } }
    finally { if (epoch === state.previewEpoch) hide('preview-loading'); }
  }
  async function downloadArtifact(artifact, button, quiet = false, jobId = state.job?.id) {
    if (button) button.disabled = true;
    try {
      const blob = await request(artifactURL(artifact, false, jobId), { blob: true });
      const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = (artifact.filename || 'document').replace(/[\x00-\x1f/\\]/g, '_'); link.style.display = 'none'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000); return true;
    } catch (error) { if (!quiet) showNotice(text('downloadFailed') + ' ' + friendly(error)); return false; }
    finally { if (button) button.disabled = false; }
  }
  async function downloadAll() {
    if (state.downloadBusy || !state.job?.artifacts?.length) return;
    state.downloadBusy = true; $('download-all').disabled = true; toast(text('preparingDownload'));
    // Fetch each binary through the authenticated endpoint before using a short-lived Blob URL.
    const artifacts = [...state.job.artifacts], jobId = state.job.id; let count = 0;
    for (const artifact of artifacts) if (await downloadArtifact(artifact, null, true, jobId)) count++;
    state.downloadBusy = false; $('download-all').disabled = false;
    if (count !== artifacts.length) showNotice(text('downloadFailed'));
    toast(text('filesStarted').replace('{count}', count) + ' ' + text('browserDownloads'));
  }
  $('access-form').addEventListener('submit', connect);
  $('disconnect').addEventListener('click', disconnect);
  $('language').addEventListener('change', event => { state.language = event.target.value; savePreferences(); translate(); });
  $('theme-toggle').addEventListener('click', () => { state.theme = state.theme === 'dark' ? 'light' : 'dark'; savePreferences(); translate(); });
  $('new-document').addEventListener('click', newDocument);
  $('refresh-history').addEventListener('click', async () => { await loadHistory(); if (state.job) await selectJob(state.job.id); });
  $('load-more').addEventListener('click', () => loadHistory(true));
  $('file-input').addEventListener('change', event => selectFile(event.target.files));
  $('remove-file').addEventListener('click', removeFile);
  $('notes').addEventListener('input', () => { $('note-count').textContent = $('notes').value.length.toLocaleString() + ' / 50,000'; });
  $('drop-zone').addEventListener('dragover', event => { event.preventDefault(); $('drop-zone').classList.add('dragging'); });
  $('drop-zone').addEventListener('dragleave', () => $('drop-zone').classList.remove('dragging'));
  $('drop-zone').addEventListener('drop', event => { event.preventDefault(); $('drop-zone').classList.remove('dragging'); if (!state.busy) selectFile(event.dataTransfer.files); });
  document.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  document.addEventListener('drop', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  all('[data-example]').forEach(button => button.addEventListener('click', () => { $('prompt').value = i18n[state.language].examples[button.dataset.example]; $('prompt').focus(); }));
  $('document-form').addEventListener('submit', generate);
  $('revise').addEventListener('click', revise);
  $('clear-revision').addEventListener('click', () => { state.sourceJobId = null; state.pending = null; hide('revision-banner'); hide('source-section', false); $('prompt').placeholder = text('promptPlaceholder'); updateControls(); });
  $('cancel-job').addEventListener('click', cancelJob);
  $('reconnect').addEventListener('click', async () => { if (!state.job) return; const id = state.job.id; try { await refreshJob(id); if (active(state.job)) watchJob(id); } catch (error) { showNotice(friendly(error)); } });
  $('download-all').addEventListener('click', downloadAll);
  window.addEventListener('pagehide', () => { stopWatching(); clearPreview(); });
  setInterval(renderTime, 1000);
  setInterval(() => { state.helpIndex++; if (active(state.job)) renderProgress(); }, 9000);
  translate();
})();
