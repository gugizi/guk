const state = {
  token: localStorage.getItem("okedbmon_token") || "",
  user: null,
  page: "dashboard",
  alias: localStorage.getItem("okedbmon_alias") || "",
  identity: { title: "OKEDBMON", version: "" },
  dashboard: null,
  error: "",
  detailSql: null,
  timer: null,
};

const NAV = [
  ["dashboard", "통합 관제"],
  ["realtime", "실시간"],
  ["history", "세션 이력"],
  ["sql", "SQL Text"],
  ["trend", "성능 추이"],
  ["report", "점검 요약"],
  ["settings", "환경 설정"],
  ["retention", "보관 주기"],
];

const app = document.getElementById("app");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function num(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return n.toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (response.status === 401 && !path.endsWith("/api/login")) {
    logout();
    throw new Error("로그인이 필요합니다.");
  }
  if (!response.ok) {
    const detail = data.detail;
    const message = typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : response.statusText);
    throw new Error(message || "요청을 처리하지 못했습니다.");
  }
  return data;
}

function rememberIdentity(source) {
  if (source?.title) state.identity.title = source.title;
  if (source?.version) state.identity.version = source.version;
}

function versionLabel() {
  return state.identity.version ? `V${state.identity.version}` : "";
}

function productLabel() {
  return `${state.identity.title} ${versionLabel()}`.trim();
}

async function loadIdentity() {
  try {
    rememberIdentity(await fetch("/api/health").then((response) => response.json()));
  } catch (err) {
    // The login screen still works without a version label.
  }
  document.title = productLabel();
}

function logout() {
  state.token = "";
  state.user = null;
  localStorage.removeItem("okedbmon_token");
  clearInterval(state.timer);
  renderLogin();
}

function setAlias(alias) {
  state.alias = alias;
  localStorage.setItem("okedbmon_alias", alias);
}

async function boot() {
  if (!state.token) {
    renderLogin();
    return;
  }
  try {
    state.user = await api("/api/me");
    await showPage(state.page);
    clearInterval(state.timer);
    state.timer = setInterval(() => {
      if (["dashboard", "realtime"].includes(state.page)) showPage(state.page, true);
    }, 5000);
  } catch (err) {
    renderLogin(err.message);
  }
}

function renderLogin(message = "") {
  app.innerHTML = `
    <div class="login">
      <form class="login-card" id="login-form">
        <div class="brand"><div class="mark">O</div><h1>${esc(state.identity.title)}<span class="ver">${esc(versionLabel())}</span></h1></div>
        <p class="sub">DB 수집서버 · Oracle, Tibero, MariaDB, PostgreSQL</p>
        <label>사용자 ID</label>
        <input name="username" autocomplete="username" value="admin" />
        <label>비밀번호</label>
        <input name="password" type="password" autocomplete="current-password" value="okedbmon" />
        <button class="primary" type="submit">로그인</button>
        ${message ? `<div class="error">${esc(message)}</div>` : ""}
        <p class="hint">초기 계정 admin / okedbmon · 에이전트가 5초 주기로 세션과 SQL을 전송합니다.</p>
      </form>
    </div>`;
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    try {
      const data = await api("/api/login", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      state.token = data.token;
      localStorage.setItem("okedbmon_token", data.token);
      boot();
    } catch (err) {
      renderLogin(err.message);
    }
  });
}

const TARGET_PAGES = ["realtime", "history", "sql", "trend", "report"];

function targetList() {
  const filter = (state.targetFilter || "").trim().toLowerCase();
  const instances = state.dashboard?.instances || [];
  const matches = (item) => !filter || [item.agent_alias, item.product, item.host_nm, item.group_nm]
    .some((value) => String(value || "").toLowerCase().includes(filter));
  const groups = {};
  instances.forEach((item) => {
    const key = item.group_nm || "미지정";
    (groups[key] = groups[key] || []).push(item);
  });
  const online = (state.dashboard?.instances || []).filter((item) => item.online).length;
  const total = (state.dashboard?.instances || []).length;
  const body = Object.entries(groups).map(([group, items]) => `
    <div class="target-group" ${items.some(matches) ? "" : "hidden"}>
      <div class="target-group-title">${esc(group)} <span>${items.length}</span></div>
      ${items.map((item) => `
        <button class="target ${item.agent_alias === state.alias ? "selected" : ""}" data-target="${esc(item.agent_alias)}" title="${esc(item.host_nm)}:${esc(item.port)} / ${esc(item.db_name)}" ${matches(item) ? "" : "hidden"}>
          <span class="dot ${item.online ? (item.alerts?.length ? "warn" : "on") : "off"}"></span>
          <span class="target-main">
            <strong>${esc(item.agent_alias)}</strong>
            <span class="product ${esc(item.product)}">${esc(item.product)}</span>
          </span>
          <span class="target-kpi">CPU ${num(item.cpu_usage, 0)}% · Act ${num(item.active_sessions)}${item.lock_wait ? ` · <b>Lock ${num(item.lock_wait)}</b>` : ""}</span>
        </button>`).join("")}
    </div>`).join("");
  return `
    <aside class="targets">
      <div class="targets-head">
        <strong>모니터링 대상</strong>
        <span class="small muted">${online} / ${total} ONLINE</span>
      </div>
      <input id="target-filter" class="target-filter" placeholder="이름, DBMS, 호스트 검색" value="${esc(state.targetFilter || "")}" />
      <div class="target-scroll">${body || `<div class="muted small">대상이 없습니다.</div>`}</div>
    </aside>`;
}

