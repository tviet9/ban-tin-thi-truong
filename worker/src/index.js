// Web "Bản tin Thị trường" chạy trên Cloudflare Workers, đọc dữ liệu từ D1.
import TEMPLATE from "./template.html";

const SECTIONS = { kinh_te_vn: "Kinh tế trong nước", kinh_te_qt: "Kinh tế ngoài nước", chung_khoan: "Chứng khoán", crypto: "Crypto" };
const TAGS = { lai_suat: "Lãi suất", hop_bao: "Họp báo" };
const TOPICS = { crypto: "Crypto", chung_khoan: "Chứng khoán", kinh_te: "Kinh tế", lai_suat: "Lãi suất", hop_bao: "Họp báo" };
const WATCH_LABELS = { chain_moi: "Chain mới", launchpad: "Launchpad mới", nguoi: "Người theo dõi" };
const COOKIE = "bt_auth";

const vnDay = (d = new Date()) => new Date(d.getTime() + 7 * 3600e3).toISOString().slice(0, 10);
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });
const parse = (s, fb) => { try { return JSON.parse(s); } catch { return fb; } };

async function sign(secret) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode("ban-tin-ok"));
  return [...new Uint8Array(mac)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function page(title, body) {
  return `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title><style>
:root{--bg:#f3f5f7;--card:#fff;--ink:#151a22;--muted:#5d6675;--line:#dde2e9;--accent:#0a6c86}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--card:#171c23;--ink:#e7ebf0;--muted:#97a1af;--line:#2a313b;--accent:#4fb7d3;color-scheme:dark}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:16px}
form,.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px;width:min(360px,100%);display:flex;flex-direction:column;gap:12px}
h1{font-size:1.2rem;margin:0} p{margin:0;color:var(--muted);font-size:.9rem}
input{font:inherit;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--ink)}
button{font:inherit;font-weight:600;padding:9px;border:0;border-radius:8px;background:var(--accent);color:#fff;cursor:pointer}
.err{color:#c8283b}</style></head><body>${body}</body></html>`;
}

const loginPage = (err = "") => new Response(page("Đăng nhập · Bản tin Thị trường", `<form method="post" action="/login">
<h1>Bản tin Thị trường</h1><p>Nhập mật khẩu để xem.</p>
<input type="password" name="password" id="password" autocomplete="current-password" required autofocus>
${err ? `<p class="err">${err}</p>` : ""}<button type="submit">Vào</button></form>`), { status: err ? 401 : 200, headers: { "content-type": "text/html; charset=utf-8" } });

async function authed(req, env) {
  const c = req.headers.get("cookie") || "";
  const m = c.match(new RegExp(`${COOKIE}=([a-f0-9]{64})`));
  return !!m && m[1] === await sign(env.SITE_PASSWORD);
}

async function inChunks(db, sql, ids) {
  const out = [];
  for (let i = 0; i < ids.length; i += 90) {
    const part = ids.slice(i, i + 90);
    const r = await db.prepare(sql.replace("(?)", `(${part.map(() => "?").join(",")})`)).bind(...part).all();
    out.push(...r.results);
  }
  return out;
}

async function sources(db) {
  const r = await db.prepare("SELECT kind, value, title FROM sources ORDER BY created_at").all();
  const s = { telegram: [], websites: [], watch_senders: [] };
  for (const x of r.results) {
    if (x.kind === "telegram") s.telegram.push({ id: x.value, title: x.title });
    else if (x.kind === "website") s.websites.push({ url: x.value, title: x.title });
    else if (x.kind === "sender") s.watch_senders.push(x.value);
  }
  return s;
}

async function buildData(env, day) {
  const db = env.DB;
  const [dg, hrs, toks, wt, lk, st, days, last, src] = await Promise.all([
    db.prepare("SELECT data FROM digests WHERE day = ?").bind(day).first(),
    db.prepare("SELECT data FROM hours WHERE day = ? ORDER BY hour DESC").bind(day).all(),
    db.prepare("SELECT data FROM token_days WHERE day = ?").bind(day).all(),
    db.prepare("SELECT data FROM watch WHERE day = ? ORDER BY date DESC LIMIT 500").bind(day).all(),
    db.prepare("SELECT data FROM links WHERE day = ? ORDER BY date DESC LIMIT 300").bind(day).all(),
    db.prepare("SELECT data FROM stats WHERE day = ?").bind(day).first(),
    db.prepare("SELECT day FROM stats ORDER BY day DESC LIMIT 400").all(),
    db.prepare("SELECT value FROM state WHERE key = 'last_run'").first(),
    sources(db),
  ]);
  const digest = dg ? parse(dg.data, null) : null;
  const hours = hrs.results.map(r => parse(r.data, null)).filter(Boolean);
  const tokens = toks.results.map(r => parse(r.data, null)).filter(Boolean)
    .sort((a, b) => (b.mentions || 0) - (a.mentions || 0) || (b.liquidity_usd || 0) - (a.liquidity_usd || 0));
  const ids = new Set();
  for (const e of [...(digest?.events || []), ...hours.flatMap(h => h.events || [])]) for (const id of e.source_ids || []) ids.add(String(id));
  const msgs = {};
  for (const r of await inChunks(db, "SELECT uid, data FROM messages WHERE uid IN (?)", [...ids])) msgs[r.uid] = parse(r.data, {});
  const stats = st ? parse(st.data, {}) : {};
  return {
    generated_at: last ? parse(last.value, null) : null,
    sample: false, api: true, day, days: days.results.map(r => r.day),
    topics: TOPICS, sections: SECTIONS, tags: TAGS,
    groups: src.telegram.map(g => g.title || g.id).concat(src.websites.map(w => w.title || w.url)),
    stats: { total: stats.total || 0, kept: stats.kept || 0 },
    digest: digest || { overview: "Chưa có dữ liệu cho ngày này. Hệ thống cập nhật mỗi giờ.", events: [] },
    hours, tokens,
    links: lk.results.map(r => parse(r.data, null)).filter(Boolean),
    watch_labels: WATCH_LABELS,
    watch: wt.results.map(r => parse(r.data, null)).filter(Boolean),
    messages: msgs, sources: src,
  };
}

function render(data) {
  const payload = JSON.stringify(data).replace(/</g, "\\u003c");
  const html = TEMPLATE.replace("/*__DATA__*/null", () => payload);
  return `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><meta name="robots" content="noindex"></head><body>${html}</body></html>`;
}

async function handleSources(req, env) {
  const db = env.DB;
  if (req.method === "GET") return json({ sources: await sources(db) });
  const body = await req.json().catch(() => ({}));
  const kind = String(body.kind || ""), value = String(body.value || "").trim(), title = String(body.title || "").trim().slice(0, 100);
  if (!["telegram", "website", "sender"].includes(kind) || !value || value.length > 300) return json({ error: "Dữ liệu không hợp lệ" }, 400);
  if (kind === "telegram" && !/^(-100\d{6,}|@[A-Za-z0-9_]{4,})$/.test(value)) return json({ error: "ID nhóm phải dạng -100... hoặc @tennhom" }, 400);
  if (kind === "website" && !/^https?:\/\/[^\s]+$/.test(value)) return json({ error: "Link trang web phải bắt đầu bằng http(s)://" }, 400);
  if (kind === "sender" && !/^[A-Za-z0-9_]{3,}$/.test(value)) return json({ error: "Username chỉ gồm chữ, số, dấu _" }, 400);
  if (req.method === "POST") {
    await db.prepare("INSERT INTO sources (kind, value, title, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(kind, value) DO UPDATE SET title = excluded.title")
      .bind(kind, value, title || null, new Date().toISOString()).run();
  } else if (req.method === "DELETE") {
    await db.prepare("DELETE FROM sources WHERE kind = ? AND value = ?").bind(kind, value).run();
  } else return json({ error: "Phương thức không hỗ trợ" }, 405);
  return json({ sources: await sources(db) });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (!env.SITE_PASSWORD) return new Response(page("Chưa cài mật khẩu", `<div class="box"><h1>Chưa cài mật khẩu</h1><p>Thêm secret SITE_PASSWORD trong GitHub rồi chạy lại workflow Deploy.</p></div>`), { status: 503, headers: { "content-type": "text/html; charset=utf-8" } });
    if (url.pathname === "/login" && req.method === "POST") {
      const f = await req.formData();
      if (String(f.get("password") || "") !== env.SITE_PASSWORD) { await new Promise(r => setTimeout(r, 800)); return loginPage("Sai mật khẩu."); }
      return new Response(null, { status: 303, headers: { location: "/", "set-cookie": `${COOKIE}=${await sign(env.SITE_PASSWORD)}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=2592000` } });
    }
    if (url.pathname === "/logout") return new Response(null, { status: 303, headers: { location: "/", "set-cookie": `${COOKIE}=; Path=/; Max-Age=0` } });
    if (!(await authed(req, env))) return url.pathname.startsWith("/api/") ? json({ error: "Chưa đăng nhập" }, 401) : loginPage();
    if (url.pathname === "/api/sources") return handleSources(req, env);
    if (url.pathname === "/" || url.pathname === "/index.html") {
      const day = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get("day") || "") ? url.searchParams.get("day") : vnDay();
      return new Response(render(await buildData(env, day)), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    }
    return new Response("Không tìm thấy", { status: 404 });
  },
};
