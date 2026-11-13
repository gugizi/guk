const state = {
  token: localStorage.getItem("okedbmon_token") || "",
  user: null,
  page: "overview",
  alias: localStorage.getItem("okedbmon_alias") || "",
  identity: { title: "OKEDBMON", version: "" },
  dashboard: null,
  error: "",
  timer: null,
  statusFilter: "all",
  productOff: {},
  targetFilter: "",
  sideClosed: false,
  sqlQuery: "",
  selectedSql: "",
};

const MENUS = [
  ["실시간", [
    ["current", "Current"],
    ["session", "Session"],
    ["lock", "Lock"],
    ["event", "Event"],
  ]],
  ["성능 분석", [
    ["history", "Session History"],
    ["sql", "SQL"],
    ["trend", "추이"],
    ["report", "점검 요약"],
  ]],
  ["환경설정", [
    ["settings", "Config"],
    ["retention", "보관 주기"],
  ]],
];

const PAGE_META = {
  current: ["실시간", "Current"],
  session: ["실시간", "Session"],
  lock: ["실시간", "Lock"],
  event: ["실시간", "Event"],
  history: ["성능 분석", "Session History"],
  sql: ["성능 분석", "SQL"],
  trend: ["성능 분석", "추이"],
  report: ["성능 분석", "점검 요약"],
  settings: ["환경설정", "Config"],
  retention: ["환경설정", "보관 주기"],
};

const KEEP_PAGE = ["current", "session", "lock", "event", "history", "sql", "trend", "report", "retention"];
const LIVE_PAGES = ["overview", "current", "session", "lock"];
const SERIES_COLORS = ["#3b6fd8", "#e36b2c", "#2f9e68", "#8d6adf"];

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
    const detail = typeof data.detail === "string" ? data.detail : "로그인이 필요합니다.";
    logout(detail);
    const error = new Error(detail);
    error.auth = true;
    throw error;
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
    // 버전 표시가 없어도 로그인 화면은 열립니다.
  }
  document.title = productLabel();
}

function logout(message = "") {
  state.token = "";
  state.user = null;
  state.page = "overview";
  localStorage.removeItem("okedbmon_token");
  clearInterval(state.timer);
  renderLogin(message);
}

function setAlias(alias) {
  state.alias = alias;
  localStorage.setItem("okedbmon_alias", alias);
}

function levelOf(item) {
  if (!item.online) return "down";
  const cpu = Number(item.cpu_usage || 0);
  const locks = Number(item.lock_wait || 0);
  if (locks > 0 || cpu >= 90) return "critical";
  if ((item.alerts || []).length) return "warning";
  return "start";
}

function productOn(name) {
  return !state.productOff[name];
}

function visibleInstances() {
  return (state.dashboard?.instances || []).filter((item) => {
    if (!productOn(item.product)) return false;
    if (state.statusFilter !== "all" && levelOf(item) !== state.statusFilter) return false;
    return true;
  });
}

function counts() {
  const items = state.dashboard?.instances || [];
  const tally = { all: items.length, start: 0, down: 0, warning: 0, critical: 0 };
  items.forEach((item) => { tally[levelOf(item)] += 1; });
  return tally;
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
      if (LIVE_PAGES.includes(state.page)) showPage(state.page, true);
    }, 5000);
  } catch (err) {
    renderLogin(err.message);
  }
}

