import React, { useCallback, useEffect, useMemo, useState } from "react";
// File nay TU CHUA CA GIAO DIEN (CSS nam o cuoi file) -> chi can thay dung 1 file App.jsx.
// Nguon du lieu: Netlify Function (doc data/live_state.json tu repo GitHub).
// Chi khi chay thu tren may (npm run dev) moi dung file mau public/data/live_state.json;
// tren mang neu function loi thi BAO LOI, tuyet doi khong hien du lieu mau.
const IS_DEV = Boolean(import.meta.env?.DEV);
const SOURCES = IS_DEV ? ["/.netlify/functions/state", "/data/live_state.json"] : ["/.netlify/functions/state"];
const TRIGGER = -4;
const GAUGE_MIN = -6;
const GAUGE_MAX = 4;
const STALE_MIN = 130; // bot chay moi gio; qua ~2 gio khong cap nhat la co van de
const TIER = { H1: "H1", H4DOW: "4H theo thứ", H4DOM: "4H theo ngày" };
const DOW = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"];
const VN_MS = 7 * 3600 * 1000;

// ---------- thoi gian (state luu gio UTC khong kem mui gio) ----------
const utc = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z") : null);
const vn = (d) => new Date(d.getTime() + VN_MS); // doc bang getUTC* = gio VN
const pad = (n) => String(n).padStart(2, "0");
const hm = (d) => { const v = vn(d); return `${pad(v.getUTCHours())}:${pad(v.getUTCMinutes())}`; };
const dm = (d) => { const v = vn(d); return `${pad(v.getUTCDate())}/${pad(v.getUTCMonth() + 1)}`; };
const pyDow = (vnDate) => (vnDate.getUTCDay() + 6) % 7; // 0 = Thu 2, giong Python weekday()
const vnDayKey = (d) => vn(d).toISOString().slice(0, 10);

// Gio thi truong mo (UTC), giong bot: khong co nen thu 7, CN tu 21h, thu 6 den 21h
function hourOpen(ms) {
  const d = new Date(ms), wd = d.getUTCDay(), h = d.getUTCHours();
  return !(wd === 6 || (wd === 0 && h < 21) || (wd === 5 && h >= 22));
}
const barOpen = (ms, hours) => Array.from({ length: hours }, (_, k) => hourOpen(ms + k * 3600000)).some(Boolean);

function ago(d, now) {
  const m = Math.round((now - d) / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
}

const price = (x) => (x == null ? "–" : Math.abs(x) < 50 ? x.toFixed(5) : Math.abs(x) < 1000 ? x.toFixed(3) : x.toFixed(2));
const pct = (x, digits = 2) => `${x > 0 ? "+" : ""}${x.toFixed(digits)}%`;

function pipSize(pair) {
  if (pair === "XAUUSD") return 0.1;
  if (pair === "BTCUSD") return 1;
  return pair.endsWith("JPY") ? 0.01 : 0.0001;
}
const unit = (pair) => (pair === "BTCUSD" ? "điểm" : "pip");
const pipTxt = (pair, x, signed = false) => `${signed && x > 0 ? "+" : ""}${x.toFixed(1)} ${unit(pair)}`;

// Trang thai "sap chot" tinh lai tren app tu so lieu bot luu
function nearFlags(p) {
  const sign = p.direction === "Long" ? 1 : -1;
  const size = pipSize(p.pair);
  const slPips = p.sl_pips ?? Math.abs(p.entry_price - p.sl_price) / size;
  const toSl = (sign * (p.last_price - p.sl_price)) / size;
  const left = p.max_hold - p.bars_held;
  const w = p.last_wpr;
  return {
    pnl: (sign * (p.last_price - p.entry_price)) / size,
    toSl,
    slPips,
    left,
    wpr: w,
    nearWpr: w != null && (sign === 1 ? w > -35 : w < -65),
    nearTime: left <= (p.tf === "1h" ? 3 : 1),
    nearSl: toSl <= 0.25 * slPips,
  };
}

function floatingOf(p) {
  const sign = p.direction === "Long" ? 1 : -1;
  return (p.risk / p.sl_pct) * sign * ((p.last_price - p.entry_price) / p.entry_price) * 100;
}

// ---------- du lieu ----------
function useLiveState() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    let lastErr = null;
    for (const src of SOURCES) {
      try {
        const res = await fetch(`${src}?t=${Date.now()}`, { cache: "no-store" });
        const body = await res.json().catch(() => null);
        if (!res.ok || !body || body.error) { lastErr = body?.error || `Lỗi ${res.status} khi đọc ${src}`; continue; }
        setState(body); setError(null); setLoading(false);
        return;
      } catch (e) { lastErr = e.message; }
    }
    setError(lastErr); setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60000);
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(id); window.removeEventListener("focus", onFocus); };
  }, [load]);

  return { state, error, loading, reload: load };
}