function shell(title, subtitle, body) {
  rememberIdentity(state.dashboard);
  document.title = productLabel();
  const previousScroll = document.querySelector(".target-scroll")?.scrollTop || 0;
  const filterFocused = document.activeElement?.id === "target-filter";
  app.innerHTML = `
    <div class="frame">
      <header class="topbar">
        <div class="brand"><div class="mark">O</div><div class="product-name"><strong>${esc(state.identity.title)}</strong><span class="ver">${esc(versionLabel())}</span></div></div>
        <nav class="menu">
          ${NAV.map(([id, label]) => `<button data-page="${id}" class="${state.page === id ? "active" : ""}">${label}</button>`).join("")}
        </nav>
        <div class="row">
          <span class="small muted">${esc(state.user?.display_name || "")}</span>
          <button class="ghost" id="logout">로그아웃</button>
        </div>
      </header>
      <div class="workspace">
        ${targetList()}
        <section class="main">
          <div class="top">
            <div><h2>${esc(title)}</h2><p>${subtitle}</p></div>
          </div>
          ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
          ${body}
        </section>
      </div>
    </div>`;
  document.getElementById("logout").onclick = logout;
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.onclick = () => showPage(button.dataset.page);
  });
  const scroller = document.querySelector(".target-scroll");
  if (scroller) scroller.scrollTop = previousScroll;
  const filter = document.getElementById("target-filter");
  if (filter) {
    if (filterFocused) {
      filter.focus();
      filter.setSelectionRange(filter.value.length, filter.value.length);
    }
    filter.oninput = () => {
      state.targetFilter = filter.value;
      applyTargetFilter();
    };
  }
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.onclick = () => {
      setAlias(button.dataset.target);
      state.selectedSql = "";
      showPage(TARGET_PAGES.includes(state.page) ? state.page : "realtime");
    };
  });
}

function applyTargetFilter() {
  const filter = (state.targetFilter || "").trim().toLowerCase();
  const byAlias = Object.fromEntries((state.dashboard?.instances || []).map((item) => [item.agent_alias, item]));
  document.querySelectorAll(".target-group").forEach((group) => {
    let shown = 0;
    group.querySelectorAll("[data-target]").forEach((button) => {
      const item = byAlias[button.dataset.target] || {};
      const match = !filter || [item.agent_alias, item.product, item.host_nm, item.group_nm]
        .some((value) => String(value || "").toLowerCase().includes(filter));
      button.hidden = !match;
      if (match) shown += 1;
    });
    group.hidden = shown === 0;
  });
}

function currentTarget() {
  const item = (state.dashboard?.instances || []).find((row) => row.agent_alias === state.alias);
  if (!item) return `<span class="current-target muted">왼쪽 목록에서 대상을 선택하세요.</span>`;
  return `<span class="current-target">
    <span class="dot ${item.online ? "on" : "off"}"></span>
    <strong>${esc(item.agent_alias)}</strong>
    <span class="product ${esc(item.product)}">${esc(item.product)}</span>
    <span class="small muted">${esc(item.host_nm)}:${esc(item.port)} / ${esc(item.db_name)}</span>
  </span>`;
}

let renderSerial = 0;

function beginRender() {
  state.renderSerial = ++renderSerial;
  return state.renderSerial;
}

function stillCurrent(serial) {
  return serial === state.renderSerial;
}