function renderLogin(message = "") {
  app.innerHTML = `
    <div class="login">
      <form class="login-card" id="login-form">
        <div class="mark">OK</div>
        <h1>${esc(state.identity.title)}<span class="ver">${esc(versionLabel())}</span></h1>
        <p class="welcome">Welcome to ${esc(state.identity.title)}.</p>
        <input name="username" autocomplete="username" placeholder="User ID" />
        <input name="password" type="password" autocomplete="current-password" placeholder="Password" />
        <button class="primary" type="submit">LOGIN</button>
        ${message ? `<div class="error">${esc(message)}</div>` : ""}
        <p class="copy">${esc(state.identity.title)} · Oracle, Tibero, MariaDB, PostgreSQL</p>
        <p class="hint">초기 계정 admin / okedbmon</p>
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
      state.page = "overview";
      localStorage.setItem("okedbmon_token", data.token);
      boot();
    } catch (err) {
      renderLogin(err.message);
    }
  });
}

function targetList() {
  const items = visibleInstances();
  const groups = {};
  items.forEach((item) => {
    const key = item.product || "기타";
    (groups[key] = groups[key] || []).push(item);
  });
  const body = Object.entries(groups).map(([product, rows]) => `
    <div class="target-group">
      <div class="target-group-title"><span class="product-${esc(product).toLowerCase()}">${esc(product)}</span><span>${rows.length}</span></div>
      ${rows.map((item) => `
        <button type="button" class="target ${item.agent_alias === state.alias ? "selected" : ""}" data-target="${esc(item.agent_alias)}" title="${esc(item.host_nm)}:${esc(item.port)} / ${esc(item.db_name)}">
          <span class="dot ${levelOf(item)}"></span>
          <span>${esc(item.agent_alias)}</span>
          <span class="sub">${esc(item.group_nm || "")}</span>
        </button>`).join("")}
    </div>`).join("");
  return `
    <aside class="targets">
      <div class="targets-head">인스턴스</div>
      <input id="target-filter" class="target-filter" placeholder="이름, 호스트 검색" value="${esc(state.targetFilter || "")}" />
      <div class="target-scroll">${body || `<div class="muted small" style="padding:8px">표시할 대상이 없습니다.</div>`}</div>
    </aside>`;
}

function menuBar() {
  return `<nav class="nav">${MENUS.map(([label, items]) => {
    const active = items.some(([id]) => id === state.page);
    return `<div class="nav-item ${active ? "active" : ""}">
      <button type="button">${esc(label)}</button>
      <div class="nav-drop">
        ${items.map(([id, text]) => `<button type="button" data-page="${id}" class="${state.page === id ? "on" : ""}">${esc(text)}</button>`).join("")}
      </div>
    </div>`;
  }).join("")}</nav>`;
}

function statusBar() {
  const tally = counts();
  const chip = (id, label, klass) => `
    <button type="button" class="chip ${klass} ${state.statusFilter === id ? "active" : ""}" data-status="${id}">
      <span class="lamp"></span>${esc(label)} <b>${tally[id]}</b>
    </button>`;
  return `<div class="status-bar">
    ${chip("all", "All", "")}
    ${chip("start", "Start", "start")}
    ${chip("down", "Down", "down")}
    ${chip("warning", "Warning", "warning")}
    ${chip("critical", "Critical", "critical")}
  </div>`;
}

function header() {
  const detail = state.page !== "overview";
  return `
    <header class="topbar">
      <button type="button" class="brand-btn" id="home">
        <span class="mark">OK</span>
        <span class="brand-text">${esc(state.identity.title)} <small>${esc(versionLabel())}</small></span>
      </button>
      <button type="button" class="icon-btn" id="toggle-side" title="목록 접기">☰</button>
      ${detail ? menuBar() : statusBar()}
      ${detail ? "" : `<span class="spacer"></span>`}
      <span class="who">${esc(state.user?.display_name || state.user?.user_id || "")}</span>
      <div class="gear">
        <button type="button" class="icon-btn" id="gear" title="메뉴">⚙</button>
        <div class="gear-drop">
          <button type="button" data-page="settings">환경설정</button>
          <button type="button" data-page="retention">보관 주기</button>
          <button type="button" id="logout">로그아웃</button>
        </div>
      </div>
    </header>`;
}

function captureScroll() {
  return {
    targets: document.querySelector(".target-scroll")?.scrollTop || 0,
    cards: document.querySelector(".card-board")?.scrollTop || 0,
    charts: document.querySelector(".chart-rail")?.scrollTop || 0,
    detail: document.querySelector(".detail")?.scrollTop || 0,
  };
}

function mount(inner) {
  if (!state.token) return;
  rememberIdentity(state.dashboard);
  document.title = productLabel();
  const saved = captureScroll();
  const filterFocused = document.activeElement?.id === "target-filter";
  app.innerHTML = `
    <div class="frame">
      ${header()}
      <div class="workspace ${state.sideClosed ? "side-closed" : ""}">
        ${targetList()}
        ${inner}
      </div>
    </div>`;
  wire(saved, filterFocused);
}

function wire(saved, filterFocused) {
  document.getElementById("logout").onclick = logout;
  document.getElementById("home").onclick = () => {
    state.statusFilter = "all";
    showPage("overview");
  };
  document.getElementById("toggle-side").onclick = () => {
    state.sideClosed = !state.sideClosed;
    document.querySelector(".workspace").classList.toggle("side-closed", state.sideClosed);
  };
  document.getElementById("gear").onclick = (event) => {
    event.stopPropagation();
    document.querySelector(".gear-drop").classList.toggle("open");
  };
  document.querySelectorAll(".nav-item > button").forEach((button) => {
    button.onclick = (event) => {
      event.stopPropagation();
      const item = button.parentElement;
      const opened = item.classList.contains("open");
      document.querySelectorAll(".nav-item.open").forEach((el) => el.classList.remove("open"));
      if (!opened) item.classList.add("open");
    };
  });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.onclick = () => showPage(button.dataset.page);
  });
  document.querySelectorAll("[data-status]").forEach((button) => {
    button.onclick = () => {
      state.statusFilter = button.dataset.status;
      showPage("overview");
    };
  });
  document.querySelectorAll("[data-target]").forEach((button) => {
    button.onclick = () => {
      setAlias(button.dataset.target);
      state.selectedSql = "";
      showPage(KEEP_PAGE.includes(state.page) ? state.page : "current");
    };
  });
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
  applyTargetFilter();
  const map = [
    [".target-scroll", saved.targets],
    [".card-board", saved.cards],
    [".chart-rail", saved.charts],
    [".detail", saved.detail],
  ];
  map.forEach(([selector, top]) => {
    const node = document.querySelector(selector);
    if (node) node.scrollTop = top;
  });
}

function applyTargetFilter() {
  const filter = (state.targetFilter || "").trim().toLowerCase();
  const byAlias = Object.fromEntries((state.dashboard?.instances || []).map((item) => [item.agent_alias, item]));
  const match = (alias) => {
    if (!filter) return true;
    const item = byAlias[alias] || {};
    return [item.agent_alias, item.product, item.host_nm, item.db_name, item.group_nm]
      .some((value) => String(value || "").toLowerCase().includes(filter));
  };
  document.querySelectorAll(".target-group").forEach((group) => {
    let shown = 0;
    group.querySelectorAll("[data-target]").forEach((button) => {
      const ok = match(button.dataset.target);
      button.hidden = !ok;
      if (ok) shown += 1;
    });
    group.hidden = shown === 0;
  });
  document.querySelectorAll(".inst-card").forEach((card) => {
    card.hidden = !match(card.dataset.alias);
  });
}

document.addEventListener("click", () => {
  document.querySelectorAll(".gear-drop.open, .nav-item.open").forEach((el) => el.classList.remove("open"));
});

function detail(body) {
  const meta = PAGE_META[state.page] || ["", ""];
  const item = (state.dashboard?.instances || []).find((row) => row.agent_alias === state.alias);
  const who = item ? `${item.product} · ${item.agent_alias}` : "대상을 선택하세요";
  mount(`<section class="detail">
    <div class="crumb">${esc(meta[0])} <span>›</span> ${esc(meta[1])} <em>(${esc(who)})</em></div>
    ${state.error ? `<div class="error">${esc(state.error)}</div>` : ""}
    <div class="detail-body">${body}</div>
  </section>`);
}

function busyUi() {
  const el = document.activeElement;
  if (el && ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return true;
  if (document.querySelector(".gear-drop.open, .nav-item.open")) return true;
  return false;
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
  if (silent && busyUi()) return;
  const serial = beginRender();
  state.page = page;
  if (!silent) state.error = "";
  try {
    if (page === "overview") await pageOverview(serial);
    else if (page === "current") await pageCurrent(serial);
    else if (page === "session") await pageSession(serial);
    else if (page === "lock") await pageLock(serial);
    else if (page === "event") await pageEvent(serial);
    else if (page === "history") await pageHistory(serial);
    else if (page === "sql") await pageSql(serial);
    else if (page === "trend") await pageTrend(serial);
    else if (page === "report") await pageReport(serial);
    else if (page === "settings") await pageSettings(serial);
    else if (page === "retention") await pageRetention(serial);
    else await pageOverview(serial);
  } catch (err) {
    if (!stillCurrent(serial) || !state.token) return;
    state.error = err.message;
    if (page === "overview") {
      mount(`<section class="detail"><div class="error">${esc(err.message)}</div></section>`);
    } else {
      detail(`<div class="panel"><div class="muted" style="padding:12px">${esc(err.message)}</div></div>`);
    }
  }
}

async function ensureDashboard() {
  state.dashboard = await api("/api/dashboard");
}

function selectedOrFirst() {
  const items = state.dashboard?.instances || [];
  if (!items.length) return "";
  if (!items.some((item) => item.agent_alias === state.alias)) setAlias(items[0].agent_alias);
  return state.alias;
}

function donut(item) {
  const level = levelOf(item);
  const color = { start: "#2f9e68", warning: "#e0a100", critical: "#d64545", down: "#b0b6bd" }[level];
  const raw = Number(item.cpu_usage);
  const value = Number.isNaN(raw) ? 0 : Math.max(0, Math.min(100, raw));
  return `<svg class="donut" viewBox="0 0 36 36">
    <circle cx="18" cy="18" r="14" fill="none" stroke="#e6e6e6" stroke-width="4" pathLength="100"></circle>
    <circle cx="18" cy="18" r="14" fill="none" stroke="${color}" stroke-width="4" pathLength="100"
      stroke-dasharray="${value} ${100 - value}" stroke-dashoffset="25"></circle>
  </svg>`;
}

function metricLines(item) {
  const rows = [
    ["CPU Usage (%)", num(item.cpu_usage, 1), false],
    ["Memory Usage (%)", num(item.mem_usage, 1), false],
    ["Active Session", num(item.active_sessions), false],
    ["Lock Wait", num(item.lock_wait), Number(item.lock_wait) > 0],
    ["Buffer Hit (%)", num(item.buffer_cache_ratio, 1), false],
    ["Connected", num(item.connected_sessions), false],
  ];
  return rows.map(([label, value, bad]) => `<div class="metric-line"><span>${label}</span><b class="${bad ? "bad" : ""}">${value}</b></div>`).join("");
}

function spark(lines, key) {
  const width = 180;
  const height = 72;
  const prepared = lines.map((line, index) => ({
    color: SERIES_COLORS[index % SERIES_COLORS.length],
    values: (line.series || []).map((row) => Number(row[key])).filter((value) => !Number.isNaN(value)),
  })).filter((line) => line.values.length);
  if (!prepared.length) return `<svg class="spark" viewBox="0 0 ${width} ${height}"><text x="8" y="20">데이터 없음</text></svg>`;
  const flat = prepared.flatMap((line) => line.values);
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const span = max - min || 1;
  const polys = prepared.map((line) => {
    const step = line.values.length === 1 ? 0 : (width - 8) / (line.values.length - 1);
    const points = line.values.map((value, index) => {
      const x = 4 + index * step;
      const y = 8 + (1 - (value - min) / span) * (height - 20);
      return `${x},${y}`;
    }).join(" ");
    return `<polyline fill="none" stroke="${line.color}" stroke-width="1.6" points="${points}" />`;
  }).join("");
  return `<svg class="spark" viewBox="0 0 ${width} ${height}">${polys}<text x="4" y="10">${num(max, 1)}</text></svg>`;
}

async function pageOverview(serial = state.renderSerial) {
  await ensureDashboard();
  if (!stillCurrent(serial)) return;
  const shown = visibleInstances();
  const chartTargets = shown.filter((item) => item.online).slice(0, 4);
  const [seriesPack, slow] = await Promise.all([
    Promise.all(chartTargets.map(async (item) => {
      try {
        const data = await api(`/api/performance?alias=${encodeURIComponent(item.agent_alias)}`);
        return { alias: item.agent_alias, series: data.series || [] };
      } catch (err) {
        if (err.auth) throw err;
        return { alias: item.agent_alias, series: [] };
      }
    })),
    slowSql(chartTargets.map((item) => item.agent_alias)),
  ]);
  if (!stillCurrent(serial)) return;
  const products = [];
  (state.dashboard.instances || []).forEach((item) => {
    if (!products.includes(item.product)) products.push(item.product);
  });
  const cards = shown.map((item) => `
    <button type="button" class="inst-card ${item.agent_alias === state.alias ? "selected" : ""}" data-alias="${esc(item.agent_alias)}">
      <div class="inst-side">
        <div class="pname product-${esc(item.product).toLowerCase()}">${esc(item.product)}</div>
        ${donut(item)}
        <div class="alias">${esc(item.agent_alias)}</div>
      </div>
      <div>${metricLines(item)}</div>
    </button>`).join("");
  const filters = products.map((name) => `
    <label><input type="checkbox" data-product="${esc(name)}" ${productOn(name) ? "checked" : ""} /> ${esc(name)}</label>`).join("");
  const legend = seriesPack.map((line, index) => `<span><i style="background:${SERIES_COLORS[index % SERIES_COLORS.length]}"></i>${esc(line.alias)}</span>`).join("");
  const chart = (title, key) => `<div class="spark-card"><h3>${esc(title)}</h3>${spark(seriesPack, key)}</div>`;
  const aliases = new Set(shown.map((item) => item.agent_alias));
  const events = (state.dashboard.events || []).filter((event) => !aliases.size || aliases.has(event.agent_alias));
  const eventRows = events.map((event, index) => `
    <tr>
      <td>${index + 1}</td>
      <td><span class="dot ${levelOf(shown.find((item) => item.agent_alias === event.agent_alias) || { online: false })}"></span> ${esc(event.agent_alias)}</td>
      <td>${esc(event.occurred_at)}</td>
      <td>${esc(event.event_nm)}</td>
      <td>${esc(event.message)}</td>
    </tr>`).join("");
  const sqlRows = slow.map((row, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${esc(row.agent_alias)}</td>
      <td>${esc(row.last_seen || "")}</td>
      <td>${esc(row.sql_id)}</td>
      <td>${num(row.elapsed_ms, 1)}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 160))}</td>
    </tr>`).join("");
  mount(`<section class="overview">
    <div class="card-board"><div class="inst-grid">${cards || `<div class="muted small" style="padding:16px">이 조건의 인스턴스가 없습니다.</div>`}</div></div>
    <aside class="chart-rail">
      <div class="chart-head"><strong>추이</strong><div class="chart-filters">${filters}</div></div>
      <div class="spark-grid">
        ${chart("CPU Usage (%)", "cpu_usage")}
        ${chart("Memory Usage (%)", "mem_usage")}
        ${chart("Active Sessions", "active_sessions")}
        ${chart("Lock Wait", "lock_wait")}
      </div>
      <div class="legend">${legend || `<span>온라인 인스턴스가 없습니다.</span>`}</div>
    </aside>
    <div class="bottom-split">
      <div class="panel">
        <header><strong>Event List</strong><span class="small muted">${esc(state.dashboard.generated_at || "")}</span></header>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>Database 명</th><th>Event 시간</th><th>Event 이름</th><th>Event 값</th></tr></thead>
          <tbody>${eventRows || `<tr><td colspan="5" class="muted">이벤트가 없습니다.</td></tr>`}</tbody></table></div>
      </div>
      <div class="panel">
        <header><strong>Slow SQL List</strong></header>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>Database 명</th><th>수집시간</th><th>SQL ID</th><th>수행시간</th><th>SQL</th></tr></thead>
          <tbody>${sqlRows || `<tr><td colspan="6" class="muted">SQL이 없습니다.</td></tr>`}</tbody></table></div>
      </div>
    </div>
  </section>`);
  document.querySelectorAll(".inst-card").forEach((card) => {
    card.onclick = () => {
      setAlias(card.dataset.alias);
      showPage("current");
    };
  });
  document.querySelectorAll("[data-product]").forEach((input) => {
    input.onchange = () => {
      state.productOff[input.dataset.product] = !input.checked;
      showPage("overview");
    };
  });
}

