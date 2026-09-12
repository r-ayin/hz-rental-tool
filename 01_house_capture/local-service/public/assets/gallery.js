/* 杭州租房画廊前端逻辑：加载本地房源库、筛选/排序/搜索、详情弹窗、服务端在线检索。 */
const themeKey = "rental-gallery-theme";
const cardGrid = document.querySelector("#cardGrid");
const statusEl = document.querySelector("#status");
const searchInput = document.querySelector("#searchInput");
const filterDistrict = document.querySelector("#filterDistrict");
const filterRooms = document.querySelector("#filterRooms");
const filterPrice = document.querySelector("#filterPrice");
const filterRentType = document.querySelector("#filterRentType");
const filterSort = document.querySelector("#filterSort");
const filterCount = document.querySelector("#filterCount");
const detailDialog = document.querySelector("#detailDialog");
const detailContent = document.querySelector("#detailContent");
const closeDialog = document.querySelector("#closeDialog");
const settingsToggle = document.querySelector("#settingsToggle");
const settingsPanel = document.querySelector("#settingsPanel");
const styleOptions = document.querySelectorAll(".style-option");
const crawlDialog = document.querySelector("#crawlDialog");
const crawlButton = document.querySelector("#crawlButton");
const crawlToggle = document.querySelector("#crawlToggle");
const closeCrawlDialog = document.querySelector("#closeCrawlDialog");
const crawlStart = document.querySelector("#crawlStart");
const crawlStatus = document.querySelector("#crawlStatus");
const statTotal = document.querySelector("#statTotal");
const statAvgRent = document.querySelector("#statAvgRent");

let meta = { districts: [], priceTiers: [], roomsOptions: [], sorts: [] };
let searchTimer = null;

function escapeHtml(value = "") {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[char]);
}

