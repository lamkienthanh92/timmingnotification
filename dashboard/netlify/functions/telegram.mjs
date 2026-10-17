// Nhan lenh tu Telegram (webhook) va tra loi ngay. Doc trang thai 2 bot (FX va crypto) tu repo GitHub.
// Bien moi truong tren Netlify (Site configuration > Environment variables):
//   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (giong GitHub Secrets)
//   TG_WEBHOOK_SECRET    chuoi bi mat tu dat khi dang ky webhook (chong gia mao)
//   GITHUB_REPO, GITHUB_TOKEN_READ, GITHUB_BRANCH
//   TWELVE_DATA_API_KEY  (tuy chon) gia FX truc tiep de tinh tha noi
//   ACCOUNT_EQUITY, RISK_PCT (tuy chon) quy R ra USD
// Dang ky webhook (mo 1 lan tren trinh duyet):
//   https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<site>.netlify.app/.netlify/functions/telegram&secret_token=<TG_WEBHOOK_SECRET>

const sg = (x, d = 2) => `${x >= 0 ? "+" : ""}${x.toFixed(d)}`;
const fx5 = (x, pair) => (x == null ? "?" : pair && pair.endsWith("JPY") ? x.toFixed(3) : x.toFixed(5));
const cp = (x) => (x == null ? "?" : x >= 100 ? x.toFixed(2) : x >= 1 ? x.toFixed(4) : x.toPrecision(4));

async function readState(path) {
  const repo = process.env.GITHUB_REPO, branch = process.env.GITHUB_BRANCH || "main", token = process.env.GITHUB_TOKEN_READ;
  const headers = { Accept: "application/vnd.github.raw+json", "User-Agent": "tg-bot" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${encodeURIComponent(branch)}`, { headers });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  return JSON.parse(await r.text());
}

async function fxPrices(pairs) {
  const key = process.env.TWELVE_DATA_API_KEY, u = [...new Set(pairs)];
  if (!key || !u.length) return {};
  try {
    const j = await (await fetch(`https://api.twelvedata.com/price?symbol=${encodeURIComponent(u.join(","))}&apikey=${key}`)).json();
    const out = {};
    for (const s of u) { const v = u.length === 1 ? j : j[s]; if (v && v.price) out[s] = parseFloat(v.price); }
    return out;
  } catch { return {}; }
}

async function cryptoPrices(coins) {
  if (!coins.length) return {};
  try {
    const syms = JSON.stringify(coins.map((c) => c + "USDT"));
    const j = await (await fetch(`https://data-api.binance.vision/api/v3/ticker/price?symbols=${encodeURIComponent(syms)}`)).json();
    const out = {};
    for (const x of j || []) out[x.symbol.replace(/USDT$/, "")] = parseFloat(x.price);
    return out;
  } catch { return {}; }
}

async function fxText(st) {
  if (!st) return "FX: chưa có dữ liệu (bot FX chưa chạy lần nào).";
  const risk = parseFloat(process.env.RISK_PCT || "0.5"), eq = parseFloat(process.env.ACCOUNT_EQUITY || "0");
  const ps = st.positions || [], live = await fxPrices(ps.filter((p) => p.status === "mo").map((p) => p.pair));
  const L = [];
  const s = st.last_signal;
  if (s) {
    const rank = Object.entries(s.xep_hang).sort((a, b) => a[1] - b[1]).map(([c, v]) => `${c} ${sg(v, 1)}`).join("  ");
    L.push(`📅 <b>Tín hiệu tuần ${s.ngay}</b>${s.bo_tuan ? " · ⏸ bỏ tuần (tín hiệu yếu)" : ""}`);
    L.push(`Yếu → mạnh: ${rank}`);
    if ((s.tam_dung || []).length) L.push(`Tạm dừng: ${s.tam_dung.join(", ")}`);
  }
  let tot = 0;
  const mo = ps.filter((p) => p.status === "mo"), cho = ps.filter((p) => p.status !== "mo");
  L.push(`\n<b>Lệnh đang mở (${mo.length})</b>`);
  for (const p of mo) {
    const price = live[p.pair];
    const r = price != null ? (p.side * (price - p.entry)) / p.sl_dist : null;
    if (r != null) tot += r;
    L.push(`• ${p.side === 1 ? "MUA" : "BÁN"} ${p.pair} ${p.lots ?? ""} lot · vào ${fx5(p.entry, p.pair)} · SL ${fx5(p.sl, p.pair)} · TP ${fx5(p.tp, p.pair)}${r != null ? ` · <b>${sg(r)}R</b>` : ""}`);
  }
  if (!mo.length) L.push("(không có)");
  if (mo.length && Object.keys(live).length) L.push(`Thả nổi: <b>${sg(tot)}R</b> ≈ ${sg(tot * risk)}% vốn${eq > 0 ? ` ≈ ${sg((eq * tot * risk) / 100, 0)} USD` : ""}`);
  if (cho.length) L.push(`Chờ thứ Hai: ${cho.map((p) => `${p.status === "cho_vao" ? "vào" : "đóng"} ${p.pair}`).join(", ")}`);
  const cl = (st.closed || []).slice(-5).reverse();
  if (cl.length) L.push(`\n<b>5 lệnh đóng gần nhất</b>\n` + cl.map((x) => `• ${x.pair} ${x.side === 1 ? "MUA" : "BÁN"} ${x.exit_date} · ${x.ly_do} · ${sg(x.R)}R`).join("\n"));
  const cut = new Date(Date.now() - 91 * 864e5).toISOString().slice(0, 10);
  const r13 = (st.closed || []).filter((x) => x.exit_date > cut).reduce((a, x) => a + x.R, 0);
  L.push(`\n13 tuần gần nhất: ${sg(r13, 1)}R · rủi ro ${risk}%/lệnh`);
  return L.join("\n");
}