async function slowSql(aliases) {
  const chunks = await Promise.all(aliases.slice(0, 4).map(async (alias) => {
    try {
      const data = await api(`/api/sql?alias=${encodeURIComponent(alias)}&limit=6`);
      return (data.sql || []).map((row) => ({ ...row, agent_alias: alias }));
    } catch (err) {
      if (err.auth) throw err;
      return [];
    }
  }));
  return chunks.flat().sort((a, b) => Number(b.elapsed_ms || 0) - Number(a.elapsed_ms || 0)).slice(0, 8);
}

function bar(label, value, max, digits = 1) {
  const n = Number(value);
  const pct = Number.isNaN(n) || !max ? 0 : Math.max(0, Math.min(100, (n / max) * 100));
  return `<div class="bar-row"><div class="bar-label"><span>${esc(label)}</span><b>${num(value, digits)}</b></div><div class="bar"><span style="width:${pct}%"></span></div></div>`;
}

function sessionRows(sessions) {
  return (sessions || []).map((row, index) => `
    <tr class="click" data-sql="${esc(row.sql_text)}">
      <td>${index + 1}</td>
      <td>${esc(row.agent_alias || state.alias)}</td>
      <td>${esc(row.db_user)}</td>
      <td>${esc(row.program)}</td>
      <td>${esc(row.machine || "")}</td>
      <td>${esc(row.sid)}</td>
      <td>${esc(row.status)}</td>
      <td>${esc(row.wait_event || row.wait_class || "")}</td>
      <td>${num(row.elapsed_ms)}</td>
      <td>${esc(row.blocking_sid || "")}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 140))}</td>
    </tr>`).join("");
}

