import assert from 'node:assert/strict';
import test from 'node:test';
import { createServer } from 'node:http';
import { readFile, mkdir } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';

// An isolated local service exercises the real browser UI without model or AWS calls.
// Catches lost authentication, duplicate jobs, unsafe previews, bad revisions and persistent secrets.
test('studio handles file input, retry identity, real progress, previews, revisions and recovery', { skip: !process.env.STUDIO_PLAYWRIGHT, timeout: 45000 }, async () => {
  const playwright = process.env.STUDIO_PLAYWRIGHT;
  const { chromium } = await import(pathToFileURL(playwright).href);
  const root = fileURLToPath(new URL('../../', import.meta.url));
  const requests = [], jobs = new Map();
  let retryFirst = true, streamCount = 0, revisionPosted;
  const artifact = { id: 'document-preview', filename: 'preview.html', mime: 'text/html', kind: 'preview', title: 'Quarterly review', size: 120 };
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    const json = (body, code = 200) => { res.writeHead(code, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); };
    try {
      if (!url.pathname.startsWith('/api/')) {
        const path = url.pathname === '/' ? 'studio/web/static/index.html' : 'studio/web' + url.pathname;
        const mime = path.endsWith('.css') ? 'text/css' : path.endsWith('.js') ? 'application/javascript' : path.endsWith('.otf') ? 'font/otf' : 'text/html';
        res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'");
        res.setHeader('Content-Type', mime); return res.end(await readFile(root + path));
      }
      requests.push({ path: url.pathname, method: req.method, auth: req.headers.authorization });
      if (req.headers.authorization !== 'Bearer local-secret') return json({ error: 'Unauthorized' }, 401);
      if (url.pathname === '/api/config') return json({ styles: [{ id: 'business', name: { ko: '업무 보고서', en: 'Business report' }, description: { ko: '정돈된 표와 명확한 요약으로 전달합니다.', en: 'Clear summaries and structured tables.' } }, { id: 'aws-desk', name: { ko: 'AWS 운영 데스크', en: 'AWS Operations Desk' }, description: { ko: '네이비와 청록, 나눔스퀘어의 익숙한 스타일입니다.', en: 'Navy, teal and familiar NanumSquare typography.' } }, { id: 'presentation', name: { ko: '발표 자료', en: 'Presentation' }, description: { ko: '핵심 문장과 큰 시각 자료에 집중합니다.', en: 'Key messages and prominent visuals.' } }], limits: { fileBytes: 5242880, notesCharacters: 50000, promptCharacters: 4000 }, formats: ['pptx', 'docx', 'chart', 'diagram'] });
      if (url.pathname === '/api/uploads') {
        assert.equal(decodeURIComponent(req.headers['x-file-name']), '분기.csv');
        return json({ upload: { id: 'upload-1', name: '분기.csv', size: 24, extension: 'csv' } });
      }
      if (url.pathname === '/api/jobs' && req.method === 'GET') return json({ jobs: [...jobs.values()].reverse(), next_cursor: null, complete: true });
      let body = '';
      for await (const chunk of req) body += chunk;
      if (url.pathname === '/api/jobs' && req.method === 'POST') {
        const input = JSON.parse(body);
        if (input.source_job_id) revisionPosted = input;
        const existing = jobs.get(input.request_id);
        const job = existing || { id: input.request_id, title: 'Quarterly review', prompt: input.prompt, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), status: 'running', phase: 'reading', style: input.style, language: input.language, outputs: input.outputs, source_job_id: input.source_job_id, upload: { id: 'upload-1', name: '분기.csv' }, artifacts: [], warnings: [], errors: [], answer: '' };
        jobs.set(job.id, job);
        if (retryFirst) { retryFirst = false; return json({ error: 'Unavailable' }, 503); }
        return json({ job }, 202);
      }
      const id = url.pathname.split('/')[3], job = jobs.get(id);
      if (!job) return json({ error: 'JobNotFound' }, 404);
      if (url.pathname.endsWith('/events')) {
        res.writeHead(200, { 'Content-Type': 'text/event-stream' });
        if (job.prompt === 'Stop this task') return res.end(`data: ${JSON.stringify({ type: 'snapshot', job })}\n\n`);
        if (streamCount++ === 0) return res.end(`data: ${JSON.stringify({ type: 'snapshot', job })}\n\n`);
        job.phase = 'writing'; job.completed_steps = ['reading'];
        res.write(`data: ${JSON.stringify({ type: 'snapshot', job })}\n\n`);
        setTimeout(() => {
          Object.assign(job, { status: job.prompt === 'Partial documents' ? 'partial' : job.prompt === 'Failed documents' ? 'failed' : 'complete', phase: 'done', answer: 'Your quarterly review is ready.', artifacts: [artifact, { id: 'slides', filename: 'review.pptx', mime: 'application/vnd.openxmlformats-officedocument.presentationml.presentation', kind: 'pptx', size: 20 }, { id: 'report', filename: 'review.docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', kind: 'docx', size: 20 }, { id: 'chart', filename: 'revenue.svg', mime: 'image/svg+xml', kind: 'chart', size: 90 }], warnings: ['One blank cell was omitted.'] });
          if (job.status === 'failed') { job.artifacts = []; job.errors = [{ code: 'NoNumericData' }]; }
          res.end(`data: ${JSON.stringify({ type: 'complete', job })}\n\n`);
        }, 650);
        return;
      }
      if (url.pathname.includes('/artifacts/')) {
        const asset = url.pathname.split('/').at(-1);
        if (asset === 'document-preview') { res.setHeader('Content-Type', 'text/html'); return res.end('<html><body><h1>Quarterly review</h1><script>parent.document.body.dataset.compromised="yes"</script></body></html>'); }
        if (asset === 'chart') { res.setHeader('Content-Type', 'image/svg+xml'); return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><rect width="200" height="100" fill="blue"/></svg>'); }
        res.setHeader('Content-Type', 'application/octet-stream'); return res.end('PK-real-download-fixture');
      }
      if (url.pathname.endsWith('/cancel')) { Object.assign(job, { status: 'cancelled' }); return json({ job }); }
      return json({ job });
    } catch (error) { json({ error: error.message }, 500); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ executablePath: process.env.STUDIO_CHROMIUM || undefined, headless: true, args: ['--no-sandbox'] });
    const page = await browser.newPage({ viewport: { width: 1512, height: 1100 }, reducedMotion: 'reduce' });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator('#access-key').fill('local-secret');
    await page.locator('#connect').click();
    await page.waitForFunction(() => !document.querySelector('#generate').disabled);
    await page.locator('#language').selectOption('en');
    assert.equal(await page.locator('input[name="style"]').count(), 3);
    await mkdir(root + 'artifacts/studio', { recursive: true });
    await page.evaluate(async () => { await document.fonts.ready; document.activeElement?.blur(); scrollTo(0, 0); });
    await page.screenshot({ path: root + 'artifacts/studio/frontend-empty-en.png', fullPage: true });
    await page.locator('#file-input').setInputFiles({ name: 'wrong.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('wrong') });
    assert.match(await page.locator('#notice').innerText(), /XLSX, CSV, TXT/);
    assert.equal(requests.filter(r => r.path === '/api/uploads').length, 0);
    await page.locator('#file-input').setInputFiles({ name: 'large.csv', mimeType: 'text/csv', buffer: Buffer.alloc(5242881) });
    assert.match(await page.locator('#notice').innerText(), /up to 5 MB/);
    assert.equal(requests.filter(r => r.path === '/api/uploads').length, 0);
    await page.locator('#file-input').setInputFiles({ name: '분기.csv', mimeType: 'text/csv', buffer: Buffer.from('Month,Revenue\nJan,100\n') });
    await page.locator('#notes').fill('Private source note');
    await page.locator('#prompt').fill('Summarize the quarterly results');
    await page.locator('#generate').click();
    await page.waitForFunction(() => document.querySelector('#progress-panel') && !document.querySelector('#progress-panel').hidden);
    assert.equal(await page.locator('[role="progressbar"][aria-valuenow]').count(), 0);
    await page.waitForFunction(() => !document.querySelector('#job-result').hidden && document.querySelectorAll('.artifact-card').length === 4);
    assert.equal(jobs.size, 1, 'retry must reuse the same request identifier');
    assert.ok(requests.filter(r => r.path.endsWith('/events')).length >= 2, 'stream should recover after early close');
    assert.equal(await page.locator('#preview-frame').getAttribute('sandbox'), '');
    await page.frameLocator('#preview-frame').locator('h1').waitFor();
    assert.equal(await page.locator('body').getAttribute('data-compromised'), null);
    assert.match(await page.locator('#preview-note').innerText(), /content preview/i);
    const downloadEvent = page.waitForEvent('download');
    await page.locator('[data-download="slides"]').click();
    const download = await downloadEvent;
    assert.equal(download.suggestedFilename(), 'review.pptx');
    assert.equal((await readFile(await download.path())).toString(), 'PK-real-download-fixture');
    const allDownloads = [];
    const allReceived = new Promise(resolve => {
      const listener = item => { allDownloads.push(item.suggestedFilename()); if (allDownloads.length === 4) { page.off('download', listener); resolve(); } };
      page.on('download', listener);
    });
    await page.locator('#download-all').click();
    await allReceived;
    assert.deepEqual(allDownloads.sort(), ['preview.html', 'revenue.svg', 'review.docx', 'review.pptx']);
    await page.locator('[data-artifact-id="chart"] .artifact-main').click();
    await page.waitForFunction(() => !document.querySelector('#preview-image').hidden && document.querySelector('#preview-image').naturalWidth > 0);
    assert.match(await page.locator('#preview-image').getAttribute('src'), /^blob:/);
    await page.locator('[data-artifact-id="document-preview"] .artifact-main').click();
    await page.frameLocator('#preview-frame').locator('h1').waitFor();
    await page.locator('#revise').click();
    await page.locator('input[name="style"][value="presentation"]').check();
    await page.locator('#prompt').fill('Make an executive presentation');
    await page.locator('#generate').click();
    await page.waitForFunction(() => document.querySelectorAll('.history-item').length === 2);
    assert.equal(revisionPosted.source_job_id, [...jobs.keys()][0]);
    assert.equal(revisionPosted.style, 'presentation');
    assert.equal(revisionPosted.upload_id, undefined);
    assert.equal(revisionPosted.notes, undefined, 'an omitted notes field lets the service reuse the original notes');
    await page.waitForFunction(() => !document.querySelector('#job-result').hidden && document.querySelectorAll('.artifact-card').length === 4);
    const saved = await page.evaluate(() => ({ ...localStorage }));
    assert.doesNotMatch(JSON.stringify(saved), /local-secret|Private source note|Summarize the quarterly/);
    assert.ok(Object.keys(saved).every(key => ['documentStudio.preferences', 'documentStudio.lastJobId'].includes(key)));
    await mkdir(root + 'artifacts/studio', { recursive: true });
    await page.locator('#toast').waitFor({ state: 'hidden' });
    await page.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
    await page.frameLocator('#preview-frame').locator('h1').waitFor();
    await page.screenshot({ path: root + 'artifacts/studio/frontend-desktop.png', fullPage: true });
    await page.locator('#theme-toggle').click();
    await page.screenshot({ path: root + 'artifacts/studio/frontend-dark.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: root + 'artifacts/studio/frontend-mobile.png', fullPage: true });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.reload();
    assert.equal(await page.locator('#access-key').inputValue(), '');
    await page.locator('#access-key').fill('local-secret');
    await page.locator('#connect').click();
    await page.waitForFunction(() => !document.querySelector('#job-result').hidden && document.querySelectorAll('.artifact-card').length === 4);
    assert.equal(jobs.size, 2, 'refresh restores results without creating a job');
    await page.setViewportSize({ width: 1512, height: 1100 });
    await page.locator('#new-document').click();
    await page.locator('#language').selectOption('ko');
    await page.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
    await page.screenshot({ path: root + 'artifacts/studio/frontend-empty-ko.png', fullPage: true });
    await page.locator('#language').selectOption('en');
    await page.locator('#notes').fill('Notes for a cancellable task');
    await page.locator('#prompt').fill('Stop this task');
    await page.locator('#generate').click();
    await page.waitForFunction(() => !document.querySelector('#progress-panel').hidden);
    await page.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
    await page.screenshot({ path: root + 'artifacts/studio/frontend-progress.png', fullPage: true });
    await page.locator('#cancel-job').click();
    await page.waitForFunction(() => !document.querySelector('#job-result').hidden && document.querySelector('#result-badge').textContent === 'Stopped');
    assert.equal(await page.locator('.artifact-card').count(), 0);
    assert.match(await page.locator('#job-messages').innerText(), /task was stopped/);
    for (const [prompt, badge] of [['Partial documents', 'Partly complete'], ['Failed documents', 'Not completed']]) {
      await page.locator('#new-document').click();
      await page.locator('#notes').fill('Input notes');
      await page.locator('#prompt').fill(prompt);
      await page.locator('#generate').click();
      await page.waitForFunction(expected => !document.querySelector('#job-result').hidden && document.querySelector('#result-badge').textContent === expected, badge);
      assert.equal(await page.locator('.artifact-card').count(), prompt === 'Partial documents' ? 4 : 0);
      if (prompt === 'Failed documents') assert.match(await page.locator('#job-messages').innerText(), /not enough numeric data/);
    }
    assert.deepEqual(errors, []);
    assert.ok(requests.every(r => r.auth === 'Bearer local-secret'));
  } finally { await browser?.close(); await new Promise(resolve => server.close(resolve)); }
});
