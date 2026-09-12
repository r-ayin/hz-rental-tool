// 最小 CDP 客户端（Node 原生 WebSocket，无第三方依赖）
// 用法: node cdp_client.mjs <command> [args...]
//   targets                     列出 page targets
//   newtab <url>                新建标签页并导航，打印 targetId
//   eval <targetId> <expr>      在页面执行 JS 表达式，打印结果 JSON
//   navigate <targetId> <url>   导航
//   cookies <targetId>          打印该页面上下文的所有 cookie（含 HttpOnly）JSON
//   close <targetId>            关闭标签页
const BASE = process.env.CDP_BASE || "http://127.0.0.1:9222";

async function http(path, opts) {
  const res = await fetch(BASE + path, opts);
  return res.json();
}

function wsCall(wsUrl, method, params = {}) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = 1;
    const timer = setTimeout(() => { try { ws.close(); } catch {} reject(new Error("timeout")); }, 30000);
    ws.addEventListener("open", () => ws.send(JSON.stringify({ id, method, params })));
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === id) {
        clearTimeout(timer);
        try { ws.close(); } catch {}
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    });
    ws.addEventListener("error", (e) => { clearTimeout(timer); reject(new Error("ws error")); });
  });
}

const [cmd, ...args] = process.argv.slice(2);

if (cmd === "targets") {
  const list = await http("/json/list");
  console.log(JSON.stringify(list.filter(t => t.type === "page").map(t => ({ id: t.id, url: t.url, title: t.title })), null, 1));
} else if (cmd === "newtab") {
  const t = await http("/json/new?" + encodeURIComponent(args[0]), { method: "PUT" });
  console.log(JSON.stringify({ id: t.id, url: t.url }));
} else if (cmd === "navigate") {
  const list = await http("/json/list");
  const t = list.find(x => x.id === args[0]);
  await wsCall(t.webSocketDebuggerUrl, "Page.navigate", { url: args[1] });
  console.log("navigated");
} else if (cmd === "eval") {
  const list = await http("/json/list");
  const t = list.find(x => x.id === args[0]);
  const r = await wsCall(t.webSocketDebuggerUrl, "Runtime.evaluate", {
    expression: args[1], returnByValue: true, awaitPromise: true });
  console.log(JSON.stringify(r.result.value ?? r));
} else if (cmd === "cookies") {
  const list = await http("/json/list");
  const t = list.find(x => x.id === args[0]);
  const r = await wsCall(t.webSocketDebuggerUrl, "Network.getCookies", {});
  console.log(JSON.stringify(r.cookies));
} else if (cmd === "close") {
  await http("/json/close/" + args[0]);
  console.log("closed");
} else {
  console.error("unknown command");
  process.exit(1);
}
