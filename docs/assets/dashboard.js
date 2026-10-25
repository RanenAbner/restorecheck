// RestoreCheck dashboard: renders docs/data/runs.json (exported by scripts/export_runs.py).
(function () {
  "use strict";

  const CHECKS = [
    ["instance_available", "Instance available", "The restore produced a working database"],
    ["connect", "Connect", "Login works (IAM token over TLS)"],
    ["tables_present", "Tables present", "Every expected table exists"],
    ["row_counts", "Row counts", "Each table has enough rows"],
    ["canary_checksum", "Canary checksum", "100 known rows are byte-for-byte unchanged"],
    ["test_queries", "Test queries", "The data fits together (no orphaned rows)"],
  ];
  const SCENARIOS = {
    healthy: "Intact backup: should pass every check",
    "missing-table": "Backup taken after a table was dropped",
    "truncated-table": "Backup taken after most rows of a table were deleted",
    "corrupt-data": "Backup taken after one value was changed (row counts unchanged)",
    "orphaned-rows": "Backup with broken links between tables",
    "no-backup": "A database that has never been backed up",
    manual: "Verification of the newest backup",
  };
  const STATUS = {
    PASSED: { cls: "is-passed", label: "Passed", verdict: "Backup verified" },
    FAILED: { cls: "is-failed", label: "Failed", verdict: "Backup failed verification" },
    ERROR: { cls: "is-error", label: "Error", verdict: "Verification could not run" },
  };

  const $ = (id) => document.getElementById(id);
  const state = { runs: [], db: "", status: "ALL", exportedAt: null };

  // ------------------------------------------------------------ helpers
  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }
  const toDate = (iso) => new Date(iso);
  const fmtDateTime = (iso) =>
    toDate(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  const fmtShortDate = (iso) => toDate(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const fmtTime = (iso) => toDate(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const minutes = (s) => (s == null ? null : s / 60);
  const fmtMin = (s) => (s == null ? "–" : s < 60 ? Math.round(s) + " s" : (s / 60).toFixed(1) + " min");
  const fmtRowTime = (iso) =>
    toDate(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const tzName = () => {
    const part = new Intl.DateTimeFormat(undefined, { timeZoneName: "short" }).formatToParts(new Date())
      .find((p) => p.type === "timeZoneName");
    return part ? part.value : "local time";
  };
  const median = (xs) => {
    if (!xs.length) return null;
    const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  };
  const statusOf = (run) => STATUS[run.status] || STATUS.ERROR;
  const checkName = (name) => (CHECKS.find((c) => c[0] === name) || [name, name])[1];

  // Status glyph in a filled circle; "none" = check never ran.
  function icon(kind, label) {
    const glyph = {
      passed: '<path d="m7.5 12.3 3 3 6-6.3" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>',
      failed: '<path d="m8.5 8.5 7 7m0-7-7 7" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>',
      error: '<path d="M12 7v6" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/><circle cx="12" cy="16.6" r="1.4" fill="#fff"/>',
      none: '<path d="M8 12h8" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>',
    }[kind];
    const fill = { passed: "var(--good)", failed: "var(--critical)", error: "var(--serious)", none: "var(--none)" }[kind];
    return `<svg class="status-icon" viewBox="0 0 24 24" role="img" aria-label="${esc(label || kind)}"><circle cx="12" cy="12" r="11" fill="${fill}"/>${glyph}</svg>`;
  }
  const runIcon = (run) => icon(run.status === "PASSED" ? "passed" : run.status === "FAILED" ? "failed" : "error", statusOf(run).label);
  const badge = (run) => `<span class="badge ${statusOf(run).cls}">${runIcon(run)}${esc(statusOf(run).label)}</span>`;
  const teardownText = (run) => (run.teardown_ok === true ? "Deleted" : run.teardown_ok === false ? "NOT deleted" : "None created");

  // ------------------------------------------------------------ tooltip
  const tip = $("tooltip");
  function showTip(html, x, y) {
    tip.innerHTML = html;
    tip.classList.add("show");
    const r = tip.getBoundingClientRect();
    let left = x + 14, top = y + 14;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (top + r.height > window.innerHeight - 8) top = y - r.height - 14;
    tip.style.left = Math.max(8, left) + "px";
    tip.style.top = Math.max(8, top) + "px";
  }
  const hideTip = () => tip.classList.remove("show");
  function bindTip(el, html) {
    el.addEventListener("mousemove", (e) => showTip(html, e.clientX, e.clientY));
    el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focus", () => {
      const r = el.getBoundingClientRect();
      showTip(html, r.right, r.top);
    });
    el.addEventListener("blur", hideTip);
  }
  const runTipTitle = (run) => `<div class="tt-title">${esc(fmtDateTime(run.run_timestamp))}</div>`;

  // ------------------------------------------------------------ filters
  const byDb = () => state.runs.filter((r) => !state.db || r.source_db_id === state.db);
  const filtered = () => byDb().filter((r) => state.status === "ALL" || r.status === state.status);

  function renderFilters() {
    const dbs = [...new Set(state.runs.map((r) => r.source_db_id))].sort();
    const select = $("db-filter");
    select.innerHTML = '<option value="">All databases</option>' +
      dbs.map((d) => `<option value="${esc(d)}"${d === state.db ? " selected" : ""}>${esc(d)}</option>`).join("");
    renderChips();
  }
  function renderChips() {
    const runs = byDb();
    const options = [["ALL", "All runs"], ["PASSED", "Passed"], ["FAILED", "Failed"], ["ERROR", "Error"]];
    $("status-filter").innerHTML = options.map(([value, label]) => {
      const count = value === "ALL" ? runs.length : runs.filter((r) => r.status === value).length;
      return `<button type="button" class="chip" data-status="${value}" aria-pressed="${state.status === value}">${esc(label)} <span class="count">${count}</span></button>`;
    }).join("");
  }

  // ------------------------------------------------------------ overview
  function renderOverview() {
    const runs = byDb();
    const latest = runs[runs.length - 1];
    const card = $("latest");
    if (!latest) {
      card.className = "card latest is-none";
      card.innerHTML = '<div class="eyebrow">Latest run</div><div class="muted">No runs recorded.</div>';
      $("tiles").innerHTML = "";
      return;
    }
    const s = statusOf(latest);
    card.className = `card latest ${s.cls}`;
    card.innerHTML = `
      <div class="eyebrow">Latest run</div>
      <div class="verdict">${runIcon(latest)}<span>${esc(s.verdict)}</span></div>
      <dl>
        <dt>When</dt><dd>${esc(fmtDateTime(latest.run_timestamp))}</dd>
        <dt>Database</dt><dd class="mono">${esc(latest.source_db_id)}</dd>
        <dt>Backup</dt><dd class="mono">${esc(latest.snapshot_id || "none found")}</dd>
        <dt>Checks</dt><dd>${latest.checks_passed} of ${latest.checks_total || CHECKS.length} passed</dd>
        <dt>Restore time</dt><dd>${esc(fmtMin(latest.restore_seconds))}</dd>
        <dt>Temporary copy</dt><dd>${esc(teardownText(latest))}</dd>
      </dl>
      <div><button type="button" class="chip" data-open="${esc(latest.run_timestamp)}|${esc(latest.source_db_id)}">View full report</button></div>`;

    const count = (st) => runs.filter((r) => r.status === st).length;
    const restores = runs.map((r) => r.restore_seconds).filter((x) => x != null);
    const created = runs.filter((r) => r.teardown_ok !== null);
    const lastPass = [...runs].reverse().find((r) => r.status === "PASSED");
    const med = median(restores);
    const tiles = [
      ["Runs recorded", `${runs.length}`, `${fmtShortDate(runs[0].run_timestamp)} to ${fmtShortDate(latest.run_timestamp)}`],
      ["Results", null, null, `<div class="split"><span>${icon("passed", "Passed")}${count("PASSED")} passed</span><span>${icon("failed", "Failed")}${count("FAILED")} failed</span><span>${icon("error", "Error")}${count("ERROR")} error</span></div><div class="sub">Failed backups were broken on purpose to test the checks</div>`],
      ["Median restore time", med == null ? "–" : `${(med / 60).toFixed(1)}<small>min</small>`, restores.length ? `range ${(Math.min(...restores) / 60).toFixed(1)} to ${(Math.max(...restores) / 60).toFixed(1)} min` : "no restores"],
      ["Temporary copies deleted", `${created.filter((r) => r.teardown_ok).length}/${created.length}`, "every run that created one"],
      ["Last verified backup", lastPass ? fmtShortDate(lastPass.run_timestamp) : "–", lastPass ? `${fmtTime(lastPass.run_timestamp)} · all ${CHECKS.length} checks passed` : "no passing run"],
      ["Alerts sent", `${runs.filter((r) => r.status !== "PASSED" || r.teardown_ok === false).length}`, "email for every failed or errored run"],
    ];
    $("tiles").innerHTML = tiles.map(([label, value, sub, html]) => `
      <div class="card tile">
        <div class="label">${esc(label)}</div>
        ${value != null ? `<div class="value">${value}</div>` : ""}
        ${html || ""}
        ${sub ? `<div class="sub">${esc(sub)}</div>` : ""}
      </div>`).join("");
  }

  // ------------------------------------------------------------ restore-time chart
  function renderRestoreChart() {
    const host = $("restore-chart");
    const runs = filtered();
    if (!runs.length) { host.innerHTML = '<div class="empty">No runs match the filters.</div>'; return; }
    const W = Math.max(320, host.clientWidth), H = 280;
    const m = { l: 40, r: 12, t: 22, b: 64 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const values = runs.map((r) => minutes(r.restore_seconds)).filter((v) => v != null);
    const yMax = Math.max(2, Math.ceil(((values.length ? Math.max(...values) : 0) * 1.15) / 2) * 2);
    const y = (v) => m.t + ih - (v / yMax) * ih;
    const band = iw / runs.length;
    const barW = Math.max(6, Math.min(40, band * 0.55));
    const labelEvery = Math.ceil(runs.length / Math.max(1, Math.floor(iw / 64)));

    let svg = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Restore time in minutes for each run">`;
    for (let v = 0; v <= yMax; v += yMax <= 12 ? 2 : Math.ceil(yMax / 6)) {
      svg += `<line class="${v ? "grid-line" : "axis-line"}" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
      svg += `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    }
    let lastDate = "";
    runs.forEach((run, i) => {
      const cx = m.l + band * (i + 0.5);
      const v = minutes(run.restore_seconds);
      const label = `${fmtDateTime(run.run_timestamp)}: ${statusOf(run).label}, restore ${fmtMin(run.restore_seconds)}`;
      svg += `<rect class="bar-hit" x="${m.l + band * i}" y="${m.t}" width="${band}" height="${ih}" tabindex="0" role="button" aria-label="${esc(label)}" data-i="${i}"/>`;
      if (v != null) {
        const top = y(v), h = m.t + ih - top, r = Math.min(4, barW / 2, h);
        // Rounded data end, square at the baseline.
        svg += `<path class="bar" d="M${cx - barW / 2},${m.t + ih} V${top + r} Q${cx - barW / 2},${top} ${cx - barW / 2 + r},${top} H${cx + barW / 2 - r} Q${cx + barW / 2},${top} ${cx + barW / 2},${top + r} V${m.t + ih} Z"/>`;
      } else {
        svg += `<text class="no-data" x="${cx}" y="${m.t + ih - 8}" text-anchor="middle">no restore</text>`;
      }
      // Status strip under the axis, then the time and (when it changes) the date.
      const kind = run.status === "PASSED" ? "passed" : run.status === "FAILED" ? "failed" : "error";
      svg += `<g transform="translate(${cx - 8},${m.t + ih + 8})">${icon(kind, statusOf(run).label).replace('class="status-icon"', 'width="16" height="16"')}</g>`;
      if (i % labelEvery === 0) {
        svg += `<text x="${cx}" y="${m.t + ih + 40}" text-anchor="middle">${esc(fmtTime(run.run_timestamp))}</text>`;
        const d = fmtShortDate(run.run_timestamp);
        if (d !== lastDate) {
          svg += `<text x="${cx}" y="${m.t + ih + 55}" text-anchor="middle" style="font-weight:600">${esc(d)}</text>`;
          lastDate = d;
        }
      }
    });
    const med = median(values);
    if (med != null && values.length > 1) {
      svg += `<line class="ref-line" x1="${m.l}" x2="${W - m.r}" y1="${y(med)}" y2="${y(med)}"/>`;
      svg += `<text class="ref-label" x="${W - m.r}" y="${y(med) - 6}" text-anchor="end">median ${med.toFixed(1)} min</text>`;
    }
    svg += "</svg>";
    host.innerHTML = svg;

    host.querySelectorAll(".bar-hit").forEach((el) => {
      const run = runs[+el.dataset.i];
      bindTip(el, `${runTipTitle(run)}
        <div class="tt-row">${esc(run.scenario)} · ${esc(run.source_db_id)}</div>
        <div class="tt-row">Result: <strong>${esc(statusOf(run).label)}</strong> · checks ${run.checks_passed}/${run.checks_total || CHECKS.length}</div>
        <div class="tt-row">Restore time: ${esc(fmtMin(run.restore_seconds))}</div>`);
      el.addEventListener("click", () => openDetails(run));
      el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetails(run); } });
    });
  }

  // ------------------------------------------------------------ check matrix
  function renderMatrix() {
    const runs = [...filtered()].reverse();
    const host = $("matrix");
    if (!runs.length) { host.innerHTML = '<div class="empty">No runs match the filters.</div>'; return; }
    let html = '<table class="matrix"><thead><tr><th class="run-col" scope="col">Run</th>' +
      CHECKS.map(([, label]) => `<th scope="col">${esc(label)}</th>`).join("") + "</tr></thead><tbody>";
    runs.forEach((run, i) => {
      html += `<tr><td class="run-label"><strong>${esc(fmtShortDate(run.run_timestamp))} ${esc(fmtTime(run.run_timestamp))}</strong> · ${esc(run.scenario)}</td>`;
      CHECKS.forEach(([name], j) => {
        const c = (run.checks || []).find((x) => x.name === name);
        const kind = !c ? "none" : c.passed ? "passed" : "failed";
        const cls = { none: "is-none", passed: "is-passed", failed: "is-failed" }[kind];
        const text = { none: "not run", passed: "passed", failed: "failed" }[kind];
        html += `<td class="cell ${cls}" tabindex="0" data-i="${i}" data-j="${j}" aria-label="${esc(checkName(name))}: ${text}">${icon(kind, text)}</td>`;
      });
      html += "</tr>";
    });
    host.innerHTML = html + "</tbody></table>";
    host.querySelectorAll(".cell").forEach((el) => {
      const run = runs[+el.dataset.i];
      const [name, label, about] = CHECKS[+el.dataset.j];
      const c = (run.checks || []).find((x) => x.name === name);
      const detail = c ? c.detail : run.status === "ERROR" ? "Not run: nothing was restored (" + (run.error || "pipeline error") + ")" : "Not recorded";
      bindTip(el, `<div class="tt-title">${esc(label)}: ${c ? (c.passed ? "passed" : "FAILED") : "not run"}</div>
        <div class="tt-row">${esc(about)}</div>
        <div class="tt-row" style="margin-top:4px">${esc(detail)}</div>
        <div class="tt-row muted" style="margin-top:4px">${esc(fmtDateTime(run.run_timestamp))} · ${esc(run.scenario)}</div>`);
    });
    host.querySelectorAll("td.run-label").forEach((el, i) => {
      el.style.cursor = "pointer";
      el.addEventListener("click", () => openDetails(runs[i]));
    });
    $("matrix-legend").innerHTML =
      `<span>${icon("passed")}Passed</span><span>${icon("failed")}Failed</span><span>${icon("none")}Not run (nothing was restored)</span>`;
  }

  // ------------------------------------------------------------ run table
  function renderRuns() {
    const runs = [...filtered()].reverse();
    const host = $("runs");
    if (!runs.length) { host.innerHTML = '<div class="empty">No runs match the filters.</div>'; return; }
    host.innerHTML = `<table class="runs"><thead><tr>
        <th scope="col">Time (${esc(tzName())})</th><th scope="col">Scenario</th><th scope="col">Database</th><th scope="col">Result</th>
        <th scope="col">Checks</th><th scope="col">Restore</th><th scope="col">Run length</th><th scope="col">Temporary copy</th>
      </tr></thead><tbody>` +
      runs.map((run, i) => `<tr tabindex="0" data-i="${i}" aria-label="Open report for the run at ${esc(fmtDateTime(run.run_timestamp))}">
        <td class="nowrap">${esc(fmtRowTime(run.run_timestamp))}</td>
        <td class="nowrap"><span class="scenario-name">${esc(run.scenario)}</span></td>
        <td class="mono nowrap">${esc(run.source_db_id)}</td>
        <td>${badge(run)}</td>
        <td class="num">${run.checks_passed}/${run.checks_total || CHECKS.length}</td>
        <td class="num">${esc(fmtMin(run.restore_seconds))}</td>
        <td class="num">${esc(fmtMin(run.total_seconds))}</td>
        <td>${esc(teardownText(run))}</td>
      </tr>`).join("") + "</tbody></table>";
    host.querySelectorAll("tbody tr").forEach((tr) => {
      const run = runs[+tr.dataset.i];
      tr.addEventListener("click", () => openDetails(run));
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDetails(run); } });
    });
  }

  // ------------------------------------------------------------ details dialog
  const dialog = $("details");
  function openDetails(run) {
    hideTip();
    const checks = run.checks || [];
    const fact = (label, value, mono) => `<div><dt>${esc(label)}</dt><dd${mono ? ' class="mono"' : ""}>${esc(value)}</dd></div>`;
    dialog.innerHTML = `
      <div class="details-head">
        <div>
          <h2 id="details-title">${esc(statusOf(run).verdict)}</h2>
          <div>${badge(run)} <span class="muted">${esc(fmtDateTime(run.run_timestamp))}</span></div>
        </div>
        <button type="button" class="close-btn" aria-label="Close">×</button>
      </div>
      <div class="details-body">
        <dl class="facts">
          ${fact("Scenario", `${run.scenario}: ${SCENARIOS[run.scenario] || SCENARIOS.manual}`)}
          ${fact("Database", run.source_db_id, true)}
          ${fact("Backup (snapshot)", run.snapshot_id || "none found", true)}
          ${fact("Backup taken", run.snapshot_time ? fmtDateTime(run.snapshot_time) : "–")}
          ${fact("Temporary copy", run.temp_instance_id ? `${run.temp_instance_id} (${teardownText(run).toLowerCase()})` : "none created", true)}
          ${fact("Restore time", fmtMin(run.restore_seconds))}
          ${fact("Whole run", fmtMin(run.total_seconds))}
          ${fact("Checks passed", `${run.checks_passed} of ${run.checks_total || CHECKS.length}`)}
        </dl>
        ${run.error ? `<div class="error-box"><strong>Error:</strong> ${esc(run.error)}</div>` : ""}
        <h3 style="font-size:0.95rem;margin:0 0 8px">Integrity checks</h3>
        ${checks.length ? `<ul class="check-list">${checks.map((c) => `<li>${icon(c.passed ? "passed" : "failed", c.passed ? "passed" : "failed")}
            <div><div class="name">${esc(checkName(c.name))} <span class="muted mono">${esc(c.name)}</span></div>
            <div class="detail">${esc(c.detail)}</div></div></li>`).join("")}</ul>`
          : `<p class="muted">No checks ran: there was nothing to restore.</p>`}
      </div>`;
    dialog.querySelector(".close-btn").addEventListener("click", () => dialog.close());
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
  }
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });

  // ------------------------------------------------------------ wiring
  function renderAll() {
    renderChips();
    renderOverview();
    renderRestoreChart();
    renderMatrix();
    renderRuns();
  }
  $("db-filter").addEventListener("change", (e) => { state.db = e.target.value; renderAll(); });
  $("status-filter").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-status]");
    if (chip) { state.status = chip.dataset.status; renderAll(); }
  });
  $("latest").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-open]");
    if (!btn) return;
    const [ts, db] = btn.dataset.open.split("|");
    const run = state.runs.find((r) => r.run_timestamp === ts && r.source_db_id === db);
    if (run) openDetails(run);
  });
  let resizeTimer;
  window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderRestoreChart, 120); });

  fetch("data/runs.json", { cache: "no-cache" })
    .then((res) => { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
    .then((data) => {
      state.runs = data.runs || [];
      state.exportedAt = data.exported_at;
      $("data-note").textContent = `${state.runs.length} runs · exported ${fmtDateTime(data.exported_at)}`;
      $("dashboard").hidden = false;
      renderFilters();
      renderAll();
    })
    .catch((err) => {
      $("data-note").textContent = "";
      const box = $("load-error");
      box.hidden = false;
      box.innerHTML = `Could not load the run history (${esc(err.message)}). <a href="data/runs.json">Open the raw data</a>.`;
    });
})();
