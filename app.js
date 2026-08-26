const STORAGE_KEY = "kr-valuation-board:v1";
const ORDER_KEY = "kr-valuation-board:order:v1";
const DEFAULT_MULTIPLES = { PER: [20, 15, 10], PBR: [2, 1.8, 1.6] };
const formatter = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 });

let dataset = { stocks: [], failures: [] };
let preferences = loadPreferences();
let stockOrder = loadStockOrder();

function loadPreferences() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; }
  catch { return {}; }
}

function savePreferences() { localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences)); }
function loadStockOrder() {
  try {
    const saved = JSON.parse(localStorage.getItem(ORDER_KEY));
    return Array.isArray(saved) ? saved : [];
  } catch { return []; }
}
function saveStockOrder() { localStorage.setItem(ORDER_KEY, JSON.stringify(stockOrder)); }
function orderedStocks() {
  const available = new Set(dataset.stocks.map((stock) => stock.code));
  stockOrder = stockOrder.filter((code) => available.has(code));
  dataset.stocks.forEach((stock) => {
    if (!stockOrder.includes(stock.code)) stockOrder.push(stock.code);
  });
  saveStockOrder();
  const byCode = new Map(dataset.stocks.map((stock) => [stock.code, stock]));
  return stockOrder.map((code) => byCode.get(code)).filter(Boolean);
}
function moveStock(code, direction) {
  const visibleCodes = orderedStocks().filter((stock) => getPreference(stock).visible).map((stock) => stock.code);
  const visibleIndex = visibleCodes.indexOf(code);
  const swapCode = visibleCodes[visibleIndex + direction];
  if (!swapCode) return;
  const from = stockOrder.indexOf(code);
  const to = stockOrder.indexOf(swapCode);
  [stockOrder[from], stockOrder[to]] = [stockOrder[to], stockOrder[from]];
  saveStockOrder();
  render();
}
function formatWon(value) { return value == null ? "—" : `${formatter.format(Math.round(value / 100) * 100)}원`; }
function formatBasis(value) { return value == null ? "—" : formatter.format(value); }
function latestYears(stock) { return Object.keys(stock.annual).sort(); }

function getPreference(stock) {
  const saved = preferences[stock.code] || {};
  const metric = saved.metric || stock.defaultMetric || "PER";
  return {
    visible: saved.visible !== false,
    metric,
    discount: Number.isFinite(saved.discount) ? saved.discount : 90,
    multiples: Array.isArray(saved.multiples) && saved.multiples.length === 3 ? saved.multiples : DEFAULT_MULTIPLES[metric],
  };
}

function setPreference(code, patch) {
  preferences[code] = { ...getPreference(dataset.stocks.find((stock) => stock.code === code)), ...preferences[code], ...patch };
  savePreferences();
}

function calculateRows(stock, pref) {
  const key = pref.metric === "PBR" ? "bps" : "eps";
  const years = latestYears(stock);
  const rows = years.map((year) => ({ year, label: `${year}E`, basis: stock.annual[year]?.[key], conservative: false }));
  if (stock.annual["2027"]?.[key] != null) {
    rows.splice(rows.findIndex((row) => row.label === "2027E"), 0, {
      year: "2027", label: "2027 보수", basis: stock.annual["2027"][key] * pref.discount / 100, conservative: true,
    });
  }
  return rows;
}

function consensusChange(stock, pref, year = "2027") {
  const key = pref.metric === "PBR" ? "bps" : "eps";
  const current = stock.annual?.[year]?.[key];
  const previous = stock.previousAnnual?.[year]?.[key];
  if (!Number.isFinite(current) || !Number.isFinite(previous) || previous === 0) return null;
  return (current / previous - 1) * 100;
}

function consensusChangeMarkup(change, prefix = "컨센서스") {
  if (change == null) return `<span class="change-flat">${prefix} 비교 준비 중</span>`;
  const direction = change > 0.05 ? "▲" : change < -0.05 ? "▼" : "→";
  const className = change > 0.05 ? "change-up" : change < -0.05 ? "change-down" : "change-flat";
  return `<span class="${className}">${prefix} ${direction} ${Math.abs(change).toFixed(1)}%</span>`;
}

