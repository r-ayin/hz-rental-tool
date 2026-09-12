// 经用户浏览器 CDP 同源 fetch 详情页并提取图片 URL（规避 WAF：真实住宅 IP + 浏览器会话）
// 用法: node cdp_fetch_images.mjs <targetId> <urls.txt> <out.jsonl> [sleepMs]
import fs from "node:fs";

const BASE = process.env.CDP_BASE || "http://127.0.0.1:9222";
const [targetId, urlsFile, outFile, sleepMsArg] = process.argv.slice(2);
const sleepMs = parseInt(sleepMsArg || "2500", 10);
const urls = fs.readFileSync(urlsFile, "utf-8").split("\n").map(s => s.trim()).filter(Boolean);

const list = await (await fetch(BASE + "/json/list")).json();
const target = list.find(t => t.id === targetId);
if (!target) { console.error("target not found"); process.exit(1); }

function wsEval(wsUrl, expression) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = 1;
    const timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error("timeout")); }, 45000);
    ws.addEventListener("open", () => ws.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression, returnByValue: true, awaitPromise: true } })));
    ws.addEventListener("message", ev => {
      const msg = JSON.parse(ev.data);
      if (msg.id === id) {
        clearTimeout(timer); try { ws.close(); } catch {}
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result.result.value);
      }
    });
    ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("ws error")); });
  });
}

const out = fs.createWriteStream(outFile, { flags: "a" });
for (const url of urls) {
  const expr = `fetch(${JSON.stringify(url)}, {credentials: "include"}).then(r => r.ok ? r.text() : "HTTP" + r.status).then(t => { if (t.startsWith("HTTP")) return JSON.stringify({error: t}); const d = new DOMParser().parseFromString(t, "text/html"); const imgs = [...d.querySelectorAll("img")].map(i => i.dataset.src || i.src).filter(s => s && s.includes("ljcdn.com")).map(s => s.split("!")[0]); return JSON.stringify({images: [...new Set(imgs)].slice(0, 12), waf: t.includes("访问已被拦截")}); })`;
  try {
    const val = await wsEval(target.webSocketDebuggerUrl, expr);
    const parsed = typeof val === "string" ? JSON.parse(val) : (val || {});
    out.write(JSON.stringify({ url, ...parsed }) + "\n");
    console.log("ok", (parsed.images || []).length, url.slice(-30));
  } catch (e) {
    out.write(JSON.stringify({ url, error: String(e).slice(0, 80) }) + "\n");
    console.log("ERR", String(e).slice(0, 60), url.slice(-30));
  }
  await new Promise(r => setTimeout(r, sleepMs));
}
out.end();
console.log("CDP FETCH DONE");