async function cryptoText(st) {
  if (!st) return "Crypto: chưa có dữ liệu (bot crypto chưa chạy lần nào).";
  const coins = Object.keys(st.dang_giu || {}), live = await cryptoPrices(coins);
  const L = [`🪙 <b>Crypto Spot</b> · top 10 tháng ${st.thang || "?"}: ${(st.top10 || []).join(", ")}`, `\n<b>Đang giữ (${coins.length}/10)</b>`];
  for (const c of coins.sort()) {
    const p = st.dang_giu[c], price = live[c];
    L.push(`• <b>${c}</b> mua ${cp(p.gia_vao)} ngày ${p.ngay_vao}${price ? ` · giá ${cp(price)} · <b>${sg((price / p.gia_vao - 1) * 100, 1)}%</b>` : ""}`);
  }
  if (!coins.length) L.push("(không có)");
  const ls = (st.lich_su || []).slice(-5).reverse();
  if (ls.length) L.push(`\n<b>5 lệnh bán gần nhất</b>\n` + ls.map((h) => `• ${h.coin} ${h.vao} → ${h.ra} · ${sg(h.lai_pct, 1)}%`).join("\n"));
  L.push(`\nQuy tắc: mua khi đóng cửa ngày cắt lên MA10 (trên MA30), bán khi đóng cửa dưới MA30.`);
  return L.join("\n");
}

const HELP = `Các lệnh:
<b>fx</b> — FX xếp hạng lực tiền tệ: tín hiệu tuần, lệnh đang mở (thả nổi), lệnh gần nhất
<b>crypto</b> — Crypto Spot top 10: đang giữ, lãi/lỗ hiện tại, lệnh gần nhất
<b>lệnh</b> (hoặc <b>tóm tắt</b>) — cả hai
<b>giúp</b> — danh sách lệnh`;

export default async (req) => {
  if (req.method !== "POST") return new Response("ok");
  const secret = process.env.TG_WEBHOOK_SECRET;
  if (secret && req.headers.get("x-telegram-bot-api-secret-token") !== secret) return new Response("forbidden", { status: 403 });
  let upd; try { upd = await req.json(); } catch { return new Response("ok"); }
  const msg = upd.message || upd.edited_message;
  if (!msg || !msg.text) return new Response("ok");
  if (String(msg.chat.id) !== String(process.env.TELEGRAM_CHAT_ID)) return new Response("ok");
  const t = msg.text.trim().toLowerCase().replace(/^\//, "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/đ/g, "d");
  let out;
  try {
    if (t.startsWith("fx") || t.startsWith("forex")) out = await fxText(await readState("data/fx_rank_state.json"));
    else if (t.startsWith("crypto") || t.startsWith("coin")) out = await cryptoText(await readState("data/crypto_ma_state.json"));
    else if (["lenh", "tom tat", "tomtat", "tk", "float", "status"].some((k) => t.startsWith(k))) {
      const [a, b] = await Promise.all([readState("data/fx_rank_state.json"), readState("data/crypto_ma_state.json")]);
      out = (await fxText(a)) + "\n\n━━━━━━━━━━\n\n" + (await cryptoText(b));
    } else out = HELP;
  } catch (e) { out = `⚠️ Lỗi: ${e.message || e}`; }
  await fetch(`https://api.telegram.org/bot${process.env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ chat_id: msg.chat.id, text: out.slice(0, 4000), parse_mode: "HTML", disable_web_page_preview: true }),
  });
  return new Response("ok");
};
