/* Live run progress via Server-Sent Events.
 *
 * The progress page sets window.RUN_ID / window.RUN_KIND. On load we connect
 * to /api/progress/{run_id}/stream: the first event is a "snapshot" (current
 * persisted/in-memory state incl. recent events, so a page reload rebuilds the
 * report), followed by live events until the run reaches a terminal state.
 */
(function () {
  "use strict";

  var runId = window.RUN_ID;
  if (!runId) return;

  var statusEl = document.getElementById("run-status");
  var fillEl = document.getElementById("progress-fill");
  var countEl = document.getElementById("progress-count");
  var stepEl = document.getElementById("current-step");
  var logEl = document.getElementById("event-log");
  var iterFillEl = document.getElementById("iteration-fill");
  var iterCountEl = document.getElementById("iteration-count");
  var iterScoreEl = document.getElementById("iteration-score");

  function setStatus(status) {
    if (!status || !statusEl) return;
    statusEl.textContent = status;
    statusEl.className = "status status-" + status;
  }

  function setProgress(executed, total) {
    if (executed == null && total == null) return;
    executed = executed || 0;
    total = total || 0;
    if (countEl) countEl.textContent = executed + " / " + (total || "?") + " steps";
    if (fillEl && total > 0) {
      fillEl.style.width = Math.min(100, Math.round((executed / total) * 100)) + "%";
    }
  }

  function setCurrentStep(text) {
    if (text && stepEl) stepEl.textContent = text;
  }

  /* Iterations card (optimization runs): fed by "iteration_done" events,
   * which carry executed / total as iteration counts plus the current best
   * avg_score. Replayed snapshot events rebuild it on page reload. */
  function setIterations(ev) {
    if (ev.type !== "iteration_done") {
      if (ev.type === "run_completed" && ev.avg_score != null && iterScoreEl) {
        iterScoreEl.textContent = Number(ev.avg_score).toFixed(2);
      }
      return;
    }
    var executed = ev.executed || 0;
    var total = ev.total || 0;
    if (iterCountEl) {
      iterCountEl.textContent = executed + " / " + (total || "?") + " iterations";
    }
    if (iterFillEl && total > 0) {
      iterFillEl.style.width =
        Math.min(100, Math.round((executed / total) * 100)) + "%";
    }
    if (iterScoreEl && ev.avg_score != null) {
      iterScoreEl.textContent = Number(ev.avg_score).toFixed(2);
    }
  }

  function addLogRow(ev) {
    if (!logEl) return;
    var empty = document.getElementById("event-log-empty");
    if (empty) empty.remove();

    var tr = document.createElement("tr");
    var ts = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : "";
    var progress =
      ev.executed != null ? ev.executed + (ev.total != null ? " / " + ev.total : "") : "";
    var score = ev.score != null ? Number(ev.score).toFixed(2)
      : ev.avg_score != null ? Number(ev.avg_score).toFixed(2) : "";
    var detail = ev.message || ev.current_state || ev.test_case_id || "";

    [ts, ev.type || "", progress, score, detail].forEach(function (text, i) {
      var td = document.createElement("td");
      td.textContent = text;
      if (i === 1) {
        var cls = { run_completed: "status-completed", error: "status-failed" }[ev.type];
        if (cls) td.innerHTML = '<span class="status ' + cls + '">' + ev.type + "</span>";
      }
      tr.appendChild(td);
    });
    logEl.appendChild(tr);
  }

  function applyEvent(ev) {
    setProgress(ev.executed, ev.total);
    setCurrentStep(ev.current_state);
    setIterations(ev);
    if (ev.type === "run_completed") setStatus("completed");
    else if (ev.type === "error") setStatus("failed");
    else setStatus("running");
    addLogRow(ev);
  }

  var source = new EventSource("/api/progress/" + runId + "/stream");

  source.addEventListener("snapshot", function (e) {
    var snap = JSON.parse(e.data);
    setStatus(snap.status);
    setProgress(snap.executed, snap.total);
    setCurrentStep(snap.current_state || snap.current_step);
    (snap.events || []).forEach(function (ev) {
      addLogRow(ev);
      setIterations(ev);
    });
    if (snap.status === "completed" || snap.status === "failed") source.close();
  });

  ["step_started", "step_completed", "iteration_done", "run_completed", "error"].forEach(
    function (type) {
      source.addEventListener(type, function (e) {
        var ev = JSON.parse(e.data);
        ev.type = ev.type || type;
        applyEvent(ev);
        if (type === "run_completed" || type === "error") source.close();
      });
    }
  );

  source.onerror = function () {
    // The server closes the stream on terminal runs; nothing to do.
  };
})();