function compactText(value = "") {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function parseTags(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function parseImages(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw;
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function rentDisplay(house) {
  const text = compactText(house.rent_text);
  if (text && text !== String(house.rent_monthly)) return `${text} 元/月`;
  if (house.rent_monthly) return `${house.rent_monthly} 元/月`;
  return "租金待定";
}

function applyTheme(theme) {
  const safeTheme = theme === "glass1" ? "glass1" : "base1";
  document.body.dataset.theme = safeTheme;
  localStorage.setItem(themeKey, safeTheme);
  styleOptions.forEach((button) => {
    button.classList.toggle("active", button.dataset.theme === safeTheme);
  });
}

function fillSelect(select, options, keepFirst) {
  const first = keepFirst ? Array.from(select.options).slice(0, 1) : [];
  select.innerHTML = "";
  first.forEach((option) => select.appendChild(option));
  options.forEach(({ value, label }) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  });
}

async function loadMeta() {
  try {
    const response = await fetch("/api/meta");
    const data = await response.json();
    if (!data.ok) return;
    meta = data;
    fillSelect(filterDistrict, data.districts.map((d) => ({ value: d.name, label: d.name })), true);
    fillSelect(filterPrice, data.priceTiers.map((t) => ({ value: t.tier, label: t.label })), true);

    fillSelect(document.querySelector("#crawlDistrict"), data.districts.map((d) => ({ value: d.slug, label: d.name })), true);
    fillSelect(document.querySelector("#crawlPrice"), data.priceTiers.map((t) => ({ value: t.tier, label: t.label })), true);
    fillSelect(document.querySelector("#crawlRooms"), data.roomsOptions.map((r) => ({ value: r.value, label: r.label })), true);
    fillSelect(document.querySelector("#crawlSort"), (data.sorts || []).filter((s) => s.value).map((s) => ({ value: s.value, label: s.label })), true);

    if (data.hasCookie) {
      crawlStatus.textContent = "已检测到 data/cookie.txt";
    }
  } catch (error) {
    console.error("[rental-gallery] loadMeta failed", error);
  }
}

async function loadStats() {
  try {
    const response = await fetch("/api/stats");
    const data = await response.json();
    if (!data.ok) return;
    statTotal.textContent = data.total;
    statAvgRent.textContent = data.avg_rent ?? "-";
  } catch (error) {
    console.error("[rental-gallery] loadStats failed", error);
  }
}

function currentFilters() {
  const params = new URLSearchParams();
  const query = searchInput.value.trim();
  if (query) params.set("q", query);
  if (filterDistrict.value) params.set("district", filterDistrict.value);
  if (filterRooms.value) params.set("rooms", filterRooms.value);
  if (filterRentType.value) params.set("rentType", filterRentType.value);
  if (filterSort.value) params.set("sort", filterSort.value);
  const tier = meta.priceTiers?.find((t) => String(t.tier) === filterPrice.value);
  if (tier) {
    if (tier.min != null) params.set("minRent", tier.min);
    if (tier.max != null) params.set("maxRent", tier.max);
  }
  return params;
}

async function loadHouses() {
  try {
    statusEl.style.display = "block";
    statusEl.textContent = "正在读取本地房源库...";
    const response = await fetch(`/api/houses?${currentFilters().toString()}`);
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "读取失败");
    render(data.houses || []);
  } catch (error) {
    statusEl.style.display = "block";
    statusEl.textContent = `读取失败：${error.message || error}`;
    cardGrid.innerHTML = "";
  }
}

function houseCard(house) {
  const tags = parseTags(house.tags).slice(0, 4);
  const image = house.image || parseImages(house.images)[0] || "";
  const location = [house.district, house.bizcircle, house.community].filter(Boolean).join(" · ") || "位置待识别";
  const specs = [
    house.layout,
    house.area_sqm ? `${house.area_sqm}㎡` : "",
    house.orientation,
    house.floor_desc
  ].filter(Boolean).join(" | ");

  return `
  <article class="house-card" data-id="${house.id}" tabindex="0">
    <div class="card-cover">
      ${image
        ? `<img src="${escapeHtml(image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentNode.classList.add('no-image')" />`
        : ""}
      <span class="cover-rent">${escapeHtml(rentDisplay(house))}</span>
      ${house.rent_type ? `<span class="cover-type">${escapeHtml(house.rent_type)}</span>` : ""}
    </div>
    <div class="card-body">
      <h2 class="card-title" title="${escapeHtml(house.title)}">${escapeHtml(house.title || "未命名房源")}</h2>
      <p class="card-location">${escapeHtml(location)}</p>
      ${specs ? `<p class="card-specs">${escapeHtml(specs)}</p>` : ""}
      <div class="card-tags">
        ${tags.map((tag) => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join("")}
      </div>
      <div class="card-meta">
        <span class="brand">${escapeHtml(compactText(house.brand) || "个人房源")}</span>
        <span class="date">${escapeHtml(compactText(house.maintain_time) || "")}</span>
      </div>
    </div>
  </article>`;
}

function render(houses) {
  cachedHouses = houses;
  filterCount.textContent = `${houses.length} 套`;
  if (!houses.length) {
    statusEl.style.display = "block";
    statusEl.textContent = "没有匹配的房源。可用「在线检索贝壳」抓取，或在贝壳页面上用扩展采集。";
    cardGrid.innerHTML = "";
    return;
  }
  statusEl.style.display = "none";
  cardGrid.innerHTML = houses.map(houseCard).join("");
}

let cachedHouses = [];

async function openDetail(id) {
  try {
    // 优先用列表缓存，未命中再按当前筛选条件拉一次
    let house = cachedHouses.find((item) => String(item.id) === String(id));
    if (!house) {
      const response = await fetch(`/api/houses?${currentFilters().toString()}`);
      const data = await response.json();
      cachedHouses = data.houses || [];
      house = cachedHouses.find((item) => String(item.id) === String(id));
    }
    if (!house) return;
    renderDetail(house);
    detailDialog.showModal();
  } catch (error) {
    console.error("[rental-gallery] openDetail failed", error);
  }
}

function renderDetail(house) {
  const tags = parseTags(house.tags);
  const images = parseImages(house.images);
  if (!images.length && house.image) images.push(house.image);
  const specs = [
    ["户型", house.layout],
    ["面积", house.area_sqm ? `${house.area_sqm}㎡` : ""],
    ["朝向", house.orientation],
    ["楼层", house.floor_desc],
    ["付款方式", house.deposit],
    ["区域", [house.district, house.bizcircle].filter(Boolean).join(" - ")],
    ["小区", house.community],
    ["品牌/来源", compactText(house.brand)],
    ["维护时间", compactText(house.maintain_time)],
    ["采集时间", house.captured_at]
  ].filter(([, value]) => value);

  detailContent.innerHTML = `
    <header class="detail-header">
      <h1>${escapeHtml(house.title || "未命名房源")}</h1>
      <p class="detail-subtitle">
        <span class="detail-rent">${escapeHtml(rentDisplay(house))}</span>
        ${house.rent_type ? ` · ${escapeHtml(house.rent_type)}` : ""}
        ${house.community ? ` · ${escapeHtml(house.community)}` : ""}
      </p>
      ${house.url ? `<a class="open-link" href="${escapeHtml(house.url)}" target="_blank" rel="noreferrer">打开贝壳原始房源</a>` : ""}
    </header>

    ${images.length ? `<section class="detail-images">${images.slice(0, 6).map((src) =>
      `<img src="${escapeHtml(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'" />`).join("")}</section>` : ""}

    <section class="detail-section">
      <h3>房源信息</h3>
      <div class="spec-grid">
        ${specs.map(([label, value]) => `<div class="spec-item"><span class="spec-label">${escapeHtml(label)}</span><span class="spec-value">${escapeHtml(compactText(value))}</span></div>`).join("")}
      </div>
    </section>

    ${tags.length ? `<section class="detail-section"><h3>标签</h3><div class="card-tags">${tags.map((tag) => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join("")}</div></section>` : ""}

    <section class="detail-section">
      <h3>房源描述</h3>
      <p class="detail-desc">${escapeHtml(house.description || "暂无描述（详情页需登录后用扩展「保存房源」抓取）")}</p>
    </section>
  `;
}

async function runCrawl() {
  const payload = {
    district: document.querySelector("#crawlDistrict").value,
    priceTier: document.querySelector("#crawlPrice").value || null,
    rooms: document.querySelector("#crawlRooms").value === "" ? null : document.querySelector("#crawlRooms").value,
    rentType: document.querySelector("#crawlRentType").value,
    sort: document.querySelector("#crawlSort").value,
    keyword: document.querySelector("#crawlKeyword").value.trim(),
    pages: parseInt(document.querySelector("#crawlPages").value || "1", 10),
    cookie: document.querySelector("#crawlCookie").value.trim()
  };

  crawlStart.disabled = true;
  crawlStatus.textContent = "检索中，请稍候（每页间隔约1.5秒）...";
  try {
    const response = await fetch("/api/crawl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (data.ok) {
      crawlStatus.textContent = `完成：抓取 ${data.fetched} 条，入库 ${data.saved} 条（${data.pages?.length || 0} 页）`;
      await Promise.all([loadHouses(), loadStats()]);
    } else if (data.error === "login_required") {
      crawlStatus.innerHTML = `贝壳要求登录，本次未能抓取。${data.first_url ? `目标页：<a href="${escapeHtml(data.first_url)}" target="_blank" rel="noreferrer">${escapeHtml(data.first_url)}</a>` : ""}<br/>方案：① 粘贴已登录 Cookie 重试；② 在浏览器打开目标页，用扩展「采集本页/自动翻页」。`;
    } else {
      crawlStatus.textContent = `检索失败：${data.message || data.error || "未知错误"}`;
    }
  } catch (error) {
    crawlStatus.textContent = `检索失败：${error.message || error}`;
  } finally {
    crawlStart.disabled = false;
  }
}

/* ---------- 事件绑定 ---------- */

cardGrid.addEventListener("click", (event) => {
  const card = event.target.closest(".house-card");
  if (card) openDetail(card.dataset.id);
});

cardGrid.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const card = event.target.closest(".house-card");
  if (card) openDetail(card.dataset.id);
});

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadHouses, 320);
});

[filterDistrict, filterRooms, filterPrice, filterRentType, filterSort].forEach((select) => {
  select.addEventListener("change", loadHouses);
});

settingsToggle.addEventListener("click", () => {
  settingsPanel.classList.toggle("open");
  settingsToggle.classList.toggle("active", settingsPanel.classList.contains("open"));
});

styleOptions.forEach((button) => {
  button.addEventListener("click", () => applyTheme(button.dataset.theme));
});

function openCrawlDialog() {
  crawlDialog.showModal();
}

crawlButton.addEventListener("click", openCrawlDialog);
crawlToggle.addEventListener("click", openCrawlDialog);
closeCrawlDialog.addEventListener("click", () => crawlDialog.close());
crawlStart.addEventListener("click", runCrawl);
closeDialog.addEventListener("click", () => detailDialog.close());

applyTheme(localStorage.getItem(themeKey) || "base1");
(async function init() {
  await loadMeta();
  await Promise.all([loadHouses(), loadStats()]);
})();