async function showPage(page, silent = false) {
  const serial = beginRender();
  state.page = page;
  if (!silent) state.error = "";
  try {
    if (page === "dashboard") await pageDashboard(serial);
    else if (page === "realtime") await pageRealtime(serial);
    else if (page === "history") await pageHistory(serial);
    else if (page === "sql") await pageSql(serial);
    else if (page === "trend") await pageTrend(serial);
    else if (page === "report") await pageReport(serial);
    else if (page === "settings") await pageSettings(serial);
    else if (page === "retention") await pageRetention(serial);
    if (stillCurrent(serial)) state.error = "";
  } catch (err) {
    if (!stillCurrent(serial)) return;
    state.error = err.message;
    if (!document.querySelector(".frame")) shell("오류", err.message, "");
  }
}

async function ensureDashboard() {
  state.dashboard = await api("/api/dashboard");
  if (!state.alias && state.dashboard.instances.length) setAlias(state.dashboard.instances[0].agent_alias);
}

function aliasOptions(selected) {
  const instances = state.dashboard?.instances || [];
  return instances.map((item) => `<option value="${esc(item.agent_alias)}" ${item.agent_alias === selected ? "selected" : ""}>${esc(item.agent_alias)} · ${esc(item.product)}</option>`).join("");
}

function cardClass(value, warn, bad) {
  if (value === null || value === undefined) return "";
  if (value >= bad) return "bad";
  if (value >= warn) return "warn";
  return "";
}

async function pageDashboard(serial = state.renderSerial) {
  await ensureDashboard();
  if (!stillCurrent(serial)) return;
  const cards = state.dashboard.instances.map((item) => `
    <article class="card ${item.agent_alias === state.alias ? "selected" : ""}" data-alias="${esc(item.agent_alias)}">
      <header>
        <strong>${esc(item.agent_alias)}</strong>
        <span class="product ${esc(item.product)}">${esc(item.product)}</span>
      </header>
      <div class="small muted">${esc(item.host_nm)}:${esc(item.port)} / ${esc(item.db_name)} · ${esc(item.group_nm)}</div>
      <div class="status ${item.online ? "on" : "off"}">${item.online ? "ONLINE" : esc(item.status)} · ${esc(item.last_seen || "수집 대기")}</div>
      <div class="kpis" style="margin-top:10px">
        <div class="kpi ${cardClass(item.cpu_usage, 70, 85)}"><span>CPU</span><strong>${num(item.cpu_usage, 1)}%</strong></div>
        <div class="kpi ${cardClass(item.active_sessions, 20, 40)}"><span>Active</span><strong>${num(item.active_sessions)}</strong></div>
        <div class="kpi ${item.lock_wait ? "bad" : ""}"><span>Lock</span><strong>${num(item.lock_wait)}</strong></div>
        <div class="kpi"><span>Hit</span><strong>${num(item.buffer_cache_ratio, 1)}</strong></div>
      </div>
      <div class="small muted" style="margin-top:8px">접속 ${num(item.connected_sessions)} · TPS ${num(item.tps, 1)} · QPS ${num(item.qps, 1)}</div>
      <div class="alerts">${(item.alerts || []).map((alert) => `<span class="tag">${esc(alert)}</span>`).join("")}</div>
      ${item.message ? `<div class="small muted">${esc(item.message)}</div>` : ""}
    </article>`).join("");
  const events = (state.dashboard.events || []).map((event) => `
    <tr><td>${esc(event.occurred_at)}</td><td>${esc(event.agent_alias)}</td><td>${esc(event.event_nm)}</td><td>${esc(event.message)}</td></tr>`).join("");
  shell("통합 관제", "이기종 DBMS의 CPU, Active Session, Lock, Buffer Hit를 한 화면에서 봅니다.", `
    <div class="grid cards">${cards || `<div class="panel">등록된 인스턴스가 없습니다.</div>`}</div>
    <div class="panel" style="margin-top:12px">
      <header><strong>최근 이벤트</strong><span class="small muted">${esc(state.dashboard.generated_at)}</span></header>
      <table><thead><tr><th>시간</th><th>인스턴스</th><th>항목</th><th>내용</th></tr></thead><tbody>${events || `<tr><td colspan="4" class="muted">임계치를 넘은 이벤트가 없습니다.</td></tr>`}</tbody></table>
    </div>`);
  document.querySelectorAll(".card").forEach((card) => {
    card.onclick = () => {
      setAlias(card.dataset.alias);
      showPage("realtime");
    };
  });
}

