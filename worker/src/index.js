// Web "Bản tin Thị trường" chạy trên Cloudflare Workers, đọc dữ liệu từ D1.
import TEMPLATE from "./template.html";

const SECTIONS = { kinh_te_vn: "Kinh tế trong nước", kinh_te_qt: "Kinh tế ngoài nước", chung_khoan: "Chứng khoán", crypto: "Crypto" };
const TAGS = { lai_suat: "Lãi suất", hop_bao: "Họp báo" };
const TOPICS = { crypto: "Crypto", chung_khoan: "Chứng khoán", kinh_te: "Kinh tế", lai_suat: "Lãi suất", hop_bao: "Họp báo" };
const WATCH_LABELS = { chain_moi: "Chain mới", launchpad: "Launchpad mới", nguoi: "Người theo dõi" };

const vnDay = (d = new Date()) => new Date(d.getTime() + 7 * 3600e3).toISOString().slice(0, 10);
const json = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8" } });
const parse = (s, fb) => { try { return JSON.parse(s); } catch { return fb; } };

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
  const s = { telegram: [], websites: [], watch_senders: [], x: [], youtube: [] };
  for (const x of r.results) {
    if (x.kind === "telegram") s.telegram.push({ id: x.value, title: x.title });
    else if (x.kind === "website") s.websites.push({ url: x.value, title: x.title });
    else if (x.kind === "sender") s.watch_senders.push(x.value);
    else if (x.kind === "x") s.x.push({ url: x.value, title: x.title });
    else if (x.kind === "youtube") s.youtube.push({ url: x.value, title: x.title });
  }
  // trạng thái từng nguồn do bộ thu tin ghi (lần lấy được cuối, lỗi gần nhất)
  const h = await db.prepare("SELECT value FROM state WHERE key = 'source_health'").first();
  s.health = h ? parse(h.value, {}) : {};
  return s;
}