function renderInvestorFlow(card, stock) {
  const flow = stock.investorTrading;
  const section = card.querySelector(".investor-flow");
  if (!flow || !Number.isFinite(flow.institution) || !Number.isFinite(flow.foreign)) return;
  section.querySelector(".investor-date").textContent = `${flow.date || "기준일 미상"} 누적 · 시간별 갱신`;
  [
    ["institution", flow.institution],
    ["foreign", flow.foreign],
  ].forEach(([key, value]) => {
    const valueElement = section.querySelector(`.${key}-flow`);
    const stateElement = section.querySelector(`.${key}-state`);
    const state = value > 0 ? "순매수" : value < 0 ? "순매도" : "보합";
    const className = value > 0 ? "net-buy" : value < 0 ? "net-sell" : "net-flat";
    valueElement.textContent = `${value > 0 ? "+" : ""}${formatter.format(value)}주`;
    valueElement.classList.add(className);
    stateElement.textContent = state;
    stateElement.classList.add(className);
  });
  section.hidden = false;
}

function renderValuationRange(section, stock, pref, basis) {
  if (!section || !basis || !stock.price) return;
  const levels = ["상", "중", "하"];
  const targets = pref.multiples.map((multiple, index) => ({
    value: basis * multiple,
    multiple,
    goal: index + 1,
    level: levels[index],
  }));
  const sortedTargets = [...targets].sort((a, b) => a.value - b.value);
  const low = sortedTargets[0].value;
  const high = sortedTargets.at(-1).value;
  if (!Number.isFinite(low) || !Number.isFinite(high) || high <= 0) return;

  const rawPosition = high === low ? 50 : (stock.price - low) / (high - low) * 100;
  const position = Math.min(100, Math.max(0, rawPosition));
  const marker = section.querySelector(".current-marker");
  marker.style.left = `${position}%`;
  marker.classList.toggle("outside-low", rawPosition < 0);
  marker.classList.toggle("outside-high", rawPosition > 100);
  section.querySelector(".current-marker-label").textContent = `현재 ${formatWon(stock.price)}`;
  const status = rawPosition < 0 ? "범위 미만" : rawPosition > 100 ? "범위 초과" : `범위 내 ${position.toFixed(0)}%`;
  section.querySelector(".range-status").textContent = status;
  const track = section.querySelector(".range-chart");
  track.setAttribute("role", "meter");
  track.setAttribute("aria-valuemin", String(Math.round(low)));
  track.setAttribute("aria-valuemax", String(Math.round(high)));
  track.setAttribute("aria-valuenow", String(Math.round(stock.price)));

  const ticks = section.querySelector(".range-target-ticks");
  ticks.replaceChildren();
  targets.forEach((target) => {
    const tick = document.createElement("i");
    const tickPosition = high === low ? 50 : (target.value - low) / (high - low) * 100;
    tick.style.left = `${tickPosition}%`;
    ticks.append(tick);
  });

  const targetList = section.querySelector(".range-targets");
  targetList.replaceChildren();
  sortedTargets.forEach((target) => {
    const item = document.createElement("div");
    item.className = `range-target range-target-${target.level === "상" ? "high" : target.level === "중" ? "mid" : "low"}`;
    item.innerHTML = `<span><b>${target.level}</b> 목표 ${target.goal}</span><strong>${formatWon(target.value)}</strong><small>${pref.metric} ${formatter.format(target.multiple)}배</small>`;
    targetList.append(item);
  });
  section.hidden = false;
}