async function pageRealtime(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const [sessions, series] = await Promise.all([
    api(`/api/sessions/active?alias=${encodeURIComponent(alias)}`),
    api(`/api/performance?alias=${encodeURIComponent(alias)}`),
  ]);
  if (!stillCurrent(serial)) return;
  const active = sessions.sessions.filter((row) => row.status === "ACTIVE");
  const rows = sessions.sessions.map((row) => `
    <tr class="click" data-sql="${esc(row.sql_text)}">
      <td>${esc(row.sid)}</td><td>${esc(row.status)}</td><td>${esc(row.db_user)}</td>
      <td>${esc(row.program)}</td><td>${esc(row.wait_class)}</td><td>${esc(row.wait_event)}</td>
      <td>${num(row.elapsed_ms)}</td><td>${esc(row.blocking_sid || "")}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 180))}</td>
    </tr>`).join("");
  shell("실시간", `${alias} 현재 세션과 Lock. Active Session은 이 DB 서버의 에이전트에 저장되어 있습니다.`, `
    <div class="toolbar">
      ${currentTarget()}
      <span class="small muted">수집 ${esc(sessions.collect_tm || "-")} · Active ${active.length} / 전체 ${sessions.sessions.length}</span>
    </div>
    <div class="split">
      <div class="panel"><header><strong>Active Session / 접속 세션</strong></header>
        <div style="overflow:auto"><table id="session-table"><thead><tr><th>SID</th><th>상태</th><th>사용자</th><th>프로그램</th><th>Wait Class</th><th>Event</th><th>ms</th><th>Blocker</th><th>SQL</th></tr></thead><tbody>${rows || `<tr><td colspan="9" class="muted">세션이 없습니다.</td></tr>`}</tbody></table></div>
      </div>
      <div class="stack">
        <div class="panel"><header><strong>세션 추이</strong></header>${lineChart(series.series, "active_sessions", "#3dcc97")}</div>
        <div class="panel"><header><strong>Lock Tree</strong></header>${renderLocks(sessions.locks)}</div>
      </div>
    </div>
    <div class="panel" id="sql-preview" style="margin-top:12px"><header><strong>SQL Text</strong></header><div class="sql muted">세션을 선택하면 수행 중인 SQL이 표시됩니다.</div></div>`);
  bindAlias();
  document.querySelectorAll("#session-table tr.click").forEach((row) => {
    row.onclick = () => showSqlPreview(row.dataset.sql || "");
  });
  if (state.selectedSql) showSqlPreview(state.selectedSql);
}

function showSqlPreview(sql) {
  state.selectedSql = sql;
  const panel = document.querySelector("#sql-preview .sql");
  if (!panel) return;
  panel.textContent = sql || "(SQL 없음)";
  panel.classList.remove("muted");
}

function renderLocks(nodes, depth = 0) {
  if (!nodes || !nodes.length) return `<div class="muted small">대기 중인 Lock이 없습니다.</div>`;
  return nodes.map((node) => `
    <div class="lock">
      <div><strong>SID ${esc(node.sid)}</strong> ${esc(node.db_user || "")} · ${esc(node.wait_event || "holder")} · ${num(node.elapsed_ms)} ms</div>
      <div class="sql">${esc((node.sql_text || "").slice(0, 220))}</div>
      ${renderLocks(node.children, depth + 1)}
    </div>`).join("");
}

