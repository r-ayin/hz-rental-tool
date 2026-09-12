// 经用户浏览器 CDP 真实导航打开详情页（新标签→读图→关标签），最贴近真人浏览
// 用法: node cdp_nav_images.mjs <urls.txt> <out.jsonl> [waitMs]
import fs from "node:fs";

const BASE = process.env.CDP_BASE || "http://127.0.0.1:9222";
const [urlsFile, outFile, waitArg] = process.argv.slice(2);
const waitMs = parseInt(waitArg || "3500", 10);
const urls = fs.readFileSync(urlsFile, "utf-8").split("\n").map(s => s.trim()).filter(Boolean);

function wsCall(wsUrl, method, params = {}) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = 1;
    const timer = setTimeout(() => { setTimeout(() => process.exit(0), 200); reject(new Error("timeout")); }, 30000);
    ws.addEventListener("open", () => ws.send(JSON.stringify({ id, method, params })));
    ws.addEventListener("message", ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id === id) {
        clearTimeout(timer);
        try { ws.close(); } catch {}
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
    ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("ws error")); });
  });
}

const version = await (await fetch(BASE + "/json/version")).json();
const browserWs = version.webSocketDebuggerUrl;
const out = fs.createWriteStream(outFile, { flags: "a" });

for (const url of urls) {
  let targetId = null;
  try {
    const created = await wsCall(browserWs, "Target.createTarget", { url });
    targetId = created.targetId;
    await new Promise(r => setTimeout(r, waitMs));
    const list = await (await fetch(BASE + "/json/list")).json();
    const t = list.find(x => x.id === targetId);
    if (!t) throw new Error("target gone");
    const expr = `JSON.stringify({ title: document.title, waf: document.body.innerText.includes("访问已被拦截"), images: [...new Set([...document.images].map(i => i.dataset.src || i.src).filter(s => s && s.includes("ljcdn.com")).map(s => s.split("!")[0]))].slice(0, 12) })`;
    const val = await wsCall(t.webSocketDebuggerUrl, "Runtime.evaluate", { expression: expr, returnByValue: true });
    const parsed = typeof val.result.value === "string" ? JSON.parse(val.result.value) : (val.result.value || {});
    out.write(JSON.stringify({ url, ...parsed }) + "\n");
    console.log("ok", (parsed.images || []).length, String(parsed.title || "").slice(0, 14), url.slice(-26));
  } catch (e) {
    out.write(JSON.stringify({ url, error: String(e).slice(0, 80) }) + "\n");
    console.log("ERR", String(e).slice(0, 60), url.slice(-26));
  } finally {
    if (targetId) {
      try { await wsCall(browserWs, "Target.closeTarget", { targetId }); } catch {}
    }
  }
  await new Promise(r => setTimeout(r, 1500));
}
out.end();
console.log("NAV FETCH DONE");
