// Thử Worker với D1 giả lập bằng node:sqlite. Chạy sau tests/test_hourly.py:
// node tests/test_worker.mjs <file sqlite> <file html xuất ra>
import { DatabaseSync } from "node:sqlite";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const [dbFile, outHtml] = process.argv.slice(2);
const tmp = path.join(path.dirname(outHtml), "worker_test_index.mjs");
const src = fs.readFileSync(path.join(root, "worker/src/index.js"), "utf8")
  .replace('import TEMPLATE from "./template.html";', `const TEMPLATE = ${JSON.stringify(fs.readFileSync(path.join(root, "web/template.html"), "utf8"))};`);
fs.writeFileSync(tmp, src);
const worker = (await import(pathToFileURL(tmp).href)).default;

const sql = new DatabaseSync(dbFile);
const stmt = (q) => {
  let args = [];
  const s = {
    bind: (...a) => { args = a; return s; },
    all: async () => ({ results: sql.prepare(q).all(...args) }),
    first: async () => sql.prepare(q).get(...args) ?? null,
    run: async () => { sql.prepare(q).run(...args); return { success: true }; },
  };
  return s;
};
const env = { DB: { prepare: stmt }, SITE_PASSWORD: "matkhau-thu" };
const call = (p, init = {}) => worker.fetch(new Request("https://x.workers.dev" + p, init), env);
const assert = (c, m) => { if (!c) { console.error("FAIL", m); process.exit(1); } };

let r;
const H = {};
r = await call("/", { headers: H });
const html = await r.text();
assert(r.status === 200 && html.includes("const DATA = {"), "trang chính có dữ liệu");
const data = JSON.parse(html.match(/const DATA = (\{.*?\});\n/s)[1]);
assert(data.api && data.digest.events.length > 0 && data.tokens.length === 2 && data.watch.length > 0, "dữ liệu đủ");
assert(Object.keys(data.messages).length > 0, "có tin gốc");
fs.writeFileSync(outHtml, html);

r = await call("/api/sources", { method: "POST", headers: { ...H, "content-type": "application/json" }, body: JSON.stringify({ kind: "website", value: "https://vnexpress.net/rss/kinh-doanh.rss", title: "VnExpress" }) });
let j = await r.json();
assert(r.status === 200 && j.sources.websites.length === 1, "thêm trang web");
r = await call("/api/sources", { method: "POST", headers: { ...H, "content-type": "application/json" }, body: JSON.stringify({ kind: "telegram", value: "abc" }) });
assert(r.status === 400, "ID nhóm sai phải báo lỗi");
r = await call("/api/sources", { method: "DELETE", headers: { ...H, "content-type": "application/json" }, body: JSON.stringify({ kind: "website", value: "https://vnexpress.net/rss/kinh-doanh.rss" }) });
j = await r.json();
assert(j.sources.websites.length === 0, "xoá trang web");
r = await call("/?day=2020-01-01", { headers: H });
assert((await r.text()).includes("Chưa có dữ liệu cho ngày này"), "ngày trống");
r = await call("/api/refresh", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
assert(r.status === 503, "chưa có GH_TOKEN phải báo 503");
env.GH_TOKEN = "t"; env.GH_REPO = "o/r";
let dispatched = 0;
globalThis.fetch = async (u, init) => { dispatched++; assert(String(u).endsWith("/o/r/actions/workflows/hourly.yml/dispatches"), "sai URL"); return new Response(null, { status: 204 }); };
r = await call("/api/refresh", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
assert(r.status === 200 && dispatched === 1, "bấm lần 1 phải gọi GitHub");
r = await call("/api/refresh", { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
assert(r.status === 429 && dispatched === 1, "bấm lần 2 trong 10 phút phải bị chặn");
r = await call("/api/refresh", { method: "POST", headers: { "content-type": "application/json", origin: "https://evil.example" }, body: "{}" });
assert(r.status === 403, "trang khác không được bấm hộ");
r = await call("/api/status");
assert((await r.json()).refresh === true, "status");
console.log("test_worker OK", { events: data.digest.events.length, tokens: data.tokens.length, days: data.days });