function useNow() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 30000); return () => clearInterval(id); }, []);
  return now;
}

// ---------- thanh do floating ----------
function Gauge({ value, history }) {
  const pos = (v) => ((Math.min(Math.max(v, GAUGE_MIN), GAUGE_MAX) - GAUGE_MIN) / (GAUGE_MAX - GAUGE_MIN)) * 100;
  const tone = value <= TRIGGER ? "danger" : value <= TRIGGER / 2 ? "warn" : "ok";
  const last = history?.length ? history[history.length - 1] : null;
  const recent = (history || []).slice(-30);
  const maxAbs = Math.max(Math.abs(TRIGGER) * 1.25, ...recent.map((h) => Math.abs(h.floating)));
  const room = value - TRIGGER;

  return (
    <section className="gauge" aria-label="Floating toàn hệ thống">
      <div className="gauge-head">
        <span className={`gauge-value tone-${tone}`}>{pct(value)}</span>
        <span className="gauge-caption">
          Floating tạm tính của 60 leg, cách ngưỡng {room > 0 ? room.toFixed(2) : "0"} điểm
        </span>
      </div>
      <div className="gauge-track">
        <div className="gauge-danger" style={{ width: `${pos(TRIGGER)}%` }} />
        <div className="gauge-zero" style={{ left: `${pos(0)}%` }} />
        <div className={`gauge-marker tone-${tone}`} style={{ left: `${pos(value)}%` }} />
      </div>
      <div className="gauge-scale">
        <span>{GAUGE_MIN}%</span>
        <span style={{ left: `${pos(TRIGGER)}%` }} className="gauge-scale-mid">ngưỡng {TRIGGER}%</span>
        <span>+{GAUGE_MAX}%</span>
      </div>
      {recent.length > 0 && (
        <div className="spark" role="img" aria-label="Floating cuối ngày 30 ngày gần nhất">
          {recent.map((h) => {
            const hgt = (Math.abs(h.floating) / maxAbs) * 50;
            return (
              <div key={h.date} className="spark-col" title={`${h.date}: ${pct(h.floating)}`}>
                <div
                  className={`spark-bar ${h.floating < 0 ? "neg" : "pos"} ${h.floating <= TRIGGER ? "hit" : ""}`}
                  style={{ height: `${Math.max(hgt, 1.5)}%`, [h.floating < 0 ? "top" : "bottom"]: "50%" }}
                />
              </div>
            );
          })}
          <div className="spark-threshold" style={{ top: `${50 + (Math.abs(TRIGGER) / maxAbs) * 50}%` }} />
        </div>
      )}
      {last && (
        <p className="gauge-note">
          Chốt ngày {last.date.slice(8, 10)}/{last.date.slice(5, 7)}: <strong>{pct(last.floating)}</strong> (con số dùng để xét ngắt mạch)
        </p>
      )}
    </section>
  );
}