function renderCard(stock, index = 0, total = 1, detail = false) {
  const pref = getPreference(stock);
  const card = document.getElementById("cardTemplate").content.firstElementChild.cloneNode(true);
  card.classList.add(detail ? "detail-card" : "dashboard-card");
  card.dataset.code = stock.code;
  card.querySelector(".stock-name").textContent = stock.name;
  card.querySelector(".stock-code").textContent = stock.code;
  const isStale = stock.collectionStatus?.state === "stale";
  if (isStale) card.classList.add("stale-card");
  card.querySelector(".quote-date").textContent = `${stock.quotedAt || "기준일 미상"} 현재가 기준${isStale ? " · 이전 데이터 유지" : ""}`;
  card.querySelector(".current-price").textContent = formatWon(stock.price);
  card.querySelector(".metric-select").value = pref.metric;
  card.querySelector(".discount-input").value = pref.discount;
  card.querySelector(".basis-heading").textContent = pref.metric === "PBR" ? "BPS" : "EPS";
  card.querySelector(".source-link").href = stock.source.consensus;

  const multiples = card.querySelector(".multiples");
  pref.multiples.forEach((multiple, index) => {
    const label = document.createElement("label");
    label.innerHTML = `<span>목표 ${pref.metric} ${index + 1}</span><div class="input-suffix"><input type="number" min="0" step="0.1" value="${multiple}" aria-label="목표 배수 ${index + 1}"><span>배</span></div>`;
    label.querySelector("input").addEventListener("change", (event) => {
      const next = [...getPreference(stock).multiples];
      next[index] = Math.max(0, Number(event.target.value) || 0);
      setPreference(stock.code, { multiples: next }); render();
      if (detail) openStockDetail(stock.code);
    });
    multiples.append(label);
  });

  const rows = calculateRows(stock, pref);
  const primaryBasis = rows.find((row) => row.conservative)?.basis || rows.at(-1)?.basis;
  card.querySelector(".current-multiple strong").textContent = primaryBasis ? `${(stock.price / primaryBasis).toFixed(2)}배` : "—";
  card.querySelector(".multiple-basis").textContent = primaryBasis ? `2027 보수 ${pref.metric === "PBR" ? "BPS" : "EPS"} 기준` : "기준값 없음";
  card.querySelector(".consensus-change").innerHTML = consensusChangeMarkup(consensusChange(stock, pref));
  const tbody = card.querySelector("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.conservative) tr.className = "conservative";
    const targets = pref.multiples.map((multiple) => {
      const target = row.basis == null ? null : row.basis * multiple;
      const upside = target == null || !stock.price ? null : (target / stock.price - 1) * 100;
      return `<td><strong>${formatWon(target)}</strong><small>${multiple}배 · <span class="potential-text ${upside >= 0 ? "up" : "down"}">${upside == null ? "—" : `${upside >= 0 ? "+" : ""}${upside.toFixed(1)}%`}</span></small></td>`;
    }).join("");
    const change = consensusChange(stock, pref, row.year);
    tr.innerHTML = `<td><strong>${row.label}</strong>${row.conservative ? `<small>${pref.discount}% 반영</small>` : ""}</td><td>${formatBasis(row.basis)}<small class="basis-change">${consensusChangeMarkup(change, "직전 대비")}</small></td>${targets}`;
    tbody.append(tr);
  });
  const metricKey = pref.metric === "PBR" ? "bps" : "eps";
  renderValuationRange(card.querySelector('[data-range="conservative"]'), stock, pref, rows.find((row) => row.conservative)?.basis);
  renderValuationRange(card.querySelector('[data-range="estimate"]'), stock, pref, stock.annual?.["2027"]?.[metricKey]);
  renderInvestorFlow(card, stock);

  card.querySelector(".metric-select").addEventListener("change", (event) => {
    setPreference(stock.code, { metric: event.target.value, multiples: DEFAULT_MULTIPLES[event.target.value] }); render();
    if (detail) openStockDetail(stock.code);
  });
  card.querySelector(".discount-input").addEventListener("change", (event) => {
    setPreference(stock.code, { discount: Math.min(150, Math.max(0, Number(event.target.value) || 0)) }); render();
    if (detail) openStockDetail(stock.code);
  });
  if (!detail) {
    card.querySelector(".remove-button").addEventListener("click", () => { setPreference(stock.code, { visible: false }); render(); });
    const moveBack = card.querySelector(".move-back");
    const moveForward = card.querySelector(".move-forward");
    moveBack.disabled = index === 0;
    moveForward.disabled = index === total - 1;
    moveBack.addEventListener("click", () => moveStock(stock.code, -1));
    moveForward.addEventListener("click", () => moveStock(stock.code, 1));
    const name = card.querySelector(".stock-name");
    name.setAttribute("role", "button");
    name.setAttribute("tabindex", "0");
    name.setAttribute("title", "상세 설정 열기");
    name.addEventListener("click", () => openStockDetail(stock.code));
    name.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openStockDetail(stock.code);
      }
    });
  }
  return card;
}