const SESSION_HEAD = "<tr><th>#</th><th>Database</th><th>User</th><th>Program</th><th>Host</th><th>SID</th><th>Status</th><th>Wait</th><th>Elapsed</th><th>Blocker</th><th>SQL</th></tr>";

function bindSqlRows() {
  document.querySelectorAll("tr.click").forEach((row) => {
    row.onclick = () => {
      state.selectedSql = row.dataset.sql || "";
      const panel = document.querySelector("#sql-preview");
      if (panel) {
        panel.textContent = state.selectedSql || "(SQL 없음)";
        panel.classList.remove("muted");
      }
    };
  });
  if (state.selectedSql) {
    const panel = document.querySelector("#sql-preview");
    if (panel) {
      panel.textContent = state.selectedSql;
      panel.classList.remove("muted");
    }
  }
}

async function pageCurrent(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  if (!alias) {
    detail(`<div class="muted">등록된 인스턴스가 없습니다.</div>`);
    return;
  }
  const [sessions, series] = await Promise.all([
    api(`/api/sessions/active?alias=${encodeURIComponent(alias)}`),
    api(`/api/performance?alias=${encodeURIComponent(alias)}`),
  ]);
  if (!stillCurrent(serial)) return;
  const item = (state.dashboard.instances || []).find((row) => row.agent_alias === alias) || {};
  const active = (sessions.sessions || []).filter((row) => row.status === "ACTIVE");
  detail(`
    <div class="blocks">
      <div class="block">
        <h3>Session</h3>
        <div class="stat"><span>Connected</span><b>${num(item.connected_sessions)}</b></div>
        <div class="stat"><span>Active</span><b>${num(item.active_sessions)}</b></div>
        <div class="stat"><span>Lock Wait</span><b>${num(item.lock_wait)}</b></div>
        <h3>Workload</h3>
        <div class="stat"><span>QPS</span><b>${num(item.qps, 1)}</b></div>
        <div class="stat"><span>TPS</span><b>${num(item.tps, 1)}</b></div>
        <div class="stat"><span>Execute</span><b>${num(item.execute_cnt)}</b></div>
      </div>
      <div class="block">
        <h3>System</h3>
        ${bar("CPU Usage (%)", item.cpu_usage, 100)}
        ${bar("Memory Usage (%)", item.mem_usage, 100)}
        <h3>Ratio</h3>
        ${bar("Buffer Hit (%)", item.buffer_cache_ratio, 100)}
        <div class="small muted">수집 ${esc(sessions.collect_tm || item.last_seen || "-")} · Active ${active.length} / ${sessions.sessions.length}</div>
      </div>
      <div class="block">
        <h3>Active Sessions</h3>
        ${spark([{ series: series.series }], "active_sessions")}
        <h3>CPU</h3>
        ${spark([{ series: series.series }], "cpu_usage")}
      </div>
    </div>
    <div class="split">
      <div class="panel">
        <header><strong>Active Session</strong></header>
        <div class="table-wrap"><table><thead>${SESSION_HEAD}</thead><tbody>${sessionRows(sessions.sessions) || `<tr><td colspan="11" class="muted">세션이 없습니다.</td></tr>`}</tbody></table></div>
      </div>
      <div class="panel">
        <header><strong>Lock</strong></header>
        <div style="padding:8px; overflow:auto">${renderLocks(sessions.locks)}</div>
      </div>
    </div>
    <div class="panel" style="margin-top:8px"><header><strong>SQL Text</strong></header><div id="sql-preview" class="sql muted" style="padding:8px">세션을 선택하면 SQL이 표시됩니다.</div></div>`);
  bindSqlRows();
}