// ---------- lenh dang mo ----------
function Positions({ positions, now }) {
  if (!positions.length) return <p className="empty">Không có lệnh nào đang mở. Tín hiệu mới sẽ báo qua Telegram.</p>;
  const sorted = [...positions].sort((a, b) => (a.entry_time < b.entry_time ? 1 : -1));
  return (
    <ul className="rows">
      {sorted.map((p) => {
        const f = floatingOf(p);
        const n = nearFlags(p);
        const long = p.direction === "Long";
        return (
          <li key={p.id} className="row">
            <div className="row-main">
              <span className={`dir ${long ? "long" : "short"}`}>{long ? "Long" : "Short"}</span>
              <span className="pair">{p.pair}</span>
              <span className="tier">{TIER[p.tier]}</span>
              <span className={`row-value ${f >= 0 ? "up" : "down"}`}>{pct(f)}</span>
            </div>
            <div className="row-sub">
              <span>Vào {price(p.entry_price)}</span>
              <span>Hiện {price(p.last_price)}</span>
              <span className={n.pnl >= 0 ? "up" : "down"}>{pipTxt(p.pair, n.pnl, true)}</span>
            </div>
            <div className="row-sub">
              <span>SL {price(p.sl_price)}</span>
              <span className={n.nearSl ? "down" : "muted"}>còn {pipTxt(p.pair, Math.max(n.toSl, 0))} tới SL</span>
            </div>
            <div className="row-sub muted">
              <span>
                Chốt khi WPR {long ? "> -20" : "< -80"}
                {n.wpr != null ? ` (hiện ${n.wpr.toFixed(1)})` : ""}
              </span>
            </div>
            <div className="row-sub muted">
              <span>Vào {dm(utc(p.entry_time))} {hm(utc(p.entry_time))}</span>
              <span>
                {p.deadline ? `Chốt muộn nhất ~${dm(utc(p.deadline))} ${hm(utc(p.deadline))}` : `${n.left} nến còn lại`}
              </span>
            </div>
            <div className="hold"><div style={{ width: `${Math.min(100, (p.bars_held / p.max_hold) * 100)}%` }} /></div>
            {(n.nearWpr || n.nearTime || n.nearSl) && (
              <div className="flags">
                {n.nearWpr && <span className="flag">Sắp chốt theo WPR</span>}
                {n.nearTime && <span className="flag">Sắp hết giờ, còn {n.left} nến</span>}
                {n.nearSl && <span className="flag danger">Gần SL</span>}
              </div>
            )}
            {p.missed && !p.rebuilt && <div className="row-flag">Tín hiệu bỏ lỡ lúc bot gián đoạn.</div>}
            {p.rebuilt && <div className="row-note">Có từ trước khi bot chạy</div>}
          </li>
        );
      })}
    </ul>
  );
}

