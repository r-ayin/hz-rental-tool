const SERVICE_URL = "http://127.0.0.1:8765/api/houses";

function safeFileName(value) {
  return (value || "house-detail")
    .replace(/[\\/:*?"<>|]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80) || "house-detail";
}

browser.runtime.onMessage.addListener((message) => {
  if (!message) {
    return undefined;
  }

  if (message.type === "saveHousesToLocal") {
    const houses = Array.isArray(message.houses) ? message.houses : [message.houses].filter(Boolean);
    if (!houses.length) {
      return Promise.resolve({ ok: false, error: "没有可保存的房源" });
    }
    return fetch(SERVICE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ houses })
    }).then(async (response) => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `本地服务返回 ${response.status}`);
      }
      return data;
    });
  }

  if (message.type !== "downloadHouseText") {
    return undefined;
  }

  const blob = new Blob([message.text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const filename = `房源-${safeFileName(message.title)}-${new Date().toISOString().slice(0, 10)}.txt`;

  return browser.downloads.download({
    url,
    filename,
    saveAs: true,
    conflictAction: "uniquify"
  }).finally(() => {
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  });
});