async function buildData(env, day) {
  const db = env.DB;
  const [dg, hrs, toks, wt, lk, st, xp, xt, days, last, src] = await Promise.all([
    db.prepare("SELECT data FROM digests WHERE day = ?").bind(day).first(),
    db.prepare("SELECT data FROM hours WHERE day = ? ORDER BY hour DESC").bind(day).all(),
    db.prepare("SELECT data FROM token_days WHERE day = ?").bind(day).all(),
    db.prepare("SELECT data FROM watch WHERE day = ? ORDER BY date DESC LIMIT 500").bind(day).all(),
    db.prepare("SELECT data FROM links WHERE day = ? ORDER BY date DESC LIMIT 300").bind(day).all(),
    db.prepare("SELECT data FROM stats WHERE day = ?").bind(day).first(),
    db.prepare("SELECT data FROM x_posts WHERE day = ? ORDER BY date DESC LIMIT 300").bind(day).all(),
    db.prepare("SELECT data FROM x_trend WHERE day = ?").bind(day).first(),
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
  // CA lưu trước khi có cột "Gửi lần đầu": tìm tin sớm nhất trong các tin đã nhắc CA đó
  const need = tokens.filter(t => !t.first_sender && (t.uids || []).length);
  const tm = {};
  for (const r of await inChunks(db, "SELECT uid, data FROM messages WHERE uid IN (?)", [...new Set(need.flatMap(t => t.uids.map(String)))])) tm[r.uid] = parse(r.data, {});
  for (const t of need) {
    const f = t.uids.map(u => tm[u]).filter(m => m && m.date).sort((a, b) => Date.parse(a.date) - Date.parse(b.date))[0];
    if (!f) continue;
    t.first_sender = f.username ? "@" + f.username : f.sender || null;
    t.first_group = t.first_group || f.group;
    t.first_seen = t.first_seen || f.date;
  }
  const stats = st ? parse(st.data, {}) : {};
  return {
    generated_at: last ? parse(last.value, null) : null,
    sample: false, api: true, day, days: days.results.map(r => r.day),
    topics: TOPICS, sections: SECTIONS, tags: TAGS,
    groups: src.telegram.map(g => g.title || g.id).concat(src.websites.map(w => w.title || w.url), src.x.map(x => "X · " + (x.title || "X")), src.youtube.map(y => "YouTube · " + (y.title || y.url))),
    stats: { total: stats.total || 0, kept: stats.kept || 0 },
    digest: digest || { overview: "Chưa có dữ liệu cho ngày này. Hệ thống cập nhật mỗi 20 phút.", events: [] },
    hours, tokens,
    links: lk.results.map(r => parse(r.data, null)).filter(Boolean),
    watch_labels: WATCH_LABELS,
    watch: wt.results.map(r => parse(r.data, null)).filter(Boolean),
    messages: msgs, sources: src,
    x_posts: xp.results.map(r => parse(r.data, null)).filter(Boolean),
    x_trend: xt ? parse(xt.data, []) : [],
  };
}

function render(data) {
  const payload = JSON.stringify(data).replace(/</g, "\\u003c");
  const html = TEMPLATE.replace("/*__DATA__*/null", () => payload);
  return `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content"><meta name="color-scheme" content="light dark"><meta name="robots" content="noindex"><meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)"><meta name="theme-color" content="#171c23" media="(prefers-color-scheme: dark)"></head><body>${html}</body></html>`;
}

// Không có mật khẩu, nhưng chỉ nhận yêu cầu ghi từ chính trang này (JSON, cùng nguồn) để trang web khác không gửi được
function badWrite(req) {
  const origin = req.headers.get("origin");
  if (origin && origin !== new URL(req.url).origin) return json({ error: "Không cho phép" }, 403);
  if (!(req.headers.get("content-type") || "").includes("application/json")) return json({ error: "Cần JSON" }, 415);
  return null;
}

// Gọi workflow cập nhật trên GitHub (dùng cho nút "Cập nhật ngay" và lịch chạy mỗi 20 phút của Cloudflare)
const dispatch = env => fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/hourly.yml/dispatches`, {
  method: "POST",
  headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json",
             "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ban-tin-worker", "Content-Type": "application/json" },
  body: JSON.stringify({ ref: "main" }),
});

const REFRESH_GAP_MIN = 10; // chống bấm liên tục làm cạn hạn mức AI miễn phí

async function handleRefresh(req, env) {
  const bad = badWrite(req);
  if (bad) return bad;
  if (!env.GH_TOKEN || !env.GH_REPO) return json({ error: "Chưa cài khoá GitHub (GH_DISPATCH_TOKEN) nên chưa cập nhật ngay được." }, 503);
  const db = env.DB;
  const prev = await db.prepare("SELECT value FROM state WHERE key = 'refresh_at'").first();
  const last = prev ? Date.parse(parse(prev.value, "")) : 0;
  const waitMin = Math.ceil(REFRESH_GAP_MIN - (Date.now() - last) / 60000);
  if (waitMin > 0) return json({ error: `Vừa có người bấm cập nhật. Thử lại sau ${waitMin} phút.` }, 429);
  const r = await dispatch(env);
  if (r.status !== 204) return json({ error: `GitHub từ chối (mã ${r.status}). Kiểm tra lại khoá GH_DISPATCH_TOKEN.` }, 502);
  await db.prepare("INSERT INTO state (key, value) VALUES ('refresh_at', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value")
    .bind(JSON.stringify(new Date().toISOString())).run();
  return json({ ok: true });
}

async function handleSources(req, env) {
  const db = env.DB;
  if (req.method === "GET") return json({ sources: await sources(db) });
  const bad = badWrite(req);
  if (bad) return bad;
  const body = await req.json().catch(() => ({}));
  const kind = String(body.kind || ""), value = String(body.value || "").trim(), title = String(body.title || "").trim().slice(0, 100);
  if (!["telegram", "website", "sender", "x", "youtube"].includes(kind) || !value || value.length > 300) return json({ error: "Dữ liệu không hợp lệ" }, 400);
  if (kind === "telegram" && !/^(-100\d{6,}|@[A-Za-z0-9_]{4,})$/.test(value)) return json({ error: "ID nhóm phải dạng -100... hoặc @tennhom" }, 400);
  if (kind === "website" && !/^https?:\/\/[^\s]+$/.test(value)) return json({ error: "Link trang web phải bắt đầu bằng http(s)://" }, 400);
  if (kind === "x" && !/^(list:\d+|@[A-Za-z0-9_]{1,15}|https?:\/\/\S+)$/.test(value)) return json({ error: "Nguồn X phải là link List (x.com/i/lists/...), @tài_khoản hoặc link RSS" }, 400);
  if (kind === "youtube" && !/^(UC[\w-]{22}|@[\w.-]{3,100})$/.test(value)) return json({ error: "Kênh YouTube phải là link kênh, @tên_kênh hoặc ID UC..." }, 400);
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
  // Lịch chạy Cloudflare (phút 07, 27, 47 mỗi giờ): đúng giờ hơn lịch của GitHub
  async scheduled(event, env) {
    const r = env.GH_TOKEN && env.GH_REPO ? await dispatch(env) : { status: 0 };
    // Ghi lại lần chạy lịch gần nhất để kiểm tra (xem ở /api/status)
    await env.DB.prepare("INSERT INTO state (key, value) VALUES ('cron_last', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value")
      .bind(JSON.stringify({ at: new Date().toISOString(), github_status: r.status })).run();
    if (r.status !== 204) throw new Error(`GitHub từ chối lịch chạy: ${r.status}`);
  },
  async fetch(req, env) {
    const url = new URL(req.url);
    // Không dùng mật khẩu (theo yêu cầu): ai có link đều xem và sửa nguồn được
    if (url.pathname === "/login" || url.pathname === "/logout") return Response.redirect(new URL("/", url), 303);
    if (url.pathname === "/api/sources") return handleSources(req, env);
    if (url.pathname === "/api/refresh" && req.method === "POST") return handleRefresh(req, env);
    if (url.pathname === "/api/status") {
      const r = await env.DB.prepare("SELECT value FROM state WHERE key = 'last_run'").first();
      const c = await env.DB.prepare("SELECT value FROM state WHERE key = 'cron_last'").first();
      return json({ last_run: r ? parse(r.value, null) : null, cron_last: c ? parse(c.value, null) : null,
                    refresh: !!(env.GH_TOKEN && env.GH_REPO) });
    }
    if (url.pathname === "/api/day") {  // dữ liệu một ngày, để trang tải thêm ngày cũ khi lướt xuống
      const d = url.searchParams.get("day") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return json({ error: "Ngày không hợp lệ" }, 400);
      return json(await buildData(env, d));
    }
    if (url.pathname === "/" || url.pathname === "/index.html") {
      const day = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get("day") || "") ? url.searchParams.get("day") : vnDay();
      return new Response(render(await buildData(env, day)), { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
    }
    return new Response("Không tìm thấy", { status: 404 });
  },
};