// ---------- lich ----------
function Schedule({ legs, now, pauseUntil }) {
  const [offset, setOffset] = useState(0);
  const day = new Date(vn(now).getTime() + offset * 86400000); // doc bang getUTC*
  const dow = pyDow(day);
  const dom = day.getUTCDate();
  const dayKey = day.toISOString().slice(0, 10);
  const paused = pauseUntil && dayKey <= pauseUntil;
  const nowHour = vn(now).getUTCHours();
  const vnMidnightUtc = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate()) - VN_MS;

  const h1 = useMemo(() => {
    const groups = {};
    legs
      .filter((l) => l.tier === "H1" && l.exclude_dow !== dow)
      .filter((l) => barOpen(vnMidnightUtc + l.entry_hour * 3600000, 1)) // bo gio thi truong dong cua
      .forEach((l) => {
        const h = (l.entry_hour + 1) % 24; // tin hieu bao khi nen gio vao DONG
        (groups[h] ||= []).push(l);
      });
    return Object.entries(groups).map(([h, ls]) => [Number(h), ls]).sort((a, b) => a[0] - b[0]);
  }, [legs, dow, vnMidnightUtc]);

  // Nen 4H cua ngay VN: mo luc 03,07,11,15,19,23h VN -> xet luc dong 07,11,15,19,23,03h
  const h4Checks = [0, 1, 2, 3, 4, 5]
    .map((k) => vnMidnightUtc + (3 + 4 * k) * 3600000)
    .filter((o) => barOpen(o, 4) && new Date(o).getUTCDay() !== 0)
    .map((o) => ({ hour: vn(new Date(o + 4 * 3600000)).getUTCHours(), past: o + 4 * 3600000 <= now.getTime() }));
  const h4 = h4Checks.length
    ? legs.filter((l) => (l.tier === "H4DOW" && l.dow === dow) || (l.tier === "H4DOM" && l.dom === dom))
    : [];

  return (
    <div>
      <div className="daypick" role="tablist" aria-label="Chọn ngày">
        {["Hôm nay", "Ngày mai"].map((t, i) => (
          <button key={t} role="tab" aria-selected={offset === i} className={offset === i ? "on" : ""} onClick={() => setOffset(i)}>
            {t}
          </button>
        ))}
        <span className="daypick-label">{DOW[dow]}, {pad(dom)}/{pad(day.getUTCMonth() + 1)}</span>
      </div>
      {paused && <p className="banner danger">Đang ngắt mạch: tín hiệu trong ngày này sẽ không được vào.</p>}

      <h3 className="sub">4H trong ngày</h3>
      {h4.length > 0 && (
        <p className="checks">
          Xét lúc{" "}
          {h4Checks.map((c, i) => (
            <span key={i} className={c.past ? "past" : ""}>{pad(c.hour)}h{i < h4Checks.length - 1 ? ", " : ""}</span>
          ))}
        </p>
      )}
      {h4.length ? (
        <ul className="rows">
          {h4.map((l) => (
            <li key={l.id} className="row">
              <div className="row-main">
                <span className={`dir ${l.direction === "Long" ? "long" : "short"}`}>{l.direction}</span>
                <span className="pair">{l.pair}</span>
                <span className="tier">{TIER[l.tier]}</span>
              </div>
              <div className="row-sub muted">
                <span>Vào khi WPR {l.direction === "Long" ? "<" : ">"} {l.threshold}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">Không có leg 4H nào trong ngày này.</p>
      )}

      <h3 className="sub">H1 theo giờ báo tín hiệu</h3>
      {h1.length === 0 && <p className="empty">Thị trường nghỉ, không có giờ xét H1.</p>}
      <ul className="timeline">
        {h1.map(([h, ls]) => {
          const past = offset === 0 && h <= nowHour;
          return (
            <li key={h} className={past ? "past" : ""}>
              <span className="tl-hour">{pad(h)}:00</span>
              <span className="tl-legs">
                {ls.map((l) => (
                  <span key={l.id} className={`chip ${l.direction === "Long" ? "long" : "short"}`}>
                    {l.pair} {l.direction === "Long" ? "L" : "S"}
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------- nhat ky ----------
function Events({ events }) {
  if (!events?.length) return <p className="empty">Chưa có sự kiện nào.</p>;
  return (
    <ul className="events">
      {[...events].reverse().slice(0, 60).map((e, i) => (
        <li key={i}>
          <time>{dm(utc(e.time))} {hm(utc(e.time))}</time>
          <span>{e.text}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------- trang chinh ----------
function Styles() {
  return <style>{APP_CSS}</style>;
}

export default function App() {
  const { state, error, loading, reload } = useLiveState();
  const now = useNow();
  const [tab, setTab] = useState("positions");

  if (!state) {
    return (
      <main className="app">
        <Styles />
        <p className={error ? "banner danger" : "empty"}>
          {error ? `Không đọc được trạng thái: ${error}` : "Đang tải trạng thái…"}
        </p>
        {error && <button className="refresh" onClick={reload}>Thử lại</button>}
      </main>
    );
  }

  const lastRun = utc(state.last_run);
  const stale = lastRun && now - lastRun > STALE_MIN * 60000;
  const todayKey = vnDayKey(now);
  const pu = state.pause_until;
  const paused = pu && todayKey <= pu;
  const positions = state.positions || [];

  return (
    <main className="app">
      <Styles />
      <header className="top">
        <div>
          <h1 className={paused ? "status danger" : "status"}>
            {paused ? `Ngắt mạch đến ${pu.slice(8, 10)}/${pu.slice(5, 7)}` : "Được vào lệnh"}
          </h1>
          <p className="updated">
            Bot cập nhật {lastRun ? ago(lastRun, now) : "chưa rõ"}
            {lastRun ? ` (${hm(lastRun)})` : ""}
          </p>
        </div>
        <button className="refresh" onClick={reload} disabled={loading}>
          {loading ? "Đang tải" : "Tải lại"}
        </button>
      </header>

      {stale && (
        <p className="banner warn">
          Bot chưa chạy từ {hm(lastRun)}. Kiểm tra cron-job.org và tab Actions trên GitHub.
        </p>
      )}
      {error && <p className="banner warn">Lần tải gần nhất lỗi ({error}), đang hiển thị dữ liệu cũ.</p>}

      <Gauge value={state.floating_now ?? 0} history={state.floating_history} />

      <nav className="tabs" role="tablist">
        {[
          ["positions", `Lệnh mở (${positions.length})`],
          ["schedule", "Lịch"],
          ["events", "Nhật ký"],
        ].map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "positions" && <Positions positions={positions} now={now} />}
      {tab === "schedule" && <Schedule legs={state.legs || []} now={now} pauseUntil={pu} />}
      {tab === "events" && <Events events={state.events} />}

      <footer className="foot">
        Bot không tự đặt lệnh. Đặt SL trên sàn ngay khi vào lệnh; bot chỉ báo thoát theo WPR và hết giờ.
      </footer>
    </main>
  );
}

const APP_CSS = `
:root {
  --bg: #E9EDF1;
  --surface: #F7F9FB;
  --ink: #1B2430;
  --muted: #5F6B78;
  --line: #D3DAE1;
  --long: #1F8A70;
  --short: #C8453A;
  --warn: #A96A12;
  --track: #D9DFE5;
  --font: "Be Vietnam Pro", system-ui, -apple-system, "Segoe UI", sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161C24;
    --surface: #1E2630;
    --ink: #E7ECF1;
    --muted: #93A0AD;
    --line: #2E3945;
    --long: #45B795;
    --short: #E0695E;
    --warn: #E0A53B;
    --track: #2B3541;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--ink); font-family: var(--font); }
body { -webkit-font-smoothing: antialiased; font-variant-numeric: tabular-nums; }
button { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }

.app {
  max-width: 560px;
  margin: 0 auto;
  padding: calc(18px + env(safe-area-inset-top, 0px)) 16px calc(28px + env(safe-area-inset-bottom, 0px));
}

/* ---------- dau trang ---------- */
.top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.status {
  margin: 0;
  font-size: 1.6rem;
  line-height: 1.15;
  font-weight: 700;
  letter-spacing: -0.015em;
}
.status.danger { color: var(--short); }
.updated { margin: 4px 0 0; font-size: 0.85rem; color: var(--muted); }
.refresh {
  flex-shrink: 0;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 999px;
  padding: 7px 14px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
}
.refresh:disabled { opacity: 0.6; cursor: default; }

.banner {
  margin: 0 0 12px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.88rem;
  line-height: 1.45;
  border-left: 4px solid currentColor;
  background: var(--surface);
}
.banner.warn { color: var(--warn); }
.banner.danger { color: var(--short); }

/* ---------- thanh do floating (diem nhan chinh) ---------- */
.gauge {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px 16px 12px;
  margin-bottom: 14px;
}
.gauge-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 2px 10px; margin-bottom: 12px; }
.gauge-value { font-size: 2.15rem; font-weight: 700; letter-spacing: -0.03em; line-height: 1; }
.gauge-caption { font-size: 0.85rem; color: var(--muted); line-height: 1.4; }
.tone-ok { color: var(--ink); }
.tone-warn { color: var(--warn); }
.tone-danger { color: var(--short); }

.gauge-track {
  position: relative;
  height: 10px;
  border-radius: 5px;
  background: var(--track);
}
.gauge-danger {
  position: absolute;
  inset: 0 auto 0 0;
  border-radius: 5px 0 0 5px;
  background: repeating-linear-gradient(-45deg,
    color-mix(in srgb, var(--short) 45%, transparent) 0 3px,
    transparent 3px 7px);
}
.gauge-zero {
  position: absolute;
  top: -4px;
  width: 2px;
  height: 18px;
  margin-left: -1px;
  background: var(--muted);
}
.gauge-marker {
  position: absolute;
  top: 50%;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  background: currentColor;
  border: 3px solid var(--surface);
  box-shadow: 0 0 0 1px var(--line);
  transition: left 0.4s ease;
}
.gauge-scale {
  position: relative;
  display: flex;
  justify-content: space-between;
  margin-top: 6px;
  font-size: 0.75rem;
  color: var(--muted);
}
.gauge-scale-mid { position: absolute; transform: translateX(-50%); color: var(--short); white-space: nowrap; }

.spark {
  position: relative;
  display: flex;
  gap: 2px;
  height: 40px;
  margin-top: 12px;
}
.spark-col { position: relative; flex: 1; }
.spark-bar { position: absolute; left: 0; right: 0; border-radius: 1px; }
.spark-bar.pos { background: color-mix(in srgb, var(--long) 70%, transparent); }
.spark-bar.neg { background: color-mix(in srgb, var(--ink) 35%, transparent); }
.spark-bar.hit { background: var(--short); }
.spark-threshold {
  position: absolute;
  left: 0;
  right: 0;
  border-top: 1px dashed var(--short);
  opacity: 0.7;
}
.gauge-note { margin: 10px 0 0; font-size: 0.82rem; line-height: 1.45; color: var(--muted); }
.gauge-note strong { color: var(--ink); font-weight: 600; }

/* ---------- tabs ---------- */
.tabs, .daypick {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 3px;
  padding: 3px;
  background: var(--track);
  border-radius: 11px;
  margin-bottom: 8px;
}
.tabs button, .daypick button {
  border: 1px solid transparent;
  background: transparent;
  border-radius: 8px;
  padding: 8px 4px;
  font-size: 0.88rem;
  white-space: nowrap;
  font-weight: 500;
  color: var(--muted);
  cursor: pointer;
}
.tabs button.on, .daypick button.on {
  background: var(--surface);
  border-color: var(--line);
  color: var(--ink);
  font-weight: 600;
}
.daypick { grid-template-columns: auto auto 1fr; align-items: center; margin-top: 6px; }
.daypick button { padding: 6px 12px; }
.daypick-label { justify-self: end; padding-right: 8px; font-size: 0.85rem; color: var(--muted); }

.sub { margin: 18px 0 2px; font-size: 0.95rem; font-weight: 600; }

/* ---------- danh sach ---------- */
.rows { list-style: none; margin: 0; padding: 0; }
.row { padding: 12px 2px; border-bottom: 1px solid var(--line); }
.row-main { display: flex; align-items: baseline; gap: 8px; }
.dir { font-size: 0.8rem; font-weight: 600; min-width: 2.6em; }
.dir::before {
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 5px;
  border-radius: 2px;
  background: currentColor;
  vertical-align: 1px;
}
.dir.long, .up { color: var(--long); }
.dir.short, .down { color: var(--short); }
.pair { font-size: 1.05rem; font-weight: 600; letter-spacing: 0.01em; }
.tier { font-size: 0.8rem; color: var(--muted); }
.row-value { margin-left: auto; font-weight: 600; }
.row-sub { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 5px; font-size: 0.85rem; }
.muted { color: var(--muted); }
.row-sub.muted { justify-content: space-between; }
.hold { height: 3px; margin-top: 8px; border-radius: 2px; background: var(--track); overflow: hidden; }
.hold > div { height: 100%; background: color-mix(in srgb, var(--ink) 45%, transparent); }
.row-flag { margin-top: 6px; font-size: 0.8rem; color: var(--warn); }
.row-note { margin-top: 6px; font-size: 0.78rem; color: var(--muted); }

.timeline { list-style: none; margin: 0; padding: 0; }
.timeline li {
  display: grid;
  grid-template-columns: 58px 1fr;
  gap: 8px;
  align-items: start;
  padding: 9px 2px;
  border-bottom: 1px solid var(--line);
}
.timeline li.past { opacity: 0.45; }
.tl-hour { font-weight: 600; padding-top: 2px; }
.tl-legs { display: flex; flex-wrap: wrap; gap: 5px; }
.chip {
  font-size: 0.8rem;
  font-weight: 500;
  padding: 2px 7px;
  border-radius: 6px;
  border: 1px solid currentColor;
}
.chip.long { color: var(--long); }
.chip.short { color: var(--short); }

.events { list-style: none; margin: 0; padding: 0; }
.events li {
  display: grid;
  grid-template-columns: 82px 1fr;
  gap: 8px;
  padding: 9px 2px;
  border-bottom: 1px solid var(--line);
  font-size: 0.85rem;
  line-height: 1.45;
}
.events time { color: var(--muted); }

.empty { color: var(--muted); font-size: 0.9rem; padding: 18px 2px; margin: 0; }
.foot { margin-top: 24px; font-size: 0.78rem; line-height: 1.5; color: var(--muted); }

.flags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.flag {
  font-size: 0.78rem;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 6px;
  color: var(--warn);
  background: color-mix(in srgb, var(--warn) 14%, transparent);
}
.flag.danger { color: var(--short); background: color-mix(in srgb, var(--short) 14%, transparent); }

.checks { margin: 4px 0 2px; font-size: 0.85rem; color: var(--muted); }
.checks .past { opacity: 0.45; }
`;
