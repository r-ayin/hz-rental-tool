/* 一秒选房采集 content script —— 运行在目标站点（*.zu.ke.com 族域名，城市可配置；用户已登录的浏览器内）。
 *
 * 列表页：浮动面板「采集本页 / 自动翻页 / 停止」
 *   - 采集本页：解析当前页全部房源卡片，批量 POST 到本地服务
 *   - 自动翻页：采集后自动跳转下一页（sessionStorage 记录进度，页面加载后自动续采）
 * 详情页：浮动面板「保存房源 / 导出TXT」
 */
(function initKeRentalCapture() {
  if (window.__keRentalCaptureLoaded) return;
  window.__keRentalCaptureLoaded = true;

  const AUTO_PAGE_KEY = "ke-rental-auto-page";
  const MAX_AUTO_PAGES = 30;

  const isDetailPage = /^\/(zufang|apartment)\/[A-Za-z0-9]+\.html/.test(location.pathname);

  const panel = document.createElement("div");
  panel.id = "ke-rental-capture-panel";
  Object.assign(panel.style, {
    position: "fixed",
    right: "22px",
    bottom: "92px",
    zIndex: "2147483647",
    display: "grid",
    gap: "8px",
    width: "112px",
    font: "700 14px/1.2 system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
  });

  function createFloatingButton(text, background) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    Object.assign(button.style, {
      width: "112px",
      height: "40px",
      border: "0",
      borderRadius: "999px",
      background,
      color: "#ffffff",
      boxShadow: "0 10px 28px rgba(0, 0, 0, 0.22)",
      cursor: "pointer",
      font: "700 14px/1.2 system-ui, -apple-system, BlinkMacSystemFont, sans-serif"
    });
    button.addEventListener("mouseenter", () => { button.style.filter = "brightness(0.92)"; });
    button.addEventListener("mouseleave", () => { button.style.filter = "none"; });
    return button;
  }

  function setButtonState(button, text, disabled) {
    button.textContent = text;
    button.disabled = disabled;
    button.style.opacity = disabled ? "0.75" : "1";
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /* 人类化延迟：区间内随机，避免机器节奏 */
  function humanDelay(minMs, maxMs) {
    return minMs + Math.random() * (maxMs - minMs);
  }

  /* 检测是否落到人机验证/拦截页：命中则停止自动化并提示 */
  function detectBlockPage() {
    const title = document.title || "";
    if (title.includes("人机") || (title.includes("验证") && !title.includes("登录"))) return true;
    return !!document.querySelector("#captcha, .verify-container");
  }

  /* 采集前模拟真人浏览：分段滚动阅读再回顶部 */
  async function simulateReading() {
    const steps = 3 + Math.floor(Math.random() * 3);
    for (let i = 0; i < steps; i += 1) {
      window.scrollBy({ top: window.innerHeight * (0.6 + Math.random() * 0.5), behavior: "smooth" });
      await sleep(260 + Math.random() * 420);
    }
    window.scrollTo({ top: 0, behavior: "smooth" });
    await sleep(200 + Math.random() * 300);
  }

  function normalizeLine(value) {
    return (value || "").replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
  }

  function reportError(context, error) {
    console.error(`[一秒选房采集] ${context}`, error);
    alert(`${context}失败：${error.message || error}\n\n请确认本地服务已启动：http://127.0.0.1:8765`);
  }

  async function saveHouses(houses) {
    await sleep(humanDelay(300, 900)); // 提交前停顿，贴近人工操作节奏
    const response = await browser.runtime.sendMessage({ type: "saveHousesToLocal", houses });
    if (!response || !response.ok) {
      throw new Error((response && response.error) || "本地服务未响应");
    }
    return response;
  }

  /* ---------- 列表页采集 ---------- */

  function parseListItem(item) {
    const titleLink = item.querySelector(".content__list--item--title a") ||
      item.querySelector("a.twoline") ||
      item.querySelector('.content__list--item--aside');
    const href = titleLink && titleLink.getAttribute("href");
    if (!href || !/\/(zufang|apartment)\/[A-Za-z0-9]+\.html/.test(href)) return null;

    const url = href.startsWith("http") ? href : location.origin + href;
    const title = normalizeLine(
      (item.querySelector(".content__list--item--title") && item.querySelector(".content__list--item--title").textContent) ||
      (titleLink && titleLink.getAttribute("title")) || ""
    );

    const priceEm = item.querySelector(".content__list--item-price em");
    const rentText = normalizeLine(priceEm && priceEm.textContent);
    const firstNumber = rentText.match(/[\d.]+/);

    const des = item.querySelector(".content__list--item--des");
    let district = "", bizcircle = "", community = "";
    let areaSqm = null, orientation = "", layout = "", floorDesc = "";
    if (des) {
      const links = Array.from(des.querySelectorAll('a[href*="/zufang/"]'))
        .map((link) => normalizeLine(link.textContent))
        .filter(Boolean);
      district = links[0] || "";
      bizcircle = links[1] || "";
      community = links[2] || "";

      const clone = des.cloneNode(true);
      clone.querySelectorAll("a").forEach((node) => node.remove());
      const parts = normalizeLine(clone.textContent).split("/").map(normalizeLine).filter(Boolean);
      for (const part of parts) {
        const areaMatch = part.match(/([\d.]+)㎡/);
        if (areaMatch && areaSqm === null) {
          areaSqm = parseFloat(areaMatch[1]);
        } else if (/^\d+室/.test(part) && !layout) {
          layout = part;
        } else if ((part.includes("楼层") || /（\d+层）/.test(part)) && !floorDesc) {
          floorDesc = part;
        } else if (/^[东南西北]{1,4}$/.test(part) && !orientation) {
          orientation = part;
        }
      }
    }
    if (!community && title.includes("·")) {
      community = title.split("·")[1].trim().split(" ")[0];
    }

    let rentType = "";
    if (title.includes("·")) {
      const prefix = title.split("·")[0].trim();
      if (["整租", "合租", "独栋", "公寓"].includes(prefix)) rentType = prefix;
    }

    const tags = Array.from(item.querySelectorAll('[class*="content__item__tag"]'))
      .map((tag) => normalizeLine(tag.textContent))
      .filter(Boolean);
    const depositTag = tags.find((tag) => tag.startsWith("押")) || "";

    const brand = normalizeLine((item.querySelector(".brand") || {}).textContent || "");
    const maintainTime = normalizeLine((item.querySelector(".content__list--item--time") || {}).textContent || "");
    const img = item.querySelector("img");
    const image = (img && (img.dataset.src || img.getAttribute("src"))) || "";

    return {
      source: "ke",
      url,
      houseCode: item.dataset.house_code || "",
      title,
      rentType,
      community,
      district,
      bizcircle,
      areaSqm,
      orientation,
      layout,
      floorDesc,
      rentMonthly: firstNumber ? Math.round(parseFloat(firstNumber[0])) : null,
      rentText,
      deposit: depositTag,
      tags,
      brand,
      image,
      maintainTime,
      capturedAt: new Date().toLocaleString()
    };
  }

  function collectListPage() {
    return Array.from(document.querySelectorAll(".content__list--item"))
      .map(parseListItem)
      .filter(Boolean);
  }

  function readPagination() {
    const nav = document.querySelector(".content__pg, [data-el='page_navigation']");
    if (!nav) return null;
    const curPage = parseInt(nav.dataset.curpage || nav.getAttribute("data-curPage") || "1", 10);
    const totalPage = parseInt(nav.dataset.totalpage || nav.getAttribute("data-totalPage") || "0", 10);
    const urlTemplate = nav.dataset.url || nav.getAttribute("data-url") || "";
    return { curPage, totalPage, urlTemplate };
  }

  function buildNextUrl(pagination) {
    if (!pagination) return "";
    const next = pagination.curPage + 1;
    if (!pagination.totalPage || next > pagination.totalPage || next > MAX_AUTO_PAGES + pagination.curPage) return "";
    if (pagination.urlTemplate.includes("{page}")) {
      return location.origin + pagination.urlTemplate.replace("{page}", String(next));
    }
    // 模板缺失时按站点惯例拼 pg token
    const path = location.pathname.replace(/pg\d+\/?/, "").replace(/\/$/, "");
    return `${location.origin}${path}/pg${next}/`;
  }

  async function captureCurrentListPage(button) {
    const houses = collectListPage();
    if (!houses.length) {
      setButtonState(button, "本页无房源", false);
      return 0;
    }
    await saveHouses(houses);
    return houses.length;
  }

  async function runAutoPaging(button) {
    if (detectBlockPage()) {
      alert("当前页面是人机验证/拦截页，已停止自动采集。请人工完成验证后重试。");
      return;
    }
    const pagination = readPagination();
    if (pagination) {
      sessionStorage.setItem(AUTO_PAGE_KEY, JSON.stringify({
        remain: Math.min(MAX_AUTO_PAGES, pagination.totalPage ? pagination.totalPage - pagination.curPage : MAX_AUTO_PAGES)
      }));
    } else {
      sessionStorage.setItem(AUTO_PAGE_KEY, JSON.stringify({ remain: MAX_AUTO_PAGES }));
    }
    setButtonState(button, "采集中", true);
    try {
      await simulateReading();
      const count = await captureCurrentListPage(button);
      setButtonState(button, `已采${count}条`, true);
      await sleep(humanDelay(2000, 4500));
      const nextUrl = buildNextUrl(readPagination());
      if (nextUrl && sessionStorage.getItem(AUTO_PAGE_KEY)) {
        setButtonState(button, "翻页中", true);
        location.href = nextUrl;
      } else {
        sessionStorage.removeItem(AUTO_PAGE_KEY);
        setButtonState(button, "采集完成", false);
      }
    } catch (error) {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
      setButtonState(button, "失败", false);
      reportError("自动翻页采集", error);
    }
  }

  async function resumeAutoPaging() {
    if (detectBlockPage()) {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
      return;
    }
    const raw = sessionStorage.getItem(AUTO_PAGE_KEY);
    if (!raw) return;
    let state;
    try {
      state = JSON.parse(raw);
    } catch {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
      return;
    }
    if (!state.remain || state.remain <= 0) {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
      return;
    }
    await sleep(humanDelay(1500, 3000));
    await simulateReading();
    const houses = collectListPage();
    if (houses.length) {
      try {
        await saveHouses(houses);
      } catch (error) {
        sessionStorage.removeItem(AUTO_PAGE_KEY);
        reportError("自动翻页续采", error);
        return;
      }
    }
    state.remain -= 1;
    sessionStorage.setItem(AUTO_PAGE_KEY, JSON.stringify(state));
    const nextUrl = buildNextUrl(readPagination());
    if (nextUrl && state.remain > 0) {
      location.href = nextUrl;
    } else {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
    }
  }

  /* ---------- 详情页采集 ---------- */

  function pickText(selectors) {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      if (element) {
        const text = normalizeLine(element.textContent);
        if (text) return text;
      }
    }
    return "";
  }

  function collectDetailInfoPairs() {
    // 详情页「房屋信息/租赁信息」多为 li 键值对（label + content），多组选择器兜底
    const pairs = {};
    const containers = document.querySelectorAll(
      ".content__article__info li, .content__detail--des li, [class*='info'] li, .baseattribute li, .introContent li"
    );
    containers.forEach((li) => {
      const label = li.querySelector(".label, .fl, [class*='label'], [class*='term']");
      const content = li.querySelector(".content, .fr, [class*='content'], [class*='value']");
      if (label && content) {
        const key = normalizeLine(label.textContent).replace(/[：:]$/, "");
        const value = normalizeLine(content.textContent);
        if (key && value && !(key in pairs)) pairs[key] = value;
      } else {
        const text = normalizeLine(li.textContent);
        const match = text.match(/^([^：:]{2,10})[：:]\s*(.+)$/);
        if (match && !(match[1] in pairs)) pairs[match[1]] = match[2];
      }
    });
    return pairs;
  }

  function collectDetailPage() {
    const title = pickText([
      ".content__detail--title", ".content__detail--header h1",
      ".house-title h1", "h1.content__detail--title", "h1",
      "[class*='detail--title']"
    ]) || document.title || "未命名房源";

    const priceRaw = pickText([
      ".content__detail--price", ".content__detail--rent",
      "[class*='detail--price']", "[class*='price'] .content__detail--price"
    ]);
    const priceMatch = priceRaw.match(/[\d.]+/);

    const pairs = collectDetailInfoPairs();
    const communityLink = document.querySelector(
      "a[href*='/zufang/c'], a[href*='/xiaoqu/'], .content__detail--community a, .content__info--map--community a"
    );

    const description = pickText([
      ".content__detail--des", ".content__article__des",
      "#js_content", "[class*='detail--des']", ".introduction .content"
    ]);

    const images = Array.from(document.querySelectorAll(
      ".content__detail--swiper img, .content__article__slide img, [class*='swiper'] img, .content__detail--pic img"
    )).map((img) => img.dataset.src || img.getAttribute("src") || "").filter(Boolean);

    const layout = pairs["户型"] || (title.match(/\d+室\d*厅?\d*卫?/) || [""])[0];
    const areaText = pairs["面积"] || pairs["建筑面积"] || "";
    const areaMatch = areaText.match(/([\d.]+)㎡/);

    let rentType = "";
    if (title.includes("·")) {
      const prefix = title.split("·")[0].trim();
      if (["整租", "合租", "独栋", "公寓"].includes(prefix)) rentType = prefix;
    }

    const tags = Array.from(document.querySelectorAll(
      ".content__detail--tag i, [class*='detail--tag'] i, .content__article__tag i"
    )).map((tag) => normalizeLine(tag.textContent)).filter(Boolean);

    return {
      source: "ke",
      url: location.href,
      title,
      rentType,
      community: normalizeLine((communityLink && (communityLink.getAttribute("title") || communityLink.textContent)) || "") || pairs["小区"] || "",
      district: pairs["区域"] || pairs["所在区域"] || "",
      bizcircle: pairs["商圈"] || pairs["所属商圈"] || "",
      areaSqm: areaMatch ? parseFloat(areaMatch[1]) : null,
      orientation: pairs["朝向"] || "",
      layout,
      floorDesc: pairs["楼层"] || "",
      rentMonthly: priceMatch ? Math.round(parseFloat(priceMatch[0])) : null,
      rentText: priceRaw,
      deposit: tags.find((tag) => tag.startsWith("押")) || pairs["付款方式"] || "",
      tags,
      brand: pickText([".content__detail--brand", "[class*='brand']"]),
      image: images[0] || "",
      images,
      maintainTime: pairs["维护时间"] || "",
      description: description || formatPairsAsDescription(pairs),
      infoPairs: pairs,
      capturedAt: new Date().toLocaleString()
    };
  }

  function formatPairsAsDescription(pairs) {
    return Object.entries(pairs).map(([key, value]) => `${key}：${value}`).join("\n");
  }

  function houseToText(house) {
    const lines = [
      `标题：${house.title}`,
      `月租：${house.rentText || (house.rentMonthly ? house.rentMonthly + "元/月" : "未知")}`,
      `小区：${house.community || "未知"}`,
      `区域：${[house.district, house.bizcircle].filter(Boolean).join("-") || "未知"}`,
      `户型：${house.layout || "未知"}  面积：${house.areaSqm ? house.areaSqm + "㎡" : "未知"}  朝向：${house.orientation || "未知"}`,
      `楼层：${house.floorDesc || "未知"}  付款：${house.deposit || "未知"}`,
      `标签：${(house.tags || []).join(" / ") || "无"}`,
      `链接：${house.url}`,
      "",
      "房源描述：",
      house.description || "（无）"
    ];
    return lines.join("\n");
  }

  /* ---------- 面板装配 ---------- */

  if (isDetailPage) {
    const saveButton = createFloatingButton("保存房源", "#e94853");
    const exportButton = createFloatingButton("导出TXT", "#475569");

    saveButton.addEventListener("click", async () => {
      setButtonState(saveButton, "整理中", true);
      try {
        const house = collectDetailPage();
        await saveHouses([house]);
        setButtonState(saveButton, "已保存", false);
      } catch (error) {
        setButtonState(saveButton, "失败", false);
        reportError("保存房源", error);
      } finally {
        setTimeout(() => setButtonState(saveButton, "保存房源", false), 1600);
      }
    });

    exportButton.addEventListener("click", () => {
      const house = collectDetailPage();
      browser.runtime.sendMessage({ type: "downloadHouseText", title: house.title, text: houseToText(house) });
    });

    panel.appendChild(saveButton);
    panel.appendChild(exportButton);
  } else {
    const captureButton = createFloatingButton("采集本页", "#2563eb");
    const autoButton = createFloatingButton("自动翻页", "#16a34a");
    const stopButton = createFloatingButton("停止", "#475569");

    captureButton.addEventListener("click", async () => {
      setButtonState(captureButton, "采集中", true);
      try {
        const count = await captureCurrentListPage(captureButton);
        setButtonState(captureButton, `已采${count}条`, false);
      } catch (error) {
        setButtonState(captureButton, "失败", false);
        reportError("采集本页", error);
      } finally {
        setTimeout(() => setButtonState(captureButton, "采集本页", false), 1600);
      }
    });

    autoButton.addEventListener("click", () => runAutoPaging(autoButton));

    stopButton.addEventListener("click", () => {
      sessionStorage.removeItem(AUTO_PAGE_KEY);
      setButtonState(autoButton, "已停止", false);
      setTimeout(() => setButtonState(autoButton, "自动翻页", false), 1200);
    });

    panel.appendChild(captureButton);
    panel.appendChild(autoButton);
    panel.appendChild(stopButton);

    // 自动翻页续采：从上一页跳转过来时继续
    resumeAutoPaging();
  }

  document.documentElement.appendChild(panel);
})();