async function pageHistory(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const data = await api(`/api/sessions/history?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const rows = data.sessions.map((row) => `
    <tr class="click" data-sql="${esc(row.sql_text)}">
      <td>${esc(row.agent_collect_tm)}</td><td>${esc(row.sid)}</td><td>${esc(row.db_user)}</td>
      <td>${esc(row.status)}</td><td>${esc(row.wait_class)}</td><td>${num(row.elapsed_ms)}</td>
      <td>${esc(row.source)}</td><td class="sql">${esc((row.sql_text || "").slice(0, 160))}</td>
    </tr>`).join("");
  shell("세션 이력", "에이전트에 저장된 Active Session 이력입니다. 수집서버에는 이 이력을 두지 않습니다.", `
    <div class="toolbar">${currentTarget()}</div>
    <div class="panel" style="overflow:auto"><table><thead><tr><th>수집시각</th><th>SID</th><th>사용자</th><th>상태</th><th>Wait</th><th>ms</th><th>출처</th><th>SQL</th></tr></thead><tbody>${rows || `<tr><td colspan="8" class="muted">이력이 없습니다.</td></tr>`}</tbody></table></div>
    <div class="panel" id="sql-preview" style="margin-top:12px"><div class="sql muted">행을 선택하면 SQL 전문이 보입니다.</div></div>`);
  bindAlias();
  document.querySelectorAll("tr.click").forEach((row) => {
    row.onclick = () => {
      document.querySelector("#sql-preview .sql").textContent = row.dataset.sql || "(SQL 없음)";
    };
  });
}

async function pageSql(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const q = document.getElementById("sql-q")?.value || state.sqlQuery || "";
  const data = await api(`/api/sql?alias=${encodeURIComponent(alias)}&q=${encodeURIComponent(q)}`);
  if (!stillCurrent(serial)) return;
  state.sqlQuery = q;
  const rows = data.sql.map((row, index) => `
    <tr class="click" data-index="${index}">
      <td>${esc(row.sql_id)}</td><td>${esc(row.command_type)}</td><td>${num(row.executions)}</td>
      <td>${num(row.elapsed_ms, 1)}</td><td>${num(row.buffer_gets)}</td><td>${num(row.disk_reads)}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 140))}</td>
    </tr>`).join("");
  shell("SQL Text", "수행된 SQL 문은 해당 에이전트에 저장됩니다. 수집 구간 합산 통계도 그 파일에 있습니다.", `
    <div class="toolbar">
      ${currentTarget()}
      <label>검색<br><input id="sql-q" value="${esc(q)}" placeholder="SQL 일부 또는 SQL ID" /></label>
      <button class="primary" id="sql-search">조회</button>
    </div>
    <div class="panel" style="overflow:auto"><table><thead><tr><th>SQL ID</th><th>유형</th><th>수행</th><th>Elapsed ms</th><th>Buffer</th><th>Disk</th><th>SQL</th></tr></thead><tbody>${rows || `<tr><td colspan="7" class="muted">SQL이 없습니다.</td></tr>`}</tbody></table></div>
    <div class="panel" style="margin-top:12px"><header><strong>SQL 전문</strong></header><div id="sql-full" class="sql muted">행을 선택하세요.</div></div>`);
  state._sqlRows = data.sql;
  bindAlias();
  document.getElementById("sql-search").onclick = () => pageSql();
  document.getElementById("sql-q").addEventListener("keydown", (event) => {
    if (event.key === "Enter") pageSql();
  });
  document.querySelectorAll("tr.click").forEach((row) => {
    row.onclick = () => {
      const item = state._sqlRows[Number(row.dataset.index)];
      document.getElementById("sql-full").textContent = item?.sql_text || "";
    };
  });
}

async function pageTrend(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const data = await api(`/api/performance?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  shell("성능 추이", "수집서버에 저장된 DB 성능 샘플입니다.", `
    <div class="toolbar">${currentTarget()}<span class="small muted">${data.series.length} samples</span></div>
    <div class="grid" style="grid-template-columns:1fr 1fr">
      ${metricPanel("CPU %", data.series, "cpu_usage", "#f0b429")}
      ${metricPanel("Active Session", data.series, "active_sessions", "#3dcc97")}
      ${metricPanel("QPS", data.series, "qps", "#6cb6ff")}
      ${metricPanel("Buffer Hit %", data.series, "buffer_cache_ratio", "#d5b4ff")}
    </div>`);
  bindAlias();
}

function metricPanel(title, series, key, color) {
  return `<div class="panel"><header><strong>${esc(title)}</strong></header>${lineChart(series, key, color)}</div>`;
}

function lineChart(series, key, color) {
  const values = (series || []).map((row) => Number(row[key])).filter((value) => !Number.isNaN(value));
  if (!values.length) return `<div class="muted small">데이터가 없습니다.</div>`;
  const width = 520;
  const height = 160;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = values.length === 1 ? 0 : (width - 24) / (values.length - 1);
  const points = values.map((value, index) => {
    const x = 12 + index * step;
    const y = 16 + (1 - (value - min) / span) * (height - 36);
    return `${x},${y}`;
  }).join(" ");
  const last = values[values.length - 1];
  return `<svg class="chart" viewBox="0 0 ${width} ${height}" role="img">
    <polyline fill="none" stroke="${color}" stroke-width="2" points="${points}" />
    <text x="12" y="14">${num(max, 1)}</text>
    <text x="12" y="${height - 4}">${num(min, 1)}</text>
    <text x="${width - 80}" y="14">최근 ${num(last, 1)}</text>
  </svg>`;
}

