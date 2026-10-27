import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { createApp } from "../server.js";
import { settingsFromEnv } from "../settings.js";

const authorization = "Bearer local-cache-test-key";
async function withApp(callback) {
  const settings = settingsFromEnv({ DATA_MODE: "sample", APP_ACCESS_TOKEN: "local-cache-test-key" });
  const server = createApp(settings);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  try { await callback(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test("desk caches anonymous public assets with bounded freshness and supports HEAD", async () => {
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

test("desk never caches authenticated state, streams, downloads or errors", async () => {
  await withApp(async base => {
    for (const [path, options, status] of [
      ["/api/context", {}, 401],
      ["/api/context", { headers: { authorization } }, 200],
      ["/health", {}, 200],
      ["/static/missing.js", {}, 404],
      ["/static/style.css", { method: "POST" }, 404],
      ["/api/chat", { method: "POST", headers: { authorization }, body: "{}" }, 422],
    ]) {
      const response = await fetch(base + path, options);
      assert.equal(response.status, status);
      assert.equal(response.headers.get("cache-control"), "no-store");
      await response.text();
    }
    const stream = await fetch(base + "/api/chat", {
      method: "POST", headers: { authorization }, body: JSON.stringify({ prompt: "서울 EC2", language: "ko" }),
    });
    assert.equal(stream.status, 200);
    assert.equal(stream.headers.get("cache-control"), "no-store");
    assert.match(stream.headers.get("content-type"), /text\/event-stream/);
    const events = (await stream.text()).split("\n").filter(line => line.startsWith("data: "))
      .map(line => JSON.parse(line.slice(6)));
    const completed = events.find(event => event.type === "complete");
    assert.ok(completed);
    const download = await fetch(`${base}/api/runs/${completed.id}/report.html`, { headers: { authorization } });
    assert.equal(download.status, 200);
    assert.equal(download.headers.get("cache-control"), "no-store");
    assert.match(download.headers.get("content-disposition"), /attachment/);
    await download.text();
  });
});
