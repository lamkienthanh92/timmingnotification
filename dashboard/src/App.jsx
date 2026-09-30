import React, { useCallback, useEffect, useMemo, useState } from "react";
import "./App.css";

// Nguon du lieu: Netlify Function (doc repo GitHub). Khi chay local (npm run dev)
// khong co function -> dung file mau public/data/live_state.json.
const SOURCES = ["/.netlify/functions/state", "/data/live_state.json"];
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

function ago(d, now) {
  const m = Math.round((now - d) / 60000);
  if (m < 1) return "vừa xong";
  if (m < 60) return `${m} phút trước`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} giờ trước` : `${Math.floor(h / 24)} ngày trước`;
}

const price = (x) => (x == null ? "–" : Math.abs(x) < 50 ? x.toFixed(5) : Math.abs(x) < 1000 ? x.toFixed(3) : x.toFixed(2));
const pct = (x, digits = 2) => `${x > 0 ? "+" : ""}${x.toFixed(digits)}%`;

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
              <span>SL {price(p.sl_price)}</span>
              <span>Hiện {price(p.last_price)}</span>
            </div>
            <div className="row-sub muted">
              <span>{dm(utc(p.entry_time))} {hm(utc(p.entry_time))} ({ago(utc(p.entry_time), now)})</span>
              <span>{p.bars_held}/{p.max_hold} nến</span>
            </div>
            <div className="hold"><div style={{ width: `${Math.min(100, (p.bars_held / p.max_hold) * 100)}%` }} /></div>
            {p.missed && <div className="row-flag">Tín hiệu đến khi bot gián đoạn, chỉ để theo dõi.</div>}
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

  const h1 = useMemo(() => {
    const groups = {};
    legs.filter((l) => l.tier === "H1" && l.exclude_dow !== dow).forEach((l) => {
      const h = (l.entry_hour + 1) % 24; // tin hieu bao khi nen gio vao DONG
      (groups[h] ||= []).push(l);
    });
    return Object.entries(groups).map(([h, ls]) => [Number(h), ls]).sort((a, b) => a[0] - b[0]);
  }, [legs, dow]);

  const h4 = legs.filter((l) => (l.tier === "H4DOW" && l.dow === dow) || (l.tier === "H4DOM" && l.dom === dom));

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
                <span>Kiểm tra sau mỗi nến 4H đóng, WPR {l.direction === "Long" ? "<" : ">"} {l.threshold}</span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">Không có leg 4H nào trong ngày này.</p>
      )}

      <h3 className="sub">H1 theo giờ báo tín hiệu</h3>
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
export default function App() {
  const { state, error, loading, reload } = useLiveState();
  const now = useNow();
  const [tab, setTab] = useState("positions");

  if (!state) {
    return (
      <main className="app">
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
