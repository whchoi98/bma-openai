export function createHistoryPanel({ t, language, fetchJson, loadRun, currentId, canLoad }) {
  const list = document.getElementById("history-list");
  const status = document.getElementById("history-status");
  const refreshButton = document.getElementById("history-refresh");
  const moreButton = document.getElementById("history-more");
  let runs = [], cursor = null, loading = false, disabled = true, error = null, loaded = false;
  let generation = 0;

  function render() {
    list.replaceChildren();
    status.textContent = error ? t(error) : loading ? t("historyLoading") : runs.length >= 100 ? t("historyLimit")
      : loaded && !runs.length ? t("historyEmpty") : "";
    refreshButton.disabled = loading || disabled;
    moreButton.disabled = loading || disabled || !cursor;
    moreButton.hidden = !cursor;
    for (const run of runs) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.runId = run.id;
      button.className = "history-item" + (run.id === currentId() ? " selected" : "");
      button.disabled = loading || disabled;
      const prompt = document.createElement("strong");
      prompt.textContent = run.prompt || t("historyUntitled");
      const when = document.createElement("span");
      when.textContent = new Intl.DateTimeFormat(language() === "en" ? "en-GB" : "ko-KR", {
        dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul", hour12: false,
      }).format(new Date(run.created_at)) + " KST";
      const scope = document.createElement("small");
      scope.textContent = `${(run.queried_services || []).join(", ") || t("historyNoResources")} / ${run.target_region}`;
      const coverage = document.createElement("small");
      coverage.className = run.coverage?.complete ? "result-label" : "coverage-note";
      coverage.textContent = run.coverage?.complete ? t("done") : t("historyPartial");
      button.append(prompt, when, scope, coverage);
      button.addEventListener("click", async () => {
        if (!canLoad()) return;
        await loadRun(run.id);
        render();
      });
      item.append(button);
      list.append(item);
    }
  }

  async function refresh(reset = true) {
    if (disabled || loading || (!reset && !cursor)) return;
    const request = ++generation;
    loading = true; error = null; render();
    try {
      const page = await fetchJson(`/api/runs?limit=10${!reset && cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`);
      if (request !== generation) return;
      if (!Array.isArray(page.runs) || page.runs.length > 20) throw new Error("InvalidHistoryPage");
      const next = reset ? page.runs : [...runs, ...page.runs];
      runs = [...new Map(next.map((run) => [run.id, run])).values()].slice(0, 100);
      cursor = runs.length >= 100 ? null : page.next_cursor || null;
      loaded = true;
    } catch { if (request === generation) error = "HistoryReadFailed"; }
    finally { if (request === generation) { loading = false; render(); } }
  }
  refreshButton.addEventListener("click", () => refresh(true));
  moreButton.addEventListener("click", () => refresh(false));
  return {
    refresh, render,
    setDisabled(value) { disabled = value; render(); },
  };
}