async function pageSession(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const sessions = await api(`/api/sessions/active?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const active = (sessions.sessions || []).filter((row) => row.status === "ACTIVE");
  detail(`
    <div class="toolbar"><span class="small muted">수집 ${esc(sessions.collect_tm || "-")} · Active ${active.length} / 전체 ${(sessions.sessions || []).length}</span></div>
    <div class="panel"><div class="table-wrap"><table><thead>${SESSION_HEAD}</thead><tbody>${sessionRows(sessions.sessions) || `<tr><td colspan="11" class="muted">세션이 없습니다.</td></tr>`}</tbody></table></div></div>
    <div class="panel" style="margin-top:8px"><header><strong>SQL Text</strong></header><div id="sql-preview" class="sql muted" style="padding:8px">행을 선택하세요.</div></div>`);
  bindSqlRows();
}

function renderLocks(nodes) {
  if (!nodes || !nodes.length) return `<div class="muted small">대기 중인 Lock이 없습니다.</div>`;
  return nodes.map((node) => `
    <div class="lock">
      <div><strong>SID ${esc(node.sid)}</strong> ${esc(node.db_user || "")} · ${esc(node.wait_event || "holder")} · ${num(node.elapsed_ms)} ms</div>
      <div class="sql">${esc((node.sql_text || "").slice(0, 220))}</div>
      ${renderLocks(node.children)}
    </div>`).join("");
}

async function pageLock(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const sessions = await api(`/api/sessions/active?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const waiting = (sessions.sessions || []).filter((row) => row.blocking_sid);
  const rows = waiting.map((row, index) => `
    <tr class="click" data-sql="${esc(row.sql_text)}">
      <td>${index + 1}</td><td>${esc(alias)}</td><td>${esc(row.sid)}</td><td>${esc(row.blocking_sid)}</td>
      <td>${esc(row.db_user)}</td><td>${esc(row.wait_event || "")}</td><td>${num(row.elapsed_ms)}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 160))}</td>
    </tr>`).join("");
  detail(`
    <div class="split">
      <div class="panel">
        <header><strong>Lock Wait</strong></header>
        <div class="table-wrap"><table><thead><tr><th>#</th><th>Database</th><th>SID</th><th>Blocker</th><th>User</th><th>Wait</th><th>Elapsed</th><th>SQL</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="8" class="muted">Lock 대기가 없습니다.</td></tr>`}</tbody></table></div>
      </div>
      <div class="panel"><header><strong>Lock Tree</strong></header><div style="padding:8px; overflow:auto">${renderLocks(sessions.locks)}</div></div>
    </div>
    <div class="panel" style="margin-top:8px"><div id="sql-preview" class="sql muted" style="padding:8px">행을 선택하면 SQL이 표시됩니다.</div></div>`);
  bindSqlRows();
}

async function pageEvent(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const data = await api(`/api/events?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const rows = (data.events || []).map((event, index) => `
    <tr><td>${index + 1}</td><td>${esc(event.agent_alias)}</td><td>${esc(event.occurred_at)}</td><td>${esc(event.severity)}</td><td>${esc(event.event_nm)}</td><td>${esc(event.message)}</td></tr>`).join("");
  detail(`<div class="panel"><div class="table-wrap"><table><thead><tr><th>#</th><th>Database</th><th>Event 시간</th><th>등급</th><th>Event 이름</th><th>Event 값</th></tr></thead><tbody>${rows || `<tr><td colspan="6" class="muted">이벤트가 없습니다.</td></tr>`}</tbody></table></div></div>`);
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function stamp(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function rangeValue(key, hours) {
  if (state[key]) return state[key];
  const date = new Date(Date.now() - hours * 3600 * 1000);
  return stamp(date).slice(0, 16).replace(" ", "T");
}

function toApiTime(value) {
  if (!value) return "";
  const text = value.replace("T", " ");
  return text.length === 16 ? `${text}:00` : text;
}

async function pageHistory(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const start = rangeValue("histStart", 1);
  const end = rangeValue("histEnd", 0);
  const data = await api(`/api/sessions/history?alias=${encodeURIComponent(alias)}&start=${encodeURIComponent(toApiTime(start))}&end=${encodeURIComponent(toApiTime(end))}`);
  if (!stillCurrent(serial)) return;
  state.histStart = start;
  state.histEnd = end;
  const rows = (data.sessions || []).map((row) => `
    <tr class="click" data-sql="${esc(row.sql_text)}">
      <td>${esc(row.agent_collect_tm)}</td><td>${esc(row.sid)}</td><td>${esc(row.db_user)}</td>
      <td>${esc(row.machine || "")}</td><td>${esc(row.status)}</td><td>${esc(row.wait_class || "")}</td>
      <td>${num(row.elapsed_ms)}</td><td class="sql">${esc((row.sql_text || "").slice(0, 140))}</td>
    </tr>`).join("");
  detail(`
    <div class="toolbar">
      <label>시작<input id="hist-start" type="datetime-local" value="${esc(start)}" /></label>
      <label>끝<input id="hist-end" type="datetime-local" value="${esc(end)}" /></label>
      <button type="button" class="primary" id="hist-search">검색</button>
      <button type="button" class="quick" data-hours="1">1시간</button>
      <button type="button" class="quick" data-hours="6">6시간</button>
      <button type="button" class="quick" data-hours="12">12시간</button>
      <button type="button" class="quick" data-hours="24">1일</button>
      <button type="button" class="quick" data-hours="168">7일</button>
    </div>
    <div class="panel"><div class="table-wrap"><table><thead><tr><th>수집시각</th><th>SID</th><th>User</th><th>Host</th><th>Status</th><th>Wait</th><th>Elapsed</th><th>SQL</th></tr></thead><tbody>${rows || `<tr><td colspan="8" class="muted">이력이 없습니다.</td></tr>`}</tbody></table></div></div>
    <div class="panel" style="margin-top:8px"><div id="sql-preview" class="sql muted" style="padding:8px">행을 선택하면 SQL 전문이 보입니다.</div></div>`);
  bindSqlRows();
  const search = () => {
    state.histStart = document.getElementById("hist-start").value;
    state.histEnd = document.getElementById("hist-end").value;
    showPage("history");
  };
  document.getElementById("hist-search").onclick = search;
  document.querySelectorAll("[data-hours]").forEach((button) => {
    button.onclick = () => {
      const hours = Number(button.dataset.hours);
      const endDate = new Date();
      state.histEnd = stamp(endDate).slice(0, 16).replace(" ", "T");
      state.histStart = stamp(new Date(endDate.getTime() - hours * 3600 * 1000)).slice(0, 16).replace(" ", "T");
      showPage("history");
    };
  });
}

async function pageSql(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const q = state.sqlQuery || "";
  const data = await api(`/api/sql?alias=${encodeURIComponent(alias)}&q=${encodeURIComponent(q)}`);
  if (!stillCurrent(serial)) return;
  const rows = (data.sql || []).map((row, index) => `
    <tr class="click" data-index="${index}">
      <td>${esc(row.sql_id)}</td><td>${esc(row.command_type)}</td><td>${num(row.executions)}</td>
      <td>${num(row.elapsed_ms, 1)}</td><td>${num(row.buffer_gets)}</td><td>${num(row.disk_reads)}</td>
      <td>${esc(row.last_seen || "")}</td>
      <td class="sql">${esc((row.sql_text || "").slice(0, 140))}</td>
    </tr>`).join("");
  detail(`
    <div class="toolbar">
      <label>검색<input id="sql-q" value="${esc(q)}" placeholder="SQL 일부 또는 SQL ID" /></label>
      <button type="button" class="primary" id="sql-search">검색</button>
    </div>
    <div class="panel"><div class="table-wrap"><table><thead><tr><th>SQL ID</th><th>유형</th><th>수행</th><th>Elapsed</th><th>Buffer</th><th>Disk</th><th>수집시간</th><th>SQL</th></tr></thead><tbody>${rows || `<tr><td colspan="8" class="muted">SQL이 없습니다.</td></tr>`}</tbody></table></div></div>
    <div class="panel" style="margin-top:8px"><header><strong>SQL 전문</strong></header><div id="sql-full" class="sql muted" style="padding:8px">행을 선택하세요.</div></div>`);
  state._sqlRows = data.sql || [];
  document.getElementById("sql-search").onclick = () => {
    state.sqlQuery = document.getElementById("sql-q").value;
    showPage("sql");
  };
  document.getElementById("sql-q").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      state.sqlQuery = event.target.value;
      showPage("sql");
    }
  });
  document.querySelectorAll("tr.click").forEach((row) => {
    row.onclick = () => {
      const item = state._sqlRows[Number(row.dataset.index)];
      const panel = document.getElementById("sql-full");
      panel.textContent = item?.sql_text || "";
      panel.classList.remove("muted");
    };
  });
}

