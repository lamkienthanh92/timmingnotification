import React, { useCallback, useEffect, useState } from "react";
// Dashboard danh muc v4 (A, B, BB, D, E). Tu chua CSS (cuoi file).
// Nguon du lieu: Netlify Function doc data/live_state.json tu repo GitHub (bot commit moi gio).
const IS_DEV = Boolean(import.meta.env?.DEV);
const SOURCES = IS_DEV ? ["/.netlify/functions/state", "/data/live_state.json"] : ["/.netlify/functions/state"];
const STALE_MIN = 130; // bot chay moi gio; qua ~2 gio khong cap nhat la co van de
const VN_MS = 7 * 3600 * 1000;
const NAME = {
  A: "A · mua sau bán tháo", B: "B · xu hướng JPY", C: "C · CUSUM short JPY", D: "D · đảo chiều sức mạnh",
  E: "E · lớp phụ 4H→1H", "BB BTC": "BB · squeeze BTC", "BB ETH": "BB · squeeze ETH", "BB SOL": "BB · squeeze SOL",
  "AQB XAU": "AQB · vàng", "AQB BTC": "AQB · BTC", "AQB ETH": "AQB · ETH", "AQB SOL": "AQB · SOL", "AQB DOGE": "AQB · DOGE",
};
const ORDER = ["A", "B", "C", "D", "E", "AQB XAU", "BB BTC", "BB ETH", "BB SOL", "AQB BTC", "AQB ETH", "AQB SOL", "AQB DOGE"];
const DOW = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];

