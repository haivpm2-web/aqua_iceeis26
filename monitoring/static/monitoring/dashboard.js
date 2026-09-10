"use strict";
const page = document.body.dataset.page;
const $ = (id) => document.getElementById(id);
const units = { do: "mg/L", ph: "pH", tds: "ppm", temperature: "°C" };
const names = {
  do: "Dissolved oxygen",
  ph: "pH",
  tds: "Total dissolved solids",
  temperature: "Water temperature",
};
const charts = {};
let busy = false;
const fmt = (v) =>
  v === null || v === undefined
    ? "N/A"
    : typeof v === "number"
      ? Number.isInteger(v)
        ? String(v)
        : v.toPrecision(5)
      : String(v);
const escapeHTML = (v) =>
  fmt(v).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const label = (s) => s.replaceAll("_", " ");
function timeQuery() {
  const q = new URLSearchParams();
  for (const k of ["start", "end"])
    if ($(k).value) q.set(k, new Date($(k).value).toISOString());
  return q.toString();
}
async function get(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(data));
  return data;
}
function table(headers, rows) {
  return `<table><thead><tr>${headers.map((h) => `<th>${escapeHTML(h)}</th>`).join("")}</tr></thead><tbody>${rows.length ? rows.map((row) => `<tr>${row.map((v) => `<td>${escapeHTML(v)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}">Awaiting experimental data</td></tr>`}</tbody></table>`;
}
function panel(title, html) {
  return `<section class="panel"><h2>${escapeHTML(title)}</h2>${html}</section>`;
}
function flatten(object, prefix = "") {
  return Object.entries(object || {}).flatMap(([key, value]) =>
    value !== null && typeof value === "object"
      ? flatten(value, prefix + label(key) + " / ")
      : [[prefix + label(key), value]],
  );
}
function metricPanel(title, object) {
  return panel(title, table(["Metric", "Value"], flatten(object)));
}
function card(title, value, detail) {
  return `<article class="card"><small>${escapeHTML(title)}</small><div class="value">${escapeHTML(value)}</div><small>${escapeHTML(detail)}</small></article>`;
}
function makeCharts() {
  if (
    !["dashboard", "live", "detail", "paper", "analysis", "fpga"].includes(page)
  )
    return;
  const sensors = page === "fpga" ? [] : Object.keys(units);
  for (const sensor of [...sensors, "diagnostics"]) {
    const article = document.createElement("article");
    article.className = "chart-panel";
    article.innerHTML = `<div class="chart-heading"><h2>${escapeHTML(names[sensor] || "Adaptive filter diagnostics")}</h2><button type="button">PNG</button></div><div class="chart-wrap"><canvas aria-label="${escapeHTML(names[sensor] || "FPGA diagnostics")} time series" role="img"></canvas></div>`;
    $("charts").append(article);
    const diagnostic = sensor === "diagnostics";
    const datasets = diagnostic
      ? ["Noise estimate", "Adaptive threshold", "Alpha value"].map(
          (name, i) => ({
            label: name,
            data: [],
            borderColor: ["#087f8c", "#bd691b", "#7855ad"][i],
            yAxisID: i === 2 ? "alpha" : "y",
          }),
        )
      : [
          { label: "Raw", data: [], borderColor: "#96a6b7" },
          { label: "FPGA filtered", data: [], borderColor: "#087f8c" },
        ];
    datasets.forEach((d) =>
      Object.assign(d, { borderWidth: 1.6, pointRadius: 0, spanGaps: false }),
    );
    charts[sensor] = new Chart(article.querySelector("canvas"), {
      type: "line",
      data: { labels: [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        normalized: true,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { position: "bottom" },
          tooltip: {
            callbacks: {
              afterBody: (items) => {
                const row = charts[sensor].sampleRows?.[items[0]?.dataIndex];
                return row
                  ? `State: ${row.signal_state}; quality: ${row.quality_flag}; outlier: ${row.outlier_detected}`
                  : "";
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "Timestamp (UTC)" },
            ticks: {
              maxTicksLimit: 6,
              maxRotation: 0,
              callback: function (value) {
                return this.getLabelForValue(value).slice(11, 23);
              },
            },
          },
          y: {
            title: {
              display: true,
              text: units[sensor] || "Noise / threshold (device units)",
            },
          },
          ...(diagnostic
            ? {
                alpha: {
                  position: "right",
                  min: 0,
                  max: 1,
                  title: { display: true, text: "Alpha" },
                  grid: { drawOnChartArea: false },
                },
              }
            : {}),
        },
      },
    });
    article.querySelector("button").onclick = () => {
      const a = document.createElement("a");
      a.download = `${$("run").value}-${sensor}-${$("source").dataset.source}.png`;
      a.href = charts[sensor].toBase64Image();
      a.click();
    };
  }
}
function updateCharts(rows) {
  for (const [sensor, chart] of Object.entries(charts)) {
    chart.sampleRows = rows;
    chart.data.labels = rows.map((r) => r.timestamp);
    const keys =
      sensor === "diagnostics"
        ? ["noise_estimate", "adaptive_threshold", "alpha_value"]
        : [sensor + "_raw", sensor + "_filtered"];
    keys.forEach(
      (key, i) =>
        (chart.data.datasets[i].data = rows.map((r) =>
          r.packet_valid && r.packet_crc_ok !== false ? r[key] : null,
        )),
    );
    chart.data.datasets[0].pointRadius = rows.map((r) =>
      r.outlier_detected || r.transient_detected ? 3 : 0,
    );
    chart.data.datasets[0].pointBackgroundColor = rows.map((r) =>
      r.outlier_detected ? "#c24738" : "#b27815",
    );
    chart.options.plugins.title = {
      display: true,
      text: `${$("source").dataset.source} · Run ${$("run").value} · ${rows.length} displayed samples (UTC)`,
      font: { size: 10 },
    };
    chart.update();
  }
}
async function renderRuns(runPage = 1) {
  const response = await get(`/api/v1/runs/?limit=20&page=${runPage}`);
  let html = panel(
    "Experiment runs",
    table(
      [
        "ID",
        "Name",
        "Type / source",
        "Date",
        "Samples",
        "Duration (s)",
        "DO SD reduction %",
        "pH SD reduction %",
        "Latency (µs)",
        "Status",
      ],
      response.results.map((r) => [
        r.id,
        r.run_name,
        `${r.run_type} / ${r.source}`,
        r.started_at,
        "Loading",
        "Loading",
        "Loading",
        "Loading",
        "Loading",
        r.status,
      ]),
    ),
  );
  $("content").innerHTML = html;
  const trs = $("content").querySelectorAll("tbody tr");
  for (let i = 0; i < response.results.length; i++) {
    const r = response.results[i];
    let s;
    try {
      s = await get(`/api/v1/runs/${r.id}/summary/`);
    } catch (e) {
      s = null;
    }
    if (s) {
      const vals = [
        s.sample_count,
        s.duration_s,
        s.sensors.do.sd_reduction_percent,
        s.sensors.ph.sd_reduction_percent,
        s.latency.mean,
      ];
      vals.forEach((v, j) => (trs[i].children[j + 4].textContent = fmt(v)));
    } else {
      for (let j = 4; j < 9; j++)
        trs[i].children[j].textContent = "Select analysis interval";
    }
    const td = document.createElement("td");
    td.innerHTML = `<a href="/runs/${r.id}/">View / Analyze</a><a href="/api/v1/runs/${r.id}/export/">CSV</a><a href="/runs/${r.id}/paper/">Paper</a>`;
    trs[i].append(td);
  }
  $("content").insertAdjacentHTML(
    "beforeend",
    `<p>Page ${runPage} · ${response.count} experiments <button id="runs-prev" ${runPage === 1 ? "disabled" : ""}>Previous</button> <button id="runs-next" ${response.next_page ? "" : "disabled"}>Next</button></p>`,
  );
  $("runs-prev").onclick = () => renderRuns(runPage - 1).catch(showError);
  $("runs-next").onclick = () => renderRuns(runPage + 1).catch(showError);
}
async function renderCompare() {
  const runs = await get("/api/v1/runs/?limit=500");
  $("content").innerHTML = panel(
    "Compare 2–5 experiments",
    `<label>Hold Ctrl / Cmd to select multiple runs<select multiple id="compare-runs" size="8">${runs.results.map((r) => `<option value="${r.id}">${escapeHTML(r.run_name)} · ${escapeHTML(r.source)} · ${escapeHTML(r.filter_version)}</option>`).join("")}</select></label><button id="compare-button">Analyze selection</button><div id="comparison"></div>`,
  );
  $("compare-button").onclick = async () => {
    try {
      const ids = Array.from($("compare-runs").selectedOptions).map(
        (o) => o.value,
      );
      if (ids.length < 2 || ids.length > 5) throw new Error("Select 2–5 runs.");
      const summaries = await Promise.all(
        ids.map((id) => get(`/api/v1/runs/${id}/summary/`)),
      );
      const rows = [];
      for (const s of summaries)
        for (const sensor of ["do", "ph"]) {
          const m = s.sensors[sensor];
          rows.push([
            s.run_id,
            s.source,
            s.filter_version,
            sensor,
            m.raw.sd,
            m.filtered.sd,
            m.sd_reduction_percent,
            m.raw.mad,
            m.filtered.mad,
            m.filtered_error.rmse,
            m.snr.improvement_db,
            s.outliers.f1,
            s.latency.mean,
            s.latency.throughput_samples_s,
          ]);
        }
      $("comparison").innerHTML = table(
        [
          "Run",
          "Source",
          "Method",
          "Sensor",
          "Raw SD",
          "Filtered SD",
          "SD reduction %",
          "Raw MAD",
          "Filtered MAD",
          "RMSE",
          "Δ-SNR",
          "Spike F1",
          "Latency µs",
          "Samples/s",
        ],
        rows,
      );
    } catch (e) {
      showError(e);
    }
  };
}
function showError(error) {
  $("error").hidden = false;
  $("error").textContent = error.message;
}
async function refresh() {
  if (busy) return;
  busy = true;
  $("error").hidden = true;
  try {
    const status = await get("/api/v1/status/");
    $("connection").textContent = status.online
      ? "Receiving packets"
      : "No recent packets";
    if (page === "system") {
      $("content").innerHTML = metricPanel("System status", status);
      return;
    }
    if (page === "compare") return;
    const id = $("run").value;
    if (!id) {
      $("cards").innerHTML = card(
        "No experiment selected",
        "Awaiting data",
        "Create an experiment through Admin or the API.",
      );
      return;
    }
    const run = await get(`/api/v1/runs/${id}/`);
    $("source").textContent =
      `${run.source} · ${run.run_name} · ${run.run_type} · ${run.filter_version || "Filter version unspecified"}${run.source === "SIMULATED" ? " — Interface testing only; not experimental evidence" : ""}${timeQuery() ? " · Selected time interval" : ""}`;
    $("source").dataset.source = run.source;
    $("source").textContent +=
      ` · ${run.status}${run.dataset_sha256 ? " · SHA256 " + run.dataset_sha256.slice(0, 12) + "…" : ""}`;
    $("research-package").href = `/api/v1/runs/${id}/research-package/`;
    $("research-package").hidden = !["COMPLETED", "LOCKED"].includes(
      run.status,
    );
    $("source").classList.toggle("simulated", run.source === "SIMULATED");
    $("csv").href = `/api/v1/runs/${id}/export/?${timeQuery()}`;
    $("csv").hidden = false;
    $("tables-csv").href =
      `/api/v1/runs/${id}/tables/?download=csv&${timeQuery()}`;
    $("tables-csv").hidden = false;
    if (page === "runs") return;
    if (page === "events") {
      const filter = $("event-type")?.value || "";
      const events = await get(
        `/api/v1/events/?run_id=${id}&event_type=${encodeURIComponent(filter)}&limit=1000`,
      );
      if (!$("event-type")) {
        $("content").innerHTML = panel(
          "Quality and ground-truth event timeline",
          '<label>Event type<select id="event-type"><option value="">All</option><option>SPIKE</option><option>NOISY</option><option>TRANSIENT</option><option>SENSOR_FAULT</option><option>PACKET_FAULT</option><option>STEP</option></select></label><div id="event-table"></div>',
        );
        $("event-type").onchange = refresh;
      }
      $("event-table").innerHTML = table(
        [
          "Timestamp",
          "Sensor",
          "Event",
          "Raw",
          "Filtered",
          "Threshold",
          "State",
          "Run",
        ],
        events.results.map((e) => [
          e.timestamp,
          e.sensor || "Packet / shared",
          e.event_type,
          e.raw_value,
          e.filtered_value,
          e.threshold,
          e.state,
          e.run,
        ]),
      );
      return;
    }
    const [latest, summary, history] = await Promise.all([
      get(`/api/v1/latest/?run_id=${id}&${timeQuery()}`),
      get(`/api/v1/runs/${id}/summary/?${timeQuery()}`),
      get(
        `/api/v1/history/?run_id=${id}&${$("scope").value === "all" ? "downsample" : "limit"}=${$("window").value}&${timeQuery()}`,
      ),
    ]);
    const s = latest.sample || {};
    $("cards").innerHTML =
      Object.keys(units)
        .map((sensor) =>
          card(
            names[sensor],
            `${fmt(s[sensor + "_filtered"] ?? s[sensor + "_raw"])} ${units[sensor]}`,
            `Raw ${fmt(s[sensor + "_raw"])} · Filtered ${fmt(s[sensor + "_filtered"])} · ${latest.sensor_health[sensor]}`,
          ),
        )
        .join("") +
      card(
        "FPGA processing",
        `${fmt(s.fpga_latency_us)} µs`,
        `${s.signal_state || "UNKNOWN"} · ${s.quality_flag || "N/A"}`,
      ) +
      card(
        "Packets",
        summary.communication.received,
        `${summary.communication.valid} valid / ${summary.communication.invalid} invalid`,
      ) +
      card(
        "Packet success",
        `${fmt(summary.communication.success_percent)}%`,
        "Denominator: received packets",
      ) +
      card(
        "Experiment duration",
        `${fmt(summary.duration_s)} s`,
        `Latest ${s.timestamp || "N/A"}`,
      );
    updateCharts(history.results);
    if (page === "dashboard" || page === "live") {
      $("content").innerHTML = panel(
        "Denoising overview",
        table(
          [
            "Sensor",
            "Raw SD",
            "Filtered SD",
            "SD reduction %",
            "MAD reduction %",
          ],
          ["do", "ph"].map((sensor) => {
            const m = summary.sensors[sensor];
            return [
              names[sensor],
              m.raw.sd,
              m.filtered.sd,
              m.sd_reduction_percent,
              m.mad_reduction_percent,
            ];
          }),
        ),
      );
      return;
    }
    let html = "";
    if (page === "detail") html += metricPanel("Experiment metadata", run);
    if (["analysis", "detail"].includes(page)) {
      for (const sensor of ["do", "ph"])
        html += metricPanel(
          `${names[sensor]} · ${units[sensor]}`,
          summary.sensors[sensor],
        );
      html +=
        metricPanel("Outlier detection", summary.outliers) +
        metricPanel(
          "Dynamic response",
          summary.dynamic.length
            ? summary.dynamic
            : {
                status:
                  "Awaiting STEP event with initial, target, settling_band and hold_seconds",
              },
        ) +
        metricPanel("Fixed-point verification", summary.fixed_point);
    }
    if (["fpga", "analysis", "detail"].includes(page))
      html +=
        metricPanel("FPGA runtime · latency in µs", summary.latency) +
        metricPanel("Adaptive filter state", {
          signal_state: s.signal_state,
          quality_flag: s.quality_flag,
          alpha_value: s.alpha_value,
          alpha_code: s.alpha_code,
          adaptive_threshold: s.adaptive_threshold,
          noise_estimate: s.noise_estimate,
          processed_valid_samples: summary.analysis_count,
        }) +
        metricPanel(
          "Vivado synthesis",
          summary.implementation || {
            status:
              "Awaiting experimental data; enter real values in Admin → FPGA implementations",
          },
        ) +
        metricPanel("Communication quality", summary.communication);
    if (page === "paper") {
      const tables = await get(`/api/v1/runs/${id}/tables/?${timeQuery()}`);
      for (const [key, t] of Object.entries(tables))
        html += panel(`Table ${key} · ${t.title}`, table(t.headers, t.rows));
      html += metricPanel("Signal / outlier summary", {
        signal_state: s.signal_state,
        quality_flag: s.quality_flag,
        transient_count: summary.transient_count,
        ...summary.outliers,
      });
    }
    $("content").innerHTML = html;
  } catch (e) {
    showError(e);
    $("connection").textContent = "Update failed";
  } finally {
    busy = false;
  }
}
async function submitForm(form, url, multipart = false) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
      ...(!multipart ? { "Content-Type": "application/json" } : {}),
    },
    body: multipart
      ? new FormData(form)
      : JSON.stringify(
          Object.fromEntries(
            Array.from(new FormData(form)).filter(
              ([k]) => k !== "csrfmiddlewaretoken",
            ),
          ),
        ),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(result));
  return result;
}
document
  .querySelectorAll("nav a")
  .forEach((a) =>
    a.classList.toggle("active", a.pathname === location.pathname),
  );
const queryRun = new URLSearchParams(location.search).get("run_id");
if (queryRun) $("run").value = queryRun;
if (!$("run").value && $("run").options.length > 1) $("run").selectedIndex = 1;
if (page === "paper") {
  $("scope").value = "all";
  $("window").value = "1000";
}
$("refresh").onclick = refresh;
$("run").onchange = refresh;
$("window").onchange = refresh;
$("scope").onchange = refresh;
$("start").onchange = refresh;
$("end").onchange = refresh;
if ($("print")) $("print").onclick = () => window.print();
if ($("lock-run"))
  $("lock-run").onsubmit = async (event) => {
    event.preventDefault();
    try {
      await submitForm(event.target, `/api/v1/runs/${$("run").value}/lock/`);
      await refresh();
    } catch (e) {
      showError(e);
    }
  };
if ($("create-run"))
  $("create-run").onsubmit = async (event) => {
    event.preventDefault();
    try {
      const result = await submitForm(event.target, "/api/v1/runs/");
      location.href = `/runs/${result.id}/`;
    } catch (e) {
      showError(e);
    }
  };
if ($("import-csv"))
  $("import-csv").onsubmit = async (event) => {
    event.preventDefault();
    try {
      if (!$("run").value) throw new Error("Select an experiment first.");
      const result = await submitForm(
        event.target,
        `/api/v1/runs/${$("run").value}/import/`,
        true,
      );
      $("import-report").textContent = JSON.stringify(result, null, 2);
      await refresh();
    } catch (e) {
      showError(e);
    }
  };
try {
  makeCharts();
  if (page === "runs") renderRuns().catch(showError);
  if (page === "compare") renderCompare().catch(showError);
  refresh();
  if (!["paper", "runs", "compare"].includes(page)) setInterval(refresh, 5000);
} catch (e) {
  showError(e);
}
