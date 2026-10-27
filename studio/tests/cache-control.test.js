import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { createStudioApp } from "../web/server.js";

const accountId = "123456789012";
const authorization = "Bearer local-cache-test-key";
const jobId = "11111111-1111-4111-8111-111111111111";
async function withApp(callback) {
  const settings = { accountId, accessToken: "local-cache-test-key", appRegion: "us-east-1", model: "openai.gpt-6.1-sol" };
  const server = createStudioApp(settings, {
    identity: async () => accountId,
    store: { async upload(name, bytes) { return { id: jobId, name, size: bytes.length, extension: ".txt" }; } },
    jobs: {
      async get() { return { job: { id: jobId, status: "complete" } }; },
      async *events() { yield { type: "complete", job: { id: jobId, status: "complete" } }; },
      async artifact() { return { bytes: Buffer.from("<h1>Private report</h1>"), mime: "text/html", filename: "report.html" }; },
    },
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try { await callback(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test("studio caches only anonymous public assets and gives HEAD the same metadata", async () => {
  await withApp(async base => {
    for (const [path, cacheControl] of [
      ["/", "public, max-age=0, s-maxage=60, must-revalidate"],
      ["/static/app.js", "public, max-age=300, s-maxage=3600, must-revalidate"],
      ["/static/style.css", "public, max-age=300, s-maxage=3600, must-revalidate"],
      ["/static/fonts/NanumSquareB.otf", "public, max-age=300, s-maxage=3600, must-revalidate"],
    ]) {
      const response = await fetch(base + path);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("cache-control"), cacheControl);
      assert.equal(response.headers.get("x-content-type-options"), "nosniff");
      assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
      const bytes = await response.arrayBuffer();
      assert.ok(bytes.byteLength > 0);
      const head = await fetch(base + path, { method: "HEAD" });
      assert.equal(head.status, 200);
      assert.equal(head.headers.get("cache-control"), cacheControl);
      assert.equal(Number(head.headers.get("content-length")), bytes.byteLength);
      assert.equal((await head.arrayBuffer()).byteLength, 0);
    }
    for (const headers of [{ authorization }, { cookie: "session=private" }]) {
      const response = await fetch(base + "/static/app.js", { headers });
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("cache-control"), "no-store");
      await response.arrayBuffer();
    }
  });
});

test("studio does not cache authenticated config, uploads, streams, documents or errors", async () => {
  await withApp(async base => {
    for (const [path, options, status] of [
      ["/api/config", {}, 401],
      ["/api/config", { headers: { authorization } }, 200],
      ["/health", {}, 200],
      ["/static/missing.js", {}, 404],
      ["/static/style.css", { method: "POST" }, 404],
      ["/api/uploads", { method: "POST", headers: { authorization, "x-file-name": "sample.txt" }, body: "private note" }, 201],
      ["/api/uploads", { method: "POST", headers: { authorization, "x-file-name": "sample.exe" }, body: "private note" }, 422],
    ]) {
      const response = await fetch(base + path, options);
      assert.equal(response.status, status);
      assert.equal(response.headers.get("cache-control"), "no-store");
      await response.text();
    }
    const stream = await fetch(`${base}/api/jobs/${jobId}/events`, { headers: { authorization } });
    assert.equal(stream.status, 200);
    assert.equal(stream.headers.get("cache-control"), "no-store");
    assert.match(stream.headers.get("content-type"), /text\/event-stream/);
    assert.match(await stream.text(), /"type":"complete"/);
    for (const suffix of ["", "?view=inline"]) {
      const download = await fetch(`${base}/api/jobs/${jobId}/artifacts/report${suffix}`, { headers: { authorization } });
      assert.equal(download.status, 200);
      assert.equal(download.headers.get("cache-control"), "no-store");
      assert.match(download.headers.get("content-security-policy"), /sandbox/);
      assert.match(await download.text(), /Private report/);
    }
  });
});