function lineChart(series, key, color) {
  const values = (series || []).map((row) => Number(row[key])).filter((value) => !Number.isNaN(value));
  if (!values.length) return `<div class="muted small">데이터가 없습니다.</div>`;
  const width = 520;
  const height = 150;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = values.length === 1 ? 0 : (width - 16) / (values.length - 1);
  const points = values.map((value, index) => {
    const x = 8 + index * step;
    const y = 16 + (1 - (value - min) / span) * (height - 28);
    return `${x},${y}`;
  }).join(" ");
  return `<svg class="spark" style="height:150px" viewBox="0 0 ${width} ${height}"><polyline fill="none" stroke="${color}" stroke-width="2" points="${points}" /><text x="8" y="12">${num(max, 1)}</text><text x="${width - 70}" y="12">최근 ${num(values[values.length - 1], 1)}</text></svg>`;
}

async function pageTrend(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const data = await api(`/api/performance?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const panel = (title, key, color) => `<div class="block"><h3>${esc(title)}</h3>${lineChart(data.series, key, color)}</div>`;
  detail(`<div class="blocks" style="grid-template-columns:1fr 1fr">
    ${panel("CPU Usage (%)", "cpu_usage", "#e36b2c")}
    ${panel("Memory Usage (%)", "mem_usage", "#3b6fd8")}
    ${panel("Active Session", "active_sessions", "#2f9e68")}
    ${panel("Buffer Hit (%)", "buffer_cache_ratio", "#8d6adf")}
  </div>`);
}

async function pageReport(serial = state.renderSerial) {
  await ensureDashboard();
  const alias = selectedOrFirst();
  const data = await api(`/api/report?alias=${encodeURIComponent(alias)}`);
  if (!stillCurrent(serial)) return;
  const summary = data.summary || {};
  const sql = (data.top_sql || []).map((row) => `<tr><td>${esc(row.sql_id)}</td><td>${num(row.elapsed_ms, 1)}</td><td>${num(row.executions)}</td><td class="sql">${esc((row.sql_text || "").slice(0, 180))}</td></tr>`).join("");
  detail(`
    <div class="small muted" style="margin-bottom:8px">${esc(data.start)} ~ ${esc(data.end)} · ${num(data.samples)} samples</div>
    <div class="kpis">
      <div class="kpi"><span>CPU 평균</span><strong>${num(summary.cpu_avg, 1)}</strong></div>
      <div class="kpi"><span>CPU 최대</span><strong>${num(summary.cpu_max, 1)}</strong></div>
      <div class="kpi"><span>Active 최대</span><strong>${num(summary.active_max, 0)}</strong></div>
      <div class="kpi"><span>Lock 최대</span><strong>${num(summary.lock_max, 0)}</strong></div>
    </div>
    ${data.sql_error ? `<div class="error">${esc(data.sql_error)}</div>` : ""}
    <div class="panel"><header><strong>Top SQL</strong></header>
      <div class="table-wrap"><table><thead><tr><th>SQL ID</th><th>Elapsed</th><th>수행</th><th>SQL</th></tr></thead><tbody>${sql || `<tr><td colspan="4" class="muted">없음</td></tr>`}</tbody></table></div>
    </div>`);
}

async function pageSettings(serial = state.renderSerial) {
  await ensureDashboard();
  if (!stillCurrent(serial)) return;
  const [settings, instances] = await Promise.all([api("/api/settings"), api("/api/instances")]);
  if (!stillCurrent(serial)) return;
  const editable = settings.settings.filter((item) => !item.setting_key.startsWith("retention.") && !item.setting_key.startsWith("db."));
  const fields = editable.map((item) => `
    <label>${esc(item.description || item.setting_key)}
      <input data-key="${esc(item.setting_key)}" value="${esc(item.secret ? "" : item.setting_value)}" placeholder="${item.secret ? "변경할 때만 입력" : ""}" />
    </label>`).join("");
  const rows = instances.instances.map((item) => `
    <tr>
      <td>${esc(item.agent_alias)}</td><td>${esc(item.product)}</td><td>${esc(item.host_nm)}:${esc(item.port)}</td>
      <td>${esc(item.db_name)}</td><td>${esc(item.group_nm)}</td><td>${esc(item.collect_interval_sec)}s</td>
      <td>${item.enabled ? "사용" : "중지"}</td>
      <td><button type="button" class="danger" data-del="${esc(item.agent_alias)}">삭제</button></td>
    </tr>`).join("");
  detail(`
    <div class="panel" style="padding:12px"><header><strong>수집서버 설정</strong></header>
      <div class="form-grid">${fields}</div>
      <div style="margin-top:12px"><button type="button" class="primary" id="save-settings">설정 저장</button></div>
    </div>
    <div class="panel" style="margin-top:8px; padding:12px"><header><strong>인스턴스</strong></header>
      <div class="table-wrap"><table><thead><tr><th>별칭</th><th>DBMS</th><th>호스트</th><th>DB</th><th>그룹</th><th>주기</th><th>상태</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <h3>인스턴스 추가</h3>
      <div class="form-grid">
        <label>별칭<input id="n-alias" /></label>
        <label>DBMS<select id="n-product"><option>ORACLE</option><option>TIBERO</option><option>MARIADB</option><option>POSTGRESQL</option></select></label>
        <label>호스트<input id="n-host" value="127.0.0.1" /></label>
        <label>포트<input id="n-port" value="1521" /></label>
        <label>DB 이름<input id="n-db" /></label>
        <label>계정<input id="n-user" /></label>
        <label>그룹<input id="n-group" value="운영" /></label>
        <label>수집주기(초)<input id="n-interval" value="5" /></label>
        <label>설명<input id="n-desc" /></label>
      </div>
      <div style="margin-top:12px"><button type="button" class="primary" id="add-instance">등록</button></div>
    </div>`);
  document.getElementById("save-settings").onclick = async () => {
    const values = {};
    document.querySelectorAll("[data-key]").forEach((input) => {
      if (input.value !== "") values[input.dataset.key] = input.value;
    });
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ values }) });
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
  const alias = selectedOrFirst();
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
      <td>${esc(item.label)}</td>
      <td><input data-kind="${esc(item.data_kind)}" data-field="days" type="number" min="0" value="${esc(item.keep_days)}" style="width:90px" /></td>
      <td><input data-kind="${esc(item.data_kind)}" data-field="enabled" type="checkbox" ${item.enabled ? "checked" : ""} /></td>
      <td>${num(item.row_count)}</td>
      <td>${num(item.last_deleted)}</td>
      <td>${esc(item.last_purge_at || "-")}</td>
    </tr>`).join("");
  const log = data.log.map((item) => `<tr><td>${esc(item.ran_at)}</td><td>${esc(item.data_kind)}</td><td>${esc(item.keep_days)}</td><td>${num(item.deleted_rows)}</td></tr>`).join("");
  const agentRows = (agent?.policies || []).map((item) => `
    <tr>
      <td>${esc(item.label)}</td>
      <td><input data-agent-kind="${esc(item.data_kind)}" data-field="days" type="number" min="0" value="${esc(item.keep_days)}" style="width:90px" /></td>
      <td><input data-agent-kind="${esc(item.data_kind)}" data-field="enabled" type="checkbox" ${item.enabled ? "checked" : ""} /></td>
      <td>${num(item.row_count)}</td>
      <td>${num(item.last_deleted)}</td>
      <td>${esc(item.last_purge_at || "-")}</td>
    </tr>`).join("");
  const agentLog = (agent?.log || []).map((item) => `<tr><td>${esc(item.ran_at)}</td><td>${esc(item.data_kind)}</td><td>${esc(item.keep_days)}</td><td>${num(item.deleted_rows)}</td></tr>`).join("");
  const agentPanel = agent ? `
    <div class="panel" style="margin-top:8px; padding:12px">
      <header><strong>${esc(alias)} 에이전트 저장</strong><span class="small muted">${esc(agent.store_path || "")}</span></header>
      <p class="small">Active Session, 세션 이력, SQL Text는 이 에이전트에 저장됩니다.</p>
      <div class="form-grid">
        <label>저장 주기(초)<input id="agent-save" type="number" min="2" value="${esc(agent.save_interval_sec)}" /></label>
        <label>삭제 주기(초)<input id="agent-purge" type="number" min="15" value="${esc(agent.purge_interval_sec)}" /></label>
      </div>
      <table><thead><tr><th>데이터</th><th>보관일수</th><th>사용</th><th>건수</th><th>마지막 삭제</th><th>실행 시각</th></tr></thead><tbody>${agentRows}</tbody></table>
      <div style="margin-top:12px">
        <button type="button" class="primary" id="save-agent-retention">에이전트 주기 저장</button>
        <button type="button" class="ghost" id="run-agent-retention">에이전트 지금 삭제</button>
      </div>
    </div>
    <div class="panel" style="margin-top:8px"><header><strong>${esc(alias)} 삭제 이력</strong></header>
      <table><thead><tr><th>시각</th><th>종류</th><th>보관일</th><th>삭제 건수</th></tr></thead><tbody>${agentLog || `<tr><td colspan="4" class="muted">아직 실행 이력이 없습니다.</td></tr>`}</tbody></table>
    </div>` : `<div class="error">${esc(agentError || "에이전트 저장 정보를 가져오지 못했습니다.")}</div>`;
  detail(`
    <div class="panel" style="padding:12px">
      <header><strong>수집서버</strong></header>
      <table><thead><tr><th>데이터</th><th>보관일수</th><th>사용</th><th>건수</th><th>마지막 삭제</th><th>실행 시각</th></tr></thead><tbody>${rows}</tbody></table>
      <div style="margin-top:12px">
        <button type="button" class="primary" id="save-retention">주기 저장</button>
        <button type="button" class="ghost" id="run-retention">지금 삭제 실행</button>
      </div>
    </div>
    <div class="panel" style="margin-top:8px"><header><strong>수집서버 삭제 이력</strong></header>
      <table><thead><tr><th>시각</th><th>종류</th><th>보관일</th><th>삭제 건수</th></tr></thead><tbody>${log || `<tr><td colspan="4" class="muted">아직 실행 이력이 없습니다.</td></tr>`}</tbody></table>
    </div>
    ${agentPanel}`);
  document.getElementById("save-retention").onclick = () => saveRetention(true);
  document.getElementById("run-retention").onclick = async () => {
    await saveRetention(false);
    await api("/api/retention/run", { method: "POST" });
    showPage("retention");
  };
  const saveAgent = document.getElementById("save-agent-retention");
  if (saveAgent) saveAgent.onclick = () => saveAgentRetention(alias, true);
  const runAgent = document.getElementById("run-agent-retention");
  if (runAgent) {
    runAgent.onclick = async () => {
      await saveAgentRetention(alias, false);
      await api(`/api/agent-retention/run?alias=${encodeURIComponent(alias)}`, { method: "POST" });
      showPage("retention");
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

loadIdentity().then(boot);