const utc = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z") : null);
const pad = (n) => String(n).padStart(2, "0");
function vnTxt(s) {
  const d = utc(s); if (!d) return "–";
  const v = new Date(d.getTime() + VN_MS);
  return `${pad(v.getUTCHours())}:${pad(v.getUTCMinutes())} ${DOW[v.getUTCDay()]} ${pad(v.getUTCDate())}/${pad(v.getUTCMonth() + 1)}`;
}
function ago(d, now) {
  const m = Math.round((now - d) / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
}
const price = (x) => (x == null ? "–" : Math.abs(x) < 50 ? x.toFixed(5) : Math.abs(x) < 1000 ? x.toFixed(3) : x.toFixed(2));
const signed = (x, d = 2, unit = "") => (x == null ? "–" : `${x > 0 ? "+" : ""}${x.toFixed(d)}${unit}`);
const tone = (x) => (x > 0 ? "up" : x < 0 ? "down" : "");
const sortPos = (a, b) => (ORDER.indexOf(a.he) - ORDER.indexOf(b.he)) || a.pair.localeCompare(b.pair);

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

function Dir({ side }) {
  return <span className={`dir ${side === 1 ? "long" : "short"}`}>{side === 1 ? "LONG" : "SHORT"}</span>;
}

function PositionRow({ p, risk }) {
  const detail = [];
  detail.push(<span key="v">Vào <b>{price(p.gia_vao)}</b> · {vnTxt(p.vao)}</span>);
  if (p.sl != null) detail.push(<span key="sl">SL <b>{price(p.sl)}</b></span>);
  if (p.tp != null) detail.push(<span key="tp">TP <b>{price(p.tp)}</b></span>);
  if (p.he === "A") detail.push(<span key="a">Còn {p.con_ngay ?? "?"} ngày, đóng ở giá đóng cửa</span>);
  if (p.he === "D") detail.push(<span key="d">Độ lệch {signed(p.do_lech, 2)} · thoát khi &lt; 1 · đã giữ {p.tuoi ?? 0} ngày</span>);
  if (p.he === "A" || p.he === "D") detail.push(<span key="n" className="muted">SL cố định · 1 ATR ngày = {price(p.rui_ro)}</span>);
  const flag = p.he === "D" && p.thoat ? "Đã có tín hiệu thoát — đóng ở giá mở phiên kế tiếp" :
    p.he === "A" && p.con_ngay === 1 ? "Hôm nay là ngày giữ cuối" : null;
  return (
    <li className="row">
      <div className="row-main">
        <Dir side={p.side} />
        <span className="pair">{p.pair}</span>
        <span className="tier">{NAME[p.he] || p.he}</span>
        <span className={`row-value ${tone(p.r_now)}`}>{signed(p.r_now, 2, "R")}</span>
      </div>
      <div className="row-sub">{detail}</div>
      <div className="row-sub muted">
        <span>Giá hiện tại {price(p.last)}</span>
        <span>{signed(p.pct_now, 2, "% vốn")} · rủi ro {risk?.[p.he] ?? "?"}%</span>
      </div>
      {flag && <div className="row-flag">{flag}</div>}
    </li>
  );
}

function PendingRow({ q }) {
  return (
    <li className="row">
      <div className="row-main">
        <Dir side={q.side} />
        <span className="pair">{q.pair}</span>
        <span className="tier">{NAME[q.he] || q.he}</span>
      </div>
      <div className="row-sub">
        <span>Vào lúc {vnTxt(q.t_vao)}</span>
        {q.sl != null && <span>SL <b>{price(q.sl)}</b></span>}
        {q.tp != null && <span>TP <b>{price(q.tp)}</b></span>}
        {q.rr != null && <span>RR {q.rr.toFixed(1)}</span>}
      </div>
    </li>
  );
}

function ClosedRow({ c, risk }) {
  return (
    <li className="row">
      <div className="row-main">
        <Dir side={c.side} />
        <span className="pair">{c.pair}</span>
        <span className="tier">{NAME[c.he] || c.he}</span>
        <span className={`row-value ${tone(c.R)}`}>{signed(c.R, 2, "R")}</span>
      </div>
      <div className="row-sub muted">
        <span>{price(c.gia_vao)} → {price(c.gia_ra)}</span>
        <span>{vnTxt(c.vao)} → {vnTxt(c.ra)}</span>
        <span>{signed((c.R || 0) * (risk?.[c.he] ?? 0), 2, "% vốn")}</span>
      </div>
    </li>
  );
}

export default function App() {
  const { state, error, loading, reload } = useLiveState();
  const now = useNow();
  const [tab, setTab] = useState("open");

  if (!state) {
    return (
      <main className="app">
        <Styles />
        <div className="top">
          <div><h1 className="status">{error ? "Không đọc được dữ liệu" : "Đang tải…"}</h1>
            {error && <p className="updated">{error}</p>}</div>
          <button className="refresh" onClick={reload} disabled={loading}>Tải lại</button>
        </div>
      </main>
    );
  }

  const lastRun = utc(state.last_run);
  const staleMin = lastRun ? (now - lastRun) / 60000 : Infinity;
  const pos = [...(state.positions || [])].sort(sortPos);
  const pend = [...(state.pending || [])].sort(sortPos);
  const closed = [...(state.closed || [])].reverse().slice(0, 60);
  const events = [...(state.events || [])].reverse().slice(0, 60);
  const fl = state.floating_now ?? 0;
  const rs = state.risk_state || {};
  const paused = rs.sleeve_paused || [];
  const floatPause = rs.float_pause_until && utc(rs.float_pause_until) > now;
  const tabs = [["open", `Đang mở (${pos.length})`], ["pending", `Chờ vào (${pend.length})`],
    ["closed", "Đã chốt"], ["log", "Nhật ký"]];

  return (
    <main className="app">
      <Styles />
      <div className="top">
        <div>
          <h1 className="status">{pos.length ? `${pos.length} lệnh đang mở` : "Không có lệnh mở"}</h1>
          <p className="updated">Cập nhật {lastRun ? ago(lastRun, now) : "–"} · tạm tính{" "}
            <b className={tone(fl)}>{signed(fl, 2, "% vốn")}</b></p>
          <p className="updated">Rủi ro mở {(rs.open_risk ?? 0).toFixed(2)}% / 4% · crypto {rs.crypto_open ?? 0}/6 · từ đỉnh {signed(rs.dd ?? 0, 2, "%")}</p>
        </div>
        <button className="refresh" onClick={reload} disabled={loading}>{loading ? "…" : "Tải lại"}</button>
      </div>

      {staleMin > STALE_MIN && (
        <p className="banner danger">Bot chưa cập nhật hơn {Math.round(staleMin / 60)} giờ — kiểm tra GitHub Actions.</p>)}
      {rs.dd_stop && <p className="banner danger">HỆ THỐNG ĐÃ DỪNG: sụt giảm ≥ 20% từ đỉnh. Không vào lệnh mới — đánh giá lại chiến lược.</p>}
      {floatPause && <p className="banner danger">Ngắt mạch thả nổi: đã đóng tất cả lệnh, nghỉ đến {vnTxt(rs.float_pause_until)}.</p>}
      {paused.length > 0 && <p className="banner warn">Ngắt mạch tháng: dừng vào lệnh mới phần {paused.map((k) => (k === "FX" ? "FX (B, D, E)" : k)).join(", ")} đến hết tháng.</p>}
      {state.b_regime != null && state.b_regime < 0 && (state.parts || []).includes("B") && (
        <p className="banner warn">Chỉ báo chế độ B đang âm ({signed(state.b_regime, 1, "R")} trong 12 tháng) — cân nhắc giảm khối lượng B.</p>)}

      <nav className="tabs">
        {tabs.map(([k, label]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>))}
      </nav>

      {tab === "open" && (pos.length ? <ul className="rows">{pos.map((p) => <PositionRow key={p.id} p={p} risk={state.risk} />)}</ul>
        : <p className="empty">Không có lệnh nào đang mở.</p>)}
      {tab === "pending" && (pend.length ? <ul className="rows">{pend.map((q, i) => <PendingRow key={i} q={q} />)}</ul>
        : <p className="empty">Không có tín hiệu chờ vào.</p>)}
      {tab === "closed" && (closed.length ? <ul className="rows">{closed.map((c) => <ClosedRow key={c.id} c={c} risk={state.risk} />)}</ul>
        : <p className="empty">Chưa có lệnh nào chốt kể từ khi bot chạy.</p>)}
      {tab === "log" && (events.length ? (
        <ul className="events">{events.map((e, i) => <li key={i}><time>{vnTxt(e.time)}</time><span>{e.text}</span></li>)}</ul>)
        : <p className="empty">Chưa có sự kiện.</p>)}

      <footer className="foot">
        <p>Thành phần: {(state.parts || []).join(", ")} · rủi ro/lệnh: {Object.entries(state.risk || {})
          .filter(([k]) => (state.parts || []).some((p) => k === p || k.startsWith(p + " "))).map(([k, v]) => `${k} ${v}%`).join(", ")}</p>
        {state.e_watch?.length > 0 && <p>E đang theo dõi mỗi giờ: {state.e_watch.join(", ")}</p>}
        <p>Lấy mẫu: BTC, ETH, SOL, DOGE, vàng mỗi giờ · 25 cặp forex mỗi 4 giờ (07, 11, 15, 19, 23, 03 giờ VN) · chốt tuần 05:00 sáng thứ Bảy.
          Lần chạy gần nhất lấy {state.last_fetch?.symbols?.length ?? 0} mã ({(state.last_fetch?.why || []).join(", ")}).
          Twelve Data hôm nay: {state.credits?.n ?? 0} lượt.</p>
        <p>Bot không đặt lệnh. Mọi lệnh có SL — đặt trên sàn ngay khi vào; B, C, BB, AQB dời SL khi bot báo.
          Giới hạn: rủi ro mở ≤ 4%, crypto ≤ 6 lệnh, A ≤ 2 lệnh/đồng tiền. Ngắt mạch: phần FX lỗ tháng ≥ 1%, phần A ≥ 3%, thả nổi ≥ 3%, sụt giảm ≥ 20%.</p>
      </footer>
    </main>
  );
}

function Styles() {
  return <style>{APP_CSS}</style>;
}

const APP_CSS = `
.app { max-width: 560px; margin: 0 auto; padding: calc(18px + env(safe-area-inset-top, 0px)) 16px calc(28px + env(safe-area-inset-bottom, 0px)); }
.top { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.status { margin: 0; font-size: 1.6rem; line-height: 1.15; font-weight: 700; letter-spacing: -0.015em; }
.updated { margin: 4px 0 0; font-size: 0.88rem; color: var(--muted); }
.refresh { flex-shrink: 0; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 7px 14px; font-size: 0.85rem; font-weight: 500; cursor: pointer; }
.refresh:disabled { opacity: 0.6; cursor: default; }
.banner { margin: 0 0 12px; padding: 10px 12px; border-radius: 10px; font-size: 0.88rem; line-height: 1.45; border-left: 4px solid currentColor; background: var(--surface); }
.banner.warn { color: var(--warn); }
.banner.danger { color: var(--short); }
.tabs { display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px; background: var(--track); border-radius: 10px; padding: 3px; margin: 4px 0 6px; }
.tabs button { border: 0; background: transparent; border-radius: 8px; padding: 8px 4px; font-size: 0.82rem; font-weight: 500; cursor: pointer; color: var(--muted); }
.tabs button.on { background: var(--surface); color: var(--ink); font-weight: 600; box-shadow: 0 1px 2px rgba(0,0,0,0.08); }
.rows { list-style: none; margin: 0; padding: 0; }
.row { padding: 12px 2px; border-bottom: 1px solid var(--line); }
.row-main { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.dir { font-size: 0.75rem; font-weight: 700; min-width: 3.4em; }
.dir.long, .up { color: var(--long); }
.dir.short, .down { color: var(--short); }
.pair { font-size: 1.05rem; font-weight: 600; letter-spacing: 0.01em; }
.tier { font-size: 0.8rem; color: var(--muted); }
.row-value { margin-left: auto; font-weight: 700; }
.row-sub { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 5px; font-size: 0.85rem; }
.row-sub b { font-weight: 600; }
.muted, .row-sub.muted { color: var(--muted); }
.row-flag { margin-top: 6px; font-size: 0.8rem; font-weight: 600; color: var(--warn); }
.events { list-style: none; margin: 0; padding: 0; }
.events li { display: grid; grid-template-columns: 96px 1fr; gap: 8px; padding: 9px 2px; border-bottom: 1px solid var(--line); font-size: 0.84rem; line-height: 1.45; }
.events time { color: var(--muted); }
.empty { color: var(--muted); font-size: 0.9rem; padding: 18px 2px; margin: 0; }
.foot { margin-top: 24px; font-size: 0.78rem; line-height: 1.5; color: var(--muted); }
.foot p { margin: 0 0 6px; }
`;