async function pageReport(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const data = await api(`/api/report?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const summary = data.summary || {};
  const sql = (data.top_sql || []).map((row) => `<tr><td>${esc(row.sql_id)}</td><td>${num(row.elapsed_ms, 1)}</td><td>${num(row.executions)}</td><td class="sql">${esc((row.sql_text || "").slice(0, 180))}</td></tr>`).join("");
  shell("점검 요약", "일간 점검에 쓰는 CPU, 세션, Top SQL 요약입니다.", `
    <div class="toolbar">${currentTarget()}<span class="small muted">${esc(data.start)} ~ ${esc(data.end)} · ${num(data.samples)} samples</span></div>
    <div class="kpis">
      <div class="kpi"><span>CPU 평균</span><strong>${num(summary.cpu_avg, 1)}</strong></div>
      <div class="kpi"><span>CPU 최대</span><strong>${num(summary.cpu_max, 1)}</strong></div>
      <div class="kpi"><span>Active 최대</span><strong>${num(summary.active_max, 0)}</strong></div>
      <div class="kpi"><span>Lock 최대</span><strong>${num(summary.lock_max, 0)}</strong></div>
    </div>
    ${data.sql_error ? `<div class="error">${esc(data.sql_error)}</div>` : ""}
    <div class="panel" style="margin-top:12px"><header><strong>Top SQL</strong></header>
      <table><thead><tr><th>SQL ID</th><th>Elapsed</th><th>수행</th><th>SQL</th></tr></thead><tbody>${sql || `<tr><td colspan="4" class="muted">없음</td></tr>`}</tbody></table>
    </div>`);
  bindAlias();
}

async function pageSettings(serial = state.renderSerial) {
  await ensureDashboard();
  if (!stillCurrent(serial)) return;
  const [settings, instances] = await Promise.all([api("/api/settings"), api("/api/instances")]);
  if (!stillCurrent(serial)) return;
  const editable = settings.settings.filter((item) => !item.setting_key.startsWith("retention.") && !item.setting_key.startsWith("db."));
  const fields = editable.map((item) => `
    <label>${esc(item.description || item.setting_key)}<br>
      <input data-key="${esc(item.setting_key)}" value="${esc(item.secret ? "" : item.setting_value)}" placeholder="${item.secret ? "변경할 때만 입력" : ""}" />
    </label>`).join("");
  const rows = instances.instances.map((item) => `
    <tr>
      <td>${esc(item.agent_alias)}</td><td>${esc(item.product)}</td><td>${esc(item.host_nm)}:${esc(item.port)}</td>
      <td>${esc(item.db_name)}</td><td>${esc(item.group_nm)}</td><td>${esc(item.collect_interval_sec)}s</td>
      <td>${item.enabled ? "사용" : "중지"}</td>
      <td><button class="danger" data-del="${esc(item.agent_alias)}">삭제</button></td>
    </tr>`).join("");
  shell("환경 설정", "수집서버 공통 설정과 모니터링 대상 인스턴스입니다. 비밀번호는 저장만 하고 다시 보여주지 않습니다.", `
    <div class="panel"><header><strong>수집서버 설정</strong></header>
      <div class="form-grid">${fields}</div>
      <div class="row" style="margin-top:12px"><button class="primary" id="save-settings">설정 저장</button></div>
    </div>
    <div class="panel" style="margin-top:12px"><header><strong>인스턴스</strong></header>
      <table><thead><tr><th>별칭</th><th>DBMS</th><th>호스트</th><th>DB</th><th>그룹</th><th>주기</th><th>상태</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      <h3>인스턴스 추가</h3>
      <div class="form-grid">
        <label>별칭<br><input id="n-alias" /></label>
        <label>DBMS<br><select id="n-product"><option>ORACLE</option><option>TIBERO</option><option>MARIADB</option><option>POSTGRESQL</option></select></label>
        <label>호스트<br><input id="n-host" value="127.0.0.1" /></label>
        <label>포트<br><input id="n-port" value="1521" /></label>
        <label>DB 이름<br><input id="n-db" /></label>
        <label>계정<br><input id="n-user" /></label>
        <label>그룹<br><input id="n-group" value="운영" /></label>
        <label>수집주기(초)<br><input id="n-interval" value="5" /></label>
        <label>설명<br><input id="n-desc" /></label>
      </div>
      <div class="row" style="margin-top:12px"><button class="primary" id="add-instance">등록</button></div>
    </div>`);
  document.getElementById("save-settings").onclick = async () => {
    const values = {};
    document.querySelectorAll("[data-key]").forEach((input) => {
      if (input.value !== "") values[input.dataset.key] = input.value;
    });
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ values }) });
    state.error = "";
    showPage("settings");
  };
  document.getElementById("add-instance").onclick = async () => {
    const body = {
      agent_alias: document.getElementById("n-alias").value.trim(),
      product: document.getElementById("n-product").value,
      host_nm: document.getElementById("n-host").value.trim(),
      port: Number(document.getElementById("n-port").value),
      db_name: document.getElementById("n-db").value.trim(),
      username: document.getElementById("n-user").value.trim(),
      group_nm: document.getElementById("n-group").value.trim(),
      collect_interval_sec: Number(document.getElementById("n-interval").value),
      enabled: true,
      description: document.getElementById("n-desc").value.trim(),
    };
    try {
      await api("/api/instances", { method: "POST", body: JSON.stringify(body) });
      showPage("settings");
    } catch (err) {
      alert(err.message);
    }
  };
  document.querySelectorAll("[data-del]").forEach((button) => {
    button.onclick = async () => {
      if (!confirm(`${button.dataset.del} 인스턴스를 삭제할까요?`)) return;
      await api(`/api/instances/${encodeURIComponent(button.dataset.del)}`, { method: "DELETE" });
      if (state.alias === button.dataset.del) setAlias("");
      showPage("settings");
    };
  });
}

async function pageRetention(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = state.alias;
  const data = await api("/api/retention");
  if (!stillCurrent(serial)) return;
  let agent = null;
  let agentError = "";
  try {
    agent = await api(`/api/agent-retention?alias=${encodeURIComponent(alias)}`);
  } catch (err) {
    agentError = err.message;
  }
  if (!stillCurrent(serial)) return;
  const rows = data.policies.map((item) => `
    <tr>
      <td>${esc(item.label)}<div class="small muted">${esc(item.table)}</div></td>
      <td><input data-kind="${esc(item.data_kind)}" data-field="days" type="number" min="0" value="${esc(item.keep_days)}" style="width:90px" /></td>
      <td><input data-kind="${esc(item.data_kind)}" data-field="enabled" type="checkbox" ${item.enabled ? "checked" : ""} /></td>
      <td>${num(item.row_count)}</td>
      <td>${num(item.last_deleted)}</td>
      <td>${esc(item.last_purge_at || "-")}</td>
    </tr>`).join("");
  const log = data.log.map((item) => `<tr><td>${esc(item.ran_at)}</td><td>${esc(item.data_kind)}</td><td>${esc(item.keep_days)}</td><td>${num(item.deleted_rows)}</td></tr>`).join("");
  const agentRows = (agent?.policies || []).map((item) => `
    <tr>
      <td>${esc(item.label)}<div class="small muted">${esc(item.table)}</div></td>
      <td><input data-agent-kind="${esc(item.data_kind)}" data-field="days" type="number" min="0" value="${esc(item.keep_days)}" style="width:90px" /></td>
      <td><input data-agent-kind="${esc(item.data_kind)}" data-field="enabled" type="checkbox" ${item.enabled ? "checked" : ""} /></td>
      <td>${num(item.row_count)}</td>
      <td>${num(item.last_deleted)}</td>
      <td>${esc(item.last_purge_at || "-")}</td>
    </tr>`).join("");
  const agentLog = (agent?.log || []).map((item) => `<tr><td>${esc(item.ran_at)}</td><td>${esc(item.data_kind)}</td><td>${esc(item.keep_days)}</td><td>${num(item.deleted_rows)}</td></tr>`).join("");
  const agentPanel = agent ? `
    <div class="panel" style="margin-top:12px">
      <header><strong>${esc(alias)} 에이전트 저장</strong><span class="small muted">${esc(agent.store_path)}</span></header>
      <p>Active Session, 세션 이력, SQL Text는 이 에이전트 파일에 저장되고, 여기서 정한 주기로 삭제됩니다.</p>
      <div class="form-grid">
        <label>저장 주기(초)<br><input id="agent-save" type="number" min="2" value="${esc(agent.save_interval_sec)}" /></label>
        <label>삭제 주기(초)<br><input id="agent-purge" type="number" min="15" value="${esc(agent.purge_interval_sec)}" /></label>
      </div>
      <table><thead><tr><th>데이터</th><th>보관일수</th><th>사용</th><th>건수</th><th>마지막 삭제</th><th>실행 시각</th></tr></thead><tbody>${agentRows}</tbody></table>
      <div class="row" style="margin-top:12px">
        <button class="primary" id="save-agent-retention">에이전트 주기 저장</button>
        <button class="ghost" id="run-agent-retention">에이전트 지금 삭제</button>
      </div>
    </div>
    <div class="panel" style="margin-top:12px"><header><strong>${esc(alias)} 삭제 이력</strong></header>
      <table><thead><tr><th>시각</th><th>종류</th><th>보관일</th><th>삭제 건수</th></tr></thead><tbody>${agentLog || `<tr><td colspan="4" class="muted">아직 실행 이력이 없습니다.</td></tr>`}</tbody></table>
    </div>` : `<div class="error" style="margin-top:12px">${esc(agentError || "에이전트 저장 정보를 가져오지 못했습니다.")}</div>`;
  shell("보관 주기", "수집서버는 성능과 이벤트만 보관합니다. 세션과 SQL Text의 저장 주기와 삭제 주기는 선택한 에이전트에서 관리합니다.", `
    <div class="toolbar">${currentTarget()}</div>
    <div class="panel">
      <header><strong>수집서버</strong></header>
      <table><thead><tr><th>데이터</th><th>보관일수</th><th>사용</th><th>건수</th><th>마지막 삭제</th><th>실행 시각</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="row" style="margin-top:12px">
        <button class="primary" id="save-retention">주기 저장</button>
        <button class="ghost" id="run-retention">지금 삭제 실행</button>
      </div>
    </div>
    <div class="panel" style="margin-top:12px"><header><strong>수집서버 삭제 이력</strong></header>
      <table><thead><tr><th>시각</th><th>종류</th><th>보관일</th><th>삭제 건수</th></tr></thead><tbody>${log || `<tr><td colspan="4" class="muted">아직 실행 이력이 없습니다.</td></tr>`}</tbody></table>
    </div>
    ${agentPanel}`);
  bindAlias();
  document.getElementById("save-retention").onclick = saveRetention;
  document.getElementById("run-retention").onclick = async () => {
    await saveRetention(false);
    const result = await api("/api/retention/run", { method: "POST" });
    const deleted = result.summary.reduce((sum, item) => sum + (item.deleted_rows || 0), 0);
    state.error = "";
    await pageRetention();
    const note = document.querySelector(".top p");
    if (note) note.textContent = `수집서버 삭제 실행 완료. ${deleted.toLocaleString("ko-KR")}건을 정리했습니다.`;
  };
  const saveAgent = document.getElementById("save-agent-retention");
  if (saveAgent) saveAgent.onclick = () => saveAgentRetention(alias);
  const runAgent = document.getElementById("run-agent-retention");
  if (runAgent) {
    runAgent.onclick = async () => {
      await saveAgentRetention(alias, false);
      const result = await api(`/api/agent-retention/run?alias=${encodeURIComponent(alias)}`, { method: "POST" });
      const deleted = (result.summary || []).reduce((sum, item) => sum + (item.deleted_rows || 0), 0);
      state.error = "";
      await pageRetention();
      const note = document.querySelector(".top p");
      if (note) note.textContent = `${alias} 에이전트에서 ${deleted.toLocaleString("ko-KR")}건을 정리했습니다.`;
    };
  }
}

async function saveAgentRetention(alias, refresh = true) {
  const grouped = {};
  document.querySelectorAll("[data-agent-kind]").forEach((input) => {
    const kind = input.dataset.agentKind;
    grouped[kind] = grouped[kind] || { data_kind: kind, keep_days: 0, enabled: false };
    if (input.dataset.field === "days") grouped[kind].keep_days = Number(input.value);
    if (input.dataset.field === "enabled") grouped[kind].enabled = input.checked;
  });
  await api(`/api/agent-retention?alias=${encodeURIComponent(alias)}`, {
    method: "PUT",
    body: JSON.stringify({
      save_interval_sec: Number(document.getElementById("agent-save").value),
      purge_interval_sec: Number(document.getElementById("agent-purge").value),
      policies: Object.values(grouped),
    }),
  });
  if (refresh) showPage("retention");
}

async function saveRetention(refresh = true) {
  const grouped = {};
  document.querySelectorAll("[data-kind]").forEach((input) => {
    const kind = input.dataset.kind;
    grouped[kind] = grouped[kind] || { data_kind: kind, keep_days: 0, enabled: false };
    if (input.dataset.field === "days") grouped[kind].keep_days = Number(input.value);
    if (input.dataset.field === "enabled") grouped[kind].enabled = input.checked;
  });
  await api("/api/retention", { method: "PUT", body: JSON.stringify({ policies: Object.values(grouped) }) });
  if (refresh) showPage("retention");
}

function bindAlias() {
  const select = document.getElementById("alias");
  if (!select) return;
  select.onchange = () => {
    setAlias(select.value);
    state.selectedSql = "";
    showPage(state.page);
  };
}

loadIdentity().then(boot);