const detailDialog = document.getElementById("detailDialog");
function openStockDetail(code) {
  const stock = dataset.stocks.find((item) => item.code === code);
  if (!stock) return;
  document.getElementById("detailContent").replaceChildren(renderCard(stock, 0, 1, true));
  if (!detailDialog.open) detailDialog.showModal();
}
document.querySelector(".detail-close").addEventListener("click", () => detailDialog.close());

function render() {
  const board = document.getElementById("board");
  board.replaceChildren();
  const visible = orderedStocks().filter((stock) => getPreference(stock).visible);
  visible.forEach((stock, index) => board.append(renderCard(stock, index, visible.length)));
  document.getElementById("stockCount").textContent = visible.length;
  document.getElementById("emptyState").hidden = visible.length !== 0;
  const positive = visible.filter((stock) => {
    const pref = getPreference(stock), row = calculateRows(stock, pref).find((item) => item.conservative);
    return row?.basis && row.basis * pref.multiples[0] > stock.price;
  }).length;
  document.getElementById("upsideCount").textContent = positive;
}

async function init() {
  try {
    if (window.__STOCK_DATA__) {
      dataset = window.__STOCK_DATA__;
    } else {
      const response = await fetch("data/stocks.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      dataset = await response.json();
    }
    document.getElementById("updatedAt").textContent = new Date(dataset.generatedAt).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
    if (dataset.failures?.length) {
      const notice = document.getElementById("notice");
      const preserved = dataset.failures.filter((failure) => failure.preserved).length;
      const excluded = dataset.failures.length - preserved;
      const messages = [];
      if (preserved) messages.push(`${preserved}개 종목은 최신 수집에 실패해 이전 데이터를 표시합니다.`);
      if (excluded) messages.push(`${excluded}개 종목은 이전 데이터가 없어 제외되었습니다.`);
      notice.hidden = false; notice.textContent = messages.join(" ");
    }
    render();
  } catch (error) {
    const notice = document.getElementById("notice"); notice.hidden = false;
    notice.textContent = "데이터를 불러오지 못했습니다. 로컬에서는 파일을 직접 열지 말고 간이 웹 서버로 실행해 주세요.";
  }
}

const dialog = document.getElementById("addDialog");
const stockSearch = document.getElementById("stockSearch");

function addVisibleStock(code) {
  setPreference(code, { visible: true });
  render();
  dialog.close();
}

function renderAvailableStocks(query = "") {
  const list = document.getElementById("availableStocks");
  const normalized = query.trim().toLocaleLowerCase("ko-KR");
  const matches = dataset.stocks
    .filter((stock) => !normalized || stock.name.toLocaleLowerCase("ko-KR").includes(normalized) || stock.code.includes(normalized))
    .sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));

  list.replaceChildren();
  matches.forEach((stock) => {
    const visible = getPreference(stock).visible;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "available-stock";
    button.disabled = visible;
    button.innerHTML = `<span><strong></strong><small></small></span><em></em>`;
    button.querySelector("strong").textContent = stock.name;
    button.querySelector("small").textContent = stock.code;
    button.querySelector("em").textContent = visible ? "표시 중" : "추가";
    button.addEventListener("click", () => addVisibleStock(stock.code));
    list.append(button);
  });
  document.getElementById("availableStocksEmpty").hidden = matches.length !== 0;
}

document.getElementById("addStockButton").addEventListener("click", () => {
  document.getElementById("stockCode").value = "";
  stockSearch.value = "";
  document.getElementById("uncataloguedStock").hidden = true;
  renderAvailableStocks();
  dialog.showModal();
  stockSearch.focus();
});
stockSearch.addEventListener("input", (event) => renderAvailableStocks(event.target.value));
document.querySelectorAll(".dialog-close").forEach((button) => button.addEventListener("click", () => dialog.close()));
document.getElementById("addForm").addEventListener("submit", (event) => {
  const code = document.getElementById("stockCode").value.trim();
  const stock = dataset.stocks.find((item) => item.code === code);
  if (!stock) {
    event.preventDefault();
    document.getElementById("uncataloguedCode").textContent = code;
    document.getElementById("uncataloguedStock").hidden = false;
    return;
  }
  document.getElementById("uncataloguedStock").hidden = true;
  addVisibleStock(code);
});

init();
