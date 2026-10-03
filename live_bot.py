"""
================================================================================
LIVE_BOT.PY - bot theo doi danh muc v4 (A, B, BB, D, E; C tuy chon), bao qua Telegram
================================================================================
Moi lan chay (khuyen nghi moi gio, phut :02):
  1. Lap ke hoach lay du lieu theo LICH LAY MAU (xem config.py):
       - moi gio: BTC, ETH (BB) + cap forex dang trong boi canh E / co lenh E mo
       - moi 4 gio (nen 4H dong): ca 25 cap forex -> B, C, E, A, D
       - thu Sau 22:00 UTC: nen cuoi tuan -> chot tin hieu A, D, B cho tuan sau
  2. Chi lay NEN H1 MOI (bo nho dem data/cache/*.csv.gz, giu bang GitHub Actions cache).
  3. Chay LAI DUNG engine backtest (portfolio_backtest.py) tren nen da dong:
       lenh dang mo / tin hieu cho vao / lenh da dong.
  4. So voi lan truoc -> bao Telegram: VAO, DOI SL, THOAT, DA CHOT, tom tat buoi sang.
  5. Luu data/live_state.json (dashboard doc file nay).

Bot KHONG dat lenh. Lenh co SL (B, C, E, BB) -> dat SL tren san ngay khi vao, doi SL khi bot bao.
================================================================================
"""
import html as _html
import json
import os
import re
import sys
import traceback

import numpy as np
import pandas as pd

import portfolio_backtest as eng
from config import (FX_PAIRS, CRYPTO_PAIRS, PARTS, NOTIFY_ONLY_PARTS, B_FILTER, FULL_EVERY_HOURS,
                    WEEK_CLOSE_HOUR_UTC, VN_OFFSET_HOURS, DAILY_SUMMARY_HOUR_VN, CACHE_DIR, CACHE_MAX_BARS,
                    BOOT_PAGES, STATE_FILE, SL_MOVE_MIN_R, SL_MOVE_MIN_HOURS, SPREAD_PCT)

VN = pd.Timedelta(hours=VN_OFFSET_HOURS)
H1 = pd.Timedelta(hours=1)
NAME = {"A": "A · mua sau bán tháo", "B": "B · xu hướng JPY", "C": "C · CUSUM short JPY",
        "D": "D · đảo chiều sức mạnh", "E": "E · lớp phụ 4H→1H", "BB BTC": "BB · squeeze BTC",
        "BB ETH": "BB · squeeze ETH"}
ORDER = ["A", "B", "C", "D", "E", "BB BTC", "BB ETH"]
DOW = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def part_of(he):
    return "BB" if he.startswith("BB") else he


# ------------------------------------------------------------------ Telegram (HTML)
TG_MAX_LEN = 3800
TG_SEP = "\n\n"


def _plain(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s))


def esc(s):
    return _html.escape(str(s), quote=False)


def _pack(blocks):
    """Gop cac khoi thanh tung tin <= TG_MAX_LEN, khong cat ngang 1 khoi."""
    out, buf = [], ""
    for b in blocks:
        if len(b) > TG_MAX_LEN:
            if buf:
                out.append(buf); buf = ""
            cur = ""
            for ln in _plain(b).split("\n"):
                if len(cur) + len(ln) + 1 > TG_MAX_LEN and cur:
                    out.append(esc(cur)); cur = ""
                cur += ln + "\n"
            if cur.strip():
                out.append(esc(cur))
            continue
        if buf and len(buf) + len(TG_SEP) + len(b) > TG_MAX_LEN:
            out.append(buf); buf = ""
        buf = b if not buf else buf + TG_SEP + b
    if buf:
        out.append(buf)
    return out


def send_blocks(blocks):
    import requests
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[Telegram chua cau hinh - chi in ra log]\n" + _plain(TG_SEP.join(blocks)))
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for msg in _pack(blocks):
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                                         "disable_web_page_preview": True}, timeout=15)
            if r.status_code == 400:              # Telegram tu choi dinh dang -> gui chu thuong
                r = requests.post(url, json={"chat_id": chat_id, "text": _plain(msg),
                                             "disable_web_page_preview": True}, timeout=15)
            if not r.ok:
                ok = False; print("Loi gui Telegram:", r.status_code, r.text[:200])
        except requests.RequestException as e:
            ok = False; print("Loi ket noi Telegram:", e)
    return ok


# ------------------------------------------------------------------ tien ich
def ts(s):
    return None if s is None else pd.Timestamp(s)


def iso(t):
    return None if t is None else pd.Timestamp(t).isoformat()


def fvn(t):
    """Gio VN de doc, vd '07:00 T2 05/10'."""
    v = pd.Timestamp(t) + VN
    return f"{v:%H:%M} {['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'][v.weekday()]} {v:%d/%m}"


def px(x):
    x = float(x)
    if abs(x) < 50:
        return f"{x:.5f}"
    if abs(x) < 1000:
        return f"{x:.3f}"
    return f"{x:.2f}" if abs(x) < 10000 else f"{x:.1f}"


def pip_size(pair):
    if pair in CRYPTO_PAIRS:
        return 1.0
    return 0.01 if pair.endswith("JPY") else 0.0001


def dist_txt(pair, d):
    d = abs(float(d))
    return f"{px(d)} ({d / pip_size(pair):.0f} {'điểm' if pair in CRYPTO_PAIRS else 'pip'})"


def side_txt(s):
    return "LONG" if s == 1 else "SHORT"


def title(icon, action, p):
    return f"{icon} <b>{action} · {p['pair']} {side_txt(p['side'])}</b> · {NAME.get(p['he'], p['he'])}"


def fx_closed(now):
    """Khong co nen forex moi (giong du lieu backtest: khong co nen thu Bay, Chu nhat; thu Hai nen dau dong luc 01:00)."""
    wd, h = now.weekday(), now.hour
    return wd in (5, 6) or (wd == 4 and h >= 22) or (wd == 0 and h < 1)


def week_view(now):
    """Da het phien forex cua tuan -> coi thu Sau la ngay cuoi da dong."""
    wd, h = now.weekday(), now.hour
    return wd in (5, 6) or (wd == 4 and h >= WEEK_CLOSE_HOUR_UTC) or (wd == 0 and h < 1)


def next_monday(t):
    t = pd.Timestamp(t)
    return (t + pd.Timedelta(days=(7 - t.weekday()) % 7 or 7)).normalize()


def next_open(he, t):
    """Thoi diem vao lenh thuc te (forex nghi cuoi tuan -> dau phien thu Hai)."""
    t = pd.Timestamp(t)
    if he.startswith("BB") or (t.weekday() == 0 and t.hour == 0):
        return t
    return next_monday(t) if fx_closed(t) else t


def want_notify(he):
    return not NOTIFY_ONLY_PARTS or part_of(he) in NOTIFY_ONLY_PARTS or he in NOTIFY_ONLY_PARTS


# ------------------------------------------------------------------ trang thai
def new_state():
    return {"version": 2, "boot_done": False, "positions": [], "pending": [], "closed": [], "events": [],
            "announced": {}, "seen_closed": {}, "last_full_bin": None, "week_close_done": None,
            "e_watch": [], "b_regime": None, "last_run": None, "credits": {"date": None, "n": 0},
            "last_summary_date": None, "quota_alert_date": None, "last_calc": {}}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("version") == 2:
            return st
    return new_state()                                  # file cua chien luoc cu -> khoi dong lai


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, STATE_FILE)


def add_event(state, now, text):
    state["events"].append({"time": iso(now), "text": _plain(text).replace("\n", " | ")})
    state["events"] = state["events"][-120:]


# ------------------------------------------------------------------ bo nho dem nen H1
def cache_path(sym):
    return os.path.join(CACHE_DIR, f"{sym}.csv.gz")


def load_cache(sym):
    p = cache_path(sym)
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["Time"])
    return df if len(df) else None


def clean(sym, df):
    df = df[["Time", "Open", "High", "Low", "Close"]].copy()
    df["Time"] = pd.to_datetime(df["Time"])
    for c in ("Open", "High", "Low", "Close"):
        df[c] = df[c].astype(float)
    df = df.drop_duplicates("Time", keep="last").sort_values("Time").reset_index(drop=True)
    if sym in FX_PAIRS:                                   # giong du lieu MT5 da backtest
        wd, h = df.Time.dt.weekday, df.Time.dt.hour
        df = df[~((wd == 5) | (wd == 6) | ((wd == 4) & (h >= 22)))]
    return df.reset_index(drop=True)


def default_fetcher(sym, outputsize, end_date=None):
    from twelvedata_client import fetch_time_series
    return fetch_time_series(sym, "1h", outputsize=outputsize, end_date=end_date, min_len=0)


def count_credit(state, now):
    d = str(now.date())
    if state["credits"].get("date") != d:
        state["credits"] = {"date": d, "n": 0}
    state["credits"]["n"] += 1


def update_symbol(sym, now, fetcher, state):
    old = load_cache(sym)
    if old is None or len(old) < 500:                    # khoi dong: tai nhieu trang
        frames, end = [], None
        for _ in range(BOOT_PAGES):
            df = fetcher(sym, 5000, end_date=end); count_credit(state, now)
            if df is None or not len(df):
                break
            frames.append(df); end = pd.to_datetime(df.Time).min() - H1
        new = pd.concat(frames) if frames else pd.DataFrame(columns=["Time", "Open", "High", "Low", "Close"])
    else:
        gap = (now - old.Time.max()) / H1
        df = fetcher(sym, int(min(5000, max(6, gap + 3)))); count_credit(state, now)
        new = pd.concat([old, df]) if df is not None and len(df) else old
    new = clean(sym, new)
    new = new[new.Time + H1 <= now].tail(CACHE_MAX_BARS)  # chi giu nen DA DONG
    os.makedirs(CACHE_DIR, exist_ok=True)
    new.to_csv(cache_path(sym), index=False, compression="gzip")
    return new


# ------------------------------------------------------------------ lap ke hoach lay mau
def last_friday(now):
    return (now - pd.Timedelta(days=(now.weekday() - 4) % 7)).normalize()


def plan(state, now, boot):
    syms, why = set(), []
    if "BB" in PARTS:
        syms |= set(CRYPTO_PAIRS); why.append("crypto moi gio")
    full = week = False
    if boot:
        syms |= set(FX_PAIRS); full = True; why.append("khoi dong")
        return sorted(syms), full, week, why
    fb = now.floor(f"{FULL_EVERY_HOURS}h")
    lf = ts(state.get("last_full_bin"))
    if not fx_closed(now) and (lf is None or lf < fb):
        full = True; why.append(f"nen {FULL_EVERY_HOURS}H dong")
    if week_view(now) and now.weekday() != 0 and state.get("week_close_done") != str(last_friday(now).date()):
        week = True; why.append("chot tuan")
    if full or week:
        syms |= set(FX_PAIRS)
    elif not fx_closed(now):
        extra = set(state.get("e_watch", [])) | {p["pair"] for p in state["positions"] if p["he"] == "E"}
        if extra:
            syms |= extra; why.append("E theo doi " + ",".join(sorted(extra)))
    return sorted(syms), full, week, why


# ------------------------------------------------------------------ chay engine backtest
def _val(v):
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        return iso(v)
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _row(d):
    r = {k: _val(v) for k, v in d.items() if not k.startswith("_")}
    if "vao" in r:
        r["id"] = f"{r['he']}|{r['pair']}|{r['side']}|{r['vao']}"
    return r


def engine(data, now, parts):
    """Chay dung cac ham backtest. A, D dung nen NGAY DA DONG (cat luc 00:00 UTC, hoac het thu Sau khi chot tuan)."""
    out = {}
    cut = last_friday(now) + pd.Timedelta(days=1) if week_view(now) else now.floor("D")
    for part, fn in (("A", eng.rule_A), ("D", eng.rule_D)):
        if part not in parts:
            continue
        dcut = {s: (df[df.Time < cut].reset_index(drop=True) if s in FX_PAIRS else df) for s, df in data.items()}
        eng.OPEN.clear(); eng.PENDING.clear(); eng._FCACHE.clear()
        closed = fn(dcut)
        pend = list(eng.PENDING)
        if part == "A":
            pend = eng.a_pending(dcut, require_week_close=True) if week_view(now) else []
        out[part] = dict(open=[_row(x) for x in eng.OPEN], pending=[_row(x) for x in pend],
                         closed=[_row(x) for x in closed])
    eng._FCACHE.clear()
    for part, fn in (("B", lambda d: eng.rule_B(d, B_FILTER)), ("C", eng.rule_C), ("E", eng.rule_E),
                     ("BB", eng.rule_BB)):
        if part not in parts:
            continue
        eng.OPEN.clear(); eng.PENDING.clear()
        closed = fn(data)
        out[part] = dict(open=[_row(x) for x in eng.OPEN], pending=[_row(x) for x in eng.PENDING],
                         closed=[_row(x) for x in closed])
    extra = {}
    if "E" in parts:                                      # cap dang trong boi canh E -> lay H1 moi gio
        F4 = eng.currency_factors(data, "4h")
        if F4 is not None:
            z4 = eng.currency_z(F4, eng.E_N)
            extra["e_watch"] = [p for p in FX_PAIRS if p in data and
                                eng.extreme_state(z4[p[:3]].values, z4[p[3:]].values, eng.E_T, 1.0, eng.E_N // 2)[-1] != 0]
    if "B" in out:
        cl = [c for c in out["B"]["closed"] if c.get("nguyen_nhan") == "JPY tu yeu"]
        if cl:
            last = max(ts(c["ra"]) for c in cl)
            extra["b_regime"] = round(sum(c["R"] for c in cl if ts(c["ra"]) >= last - pd.Timedelta(days=365)), 2)
    eng.OPEN.clear(); eng.PENDING.clear(); eng._FCACHE.clear()
    return out, extra


# ------------------------------------------------------------------ noi dung tin nhan
def risk_line(p, ref_price=None):
    he, pair, rk = p["he"], p["pair"], eng.RISK.get(p["he"], 0)
    if he in ("A", "D"):
        return f"Khối lượng: {rk}% vốn ứng với 1 ATR ngày = {dist_txt(pair, p['rui_ro'])}"
    if p.get("sl") is not None and ref_price is not None and not np.isnan(ref_price):
        return f"Khối lượng: {rk}% vốn ứng với khoảng SL ≈ {dist_txt(pair, ref_price - p['sl'])} (theo giá hiện tại)"
    if p.get("sl_kc") is not None:
        return f"Khối lượng: {rk}% vốn ứng với khoảng SL = {dist_txt(pair, p['sl_kc'])}"
    return f"Khối lượng: {rk}% vốn mỗi lệnh"


def msg_signal(q, last_px, now):
    he = q["he"]; t = next_open(he, ts(q["t_vao"]))
    late = now - t > pd.Timedelta(hours=26 if he in ("A", "D") else 2)
    L = [title("🟢" if q["side"] == 1 else "🔴", "VÀO", q)]
    if he == "A":
        L.append(f"Vào: giá mở {fvn(t)} · giữ 8 ngày giao dịch, đóng ở giá đóng cửa ngày thứ 8 (bot nhắc)")
        L.append(f"Không SL · WPR-EMA {q.get('wpr', 0):.1f}, giá dưới SMA200 ngày")
    elif he == "D":
        L.append(f"Vào: giá mở {fvn(t)} · không SL")
        L.append(f"Thoát khi bot báo (độ lệch z về dưới {eng.D_EXIT:g}, tối đa {eng.D_MAXAGE} ngày giao dịch)")
        L.append(f"z {q['pair'][:3]} {q.get('z_tu', 0):+.1f} · z {q['pair'][3:]} {q.get('z_mau', 0):+.1f}")
    elif he == "E":
        L.append(f"Vào: giá mở {fvn(t)}")
        L.append(f"<pre>SL  {px(q['sl'])}\nTP  {px(q['tp'])}\nRR  {q.get('rr', 0):.1f}</pre>SL, TP cố định — đặt sẵn trên sàn.")
    elif he == "B":
        L.append(f"Vào: giá mở {fvn(t)}")
        L.append(f"SL ban đầu {px(q['sl'])} · dời theo Supertrend 4H (bot báo)")
        if q.get("nguyen_nhan"):
            L.append(f"Nguyên nhân cú đảo chiều: {q['nguyen_nhan']}")
    elif he == "C":
        L.append(f"Vào: giá mở {fvn(t)} · SL = giá vào + {px(q['sl_kc'])}, kéo theo đáy (bot báo)")
    else:
        L.append(f"Vào: giá mở {fvn(t)} · SL {px(q['sl'])} (band đối diện, bot báo khi dời) · tối đa 10 ngày")
    L.append(risk_line(q, last_px))
    if late:
        L.insert(0, "⚠️ <b>Tín hiệu cũ</b> (bot bị gián đoạn) — cân nhắc trước khi vào")
    return "\n".join(L)


def exit_reason(c):
    he, R = c["he"], c.get("R", 0)
    held = (ts(c["ra"]) - ts(c["vao"])) / pd.Timedelta(days=1)
    if he == "A":
        return "hết 8 ngày giao dịch"
    if he == "D":
        return "độ lệch về gần trung bình" if held < eng.D_MAXAGE * 7 / 5 - 3 else f"giữ đủ {eng.D_MAXAGE} ngày"
    if he == "E":
        return "chạm TP" if R > 0 else "chạm SL"
    if he.startswith("BB") and held >= 9.9:
        return "hết 10 ngày"
    return "chạm SL kéo theo"


def msg_close(c, note=""):
    R = c.get("R", 0); pct = R * eng.RISK.get(c["he"], 0)
    held = ts(c["ra"]) - ts(c["vao"])
    held_txt = f"{held / pd.Timedelta(days=1):.1f} ngày" if held >= pd.Timedelta(days=1) else f"{held / H1:.0f} giờ"
    return (title("✅" if R > 0 else "❌", "ĐÃ CHỐT", c) + "\n"
            f"<b>{R:+.2f}R</b> (≈ {pct:+.2f}% vốn) · {exit_reason(c)}\n"
            f"{px(c['gia_vao'])} → {px(c['gia_ra'])} · giữ {held_txt}" + note)


def r_now(p, last):
    return p["side"] * (last - p["gia_vao"]) / p["rui_ro"] if p.get("rui_ro") else 0.0


# ------------------------------------------------------------------ so sanh voi lan truoc va bao
def consume_pending(state, p):
    """Lenh moi co khop tin hieu da bao (vao trong vong 4 ngay sau gio du kien) khong."""
    vao = ts(p["vao"])
    for k, v in state["announced"].items():
        he, pair, side, tv = k.split("|")
        if (he, pair, int(side)) == (p["he"], p["pair"], p["side"]) and not v.get("used"):
            if ts(tv) - H1 <= vao <= ts(tv) + pd.Timedelta(days=4):
                v["used"] = True
                return True
    return False


def emit(state, now, notify, msgs, he, txt):
    add_event(state, now, txt)
    if notify and want_notify(he):
        msgs.append(txt)


def process(state, res, data, now, notify, msgs):
    lastp = {s: float(df.Close.iloc[-1]) for s, df in data.items() if len(df)}
    for part, snap in res.items():
        prev = {p["id"]: p for p in state["positions"] if part_of(p["he"]) == part}
        cur = {p["id"]: p for p in snap["open"]}
        closed = {c["id"]: c for c in snap["closed"]}
        last_calc = ts(state["last_calc"].get(part))
        # 1) lenh dang mo -> da dong
        for pid, p in prev.items():
            if pid in cur:
                continue
            c = closed.get(pid)
            if c is None:
                add_event(state, now, f"Ngừng theo dõi {pid} (dữ liệu nguồn thay đổi)")
                continue
            if pid not in state["seen_closed"]:
                emit(state, now, notify, msgs, c["he"], msg_close(c))
                state["closed"].append(c)
            state["seen_closed"][pid] = iso(now)
        # 2) lenh vao va dong giua 2 lan tinh
        if last_calc is not None:
            for cid, c in closed.items():
                if cid in prev or cid in state["seen_closed"] or ts(c["ra"]) <= last_calc:
                    continue
                consume_pending(state, c)
                emit(state, now, notify, msgs, c["he"], msg_close(c, "\n<i>Vào và chốt giữa 2 lần cập nhật</i>"))
                state["seen_closed"][cid] = iso(now); state["closed"].append(c)
        # 3) lenh moi mo / doi SL / nhac thoat
        for pid, p in cur.items():
            last = lastp.get(p["pair"], p["gia_vao"])
            p["last"] = last; p["r_now"] = round(r_now(p, last), 3)
            p["pct_now"] = round(p["r_now"] * eng.RISK.get(p["he"], 0), 3)
            old = prev.get(pid)
            if old is None:
                p["sl_bao"] = p.get("sl")
                if not consume_pending(state, p) and last_calc is not None:
                    emit(state, now, notify, msgs, p["he"],
                         title("🟢" if p["side"] == 1 else "🔴", "ĐANG MỞ (báo muộn)", p) + "\n"
                         f"Vào {px(p['gia_vao'])} lúc {fvn(p['vao'])} · {p.get('ghi_chu', '')}\n"
                         f"<i>Tín hiệu xảy ra lúc bot gián đoạn — tạm tính {p['r_now']:+.2f}R</i>")
                continue
            for k in ("sl_bao", "sl_bao_luc", "bao_thoat", "bao_ngay_cuoi"):
                if k in old:
                    p[k] = old[k]
            if p.get("sl") is not None and p["he"] in SL_MOVE_MIN_R and p.get("rui_ro"):
                base = p.get("sl_bao", old.get("sl"))
                gap_ok = (ts(p.get("sl_bao_luc")) is None or
                          now - ts(p["sl_bao_luc"]) >= pd.Timedelta(hours=SL_MOVE_MIN_HOURS.get(p["he"], 0)))
                if base is not None and gap_ok and abs(p["sl"] - base) >= SL_MOVE_MIN_R[p["he"]] * p["rui_ro"]:
                    emit(state, now, notify, msgs, p["he"], title("↕️", "DỜI SL", p) +
                         f"\n{px(base)} → <b>{px(p['sl'])}</b> · tạm tính {p['r_now']:+.2f}R")
                    p["sl_bao"] = p["sl"]; p["sl_bao_luc"] = iso(now)
            if p["he"] == "D" and p.get("thoat") and not p.get("bao_thoat"):
                p["bao_thoat"] = True
                when = (f"giá mở {fvn(next_monday(now))}" if week_view(now) else "giá thị trường ngay bây giờ "
                        f"(phiên mở {fvn(now.floor('D'))})")
                emit(state, now, notify, msgs, "D", title("🔔", "THOÁT", p) +
                     f"\nĐóng ở {when} · độ lệch {p.get('do_lech', 0):+.2f} (hoặc đủ {eng.D_MAXAGE} ngày)\n"
                     f"Tạm tính <b>{p['r_now']:+.2f}R</b>")
            if p["he"] == "A" and p.get("con_ngay") == 1 and not p.get("bao_ngay_cuoi") and not week_view(now):
                p["bao_ngay_cuoi"] = True
                emit(state, now, notify, msgs, "A", title("🔔", "HÔM NAY ĐÓNG", p) +
                     f"\nNgày giữ cuối: đóng ở giá đóng cửa, trước {fvn(now.floor('D') + pd.Timedelta(days=1))}\n"
                     f"Tạm tính <b>{p['r_now']:+.2f}R</b>")
        # 4) tin hieu cho vao
        for q in snap["pending"]:
            key = f"{q['he']}|{q['pair']}|{q['side']}|{q['t_vao']}"
            if key not in state["announced"]:
                state["announced"][key] = {"time": iso(now), "used": False}
                emit(state, now, notify, msgs, q["he"], msg_signal(q, lastp.get(q["pair"]), now))
        state["positions"] = [p for p in state["positions"] if part_of(p["he"]) != part] + list(cur.values())
        state["pending"] = [q for q in state["pending"] if part_of(q["he"]) != part] + snap["pending"]
        state["last_calc"][part] = iso(now)
    state["closed"] = sorted(state["closed"], key=lambda c: c["ra"])[-200:]
    state["announced"] = dict(sorted(state["announced"].items(), key=lambda kv: kv[1]["time"])[-600:])
    state["seen_closed"] = dict(sorted(state["seen_closed"].items(), key=lambda kv: kv[1])[-1500:])
    for p in state["positions"]:                          # gia moi nhat cho moi lenh
        if p["pair"] in lastp:
            p["last"] = lastp[p["pair"]]; p["r_now"] = round(r_now(p, p["last"]), 3)
            p["pct_now"] = round(p["r_now"] * eng.RISK.get(p["he"], 0), 3)


# ------------------------------------------------------------------ tom tat buoi sang
def summary(state, now):
    d = now + VN
    L = [f"📋 <b>{DOW[d.weekday()]}, {d:%d/%m}</b>"]
    pos = sorted(state["positions"], key=lambda p: (ORDER.index(p["he"]) if p["he"] in ORDER else 9, p["pair"]))
    if pos:
        L.append(f"<b>Đang mở {len(pos)} lệnh</b> · tạm tính {sum(p.get('pct_now', 0) for p in pos):+.2f}% vốn")
        rows = []
        for p in pos:
            extra = (f"SL {px(p['sl'])}" if p.get("sl") is not None else
                     f"còn {p.get('con_ngay', '?')} ngày" if p["he"] == "A" else
                     f"lệch {p.get('do_lech', 0):+.1f}" if p["he"] == "D" else "")
            rows.append(f"{'▲' if p['side'] == 1 else '▼'} {p['pair']:<6} {p['he']:<6}{p.get('r_now', 0):>+6.2f}R  {extra}")
        L.append("<pre>" + esc("\n".join(rows)) + "</pre>")
    else:
        L.append("Không có lệnh nào đang mở.")
    if state.get("pending"):
        L.append("Tín hiệu chờ vào: " + ", ".join(f"{q['he']} {q['pair']} {side_txt(q['side'])}" for q in state["pending"]))
    if state.get("e_watch"):
        L.append(f"E đang theo dõi mỗi giờ: {', '.join(state['e_watch'])}")
    br = state.get("b_regime")
    if br is not None and "B" in PARTS:
        L.append(f"Chỉ báo chế độ B (R 12 tháng lệnh 'JPY tự yếu'): <b>{br:+.1f}R</b>"
                 + (" — âm, cân nhắc giảm khối lượng B" if br < 0 else ""))
    if d.weekday() == 4:
        L.append("05:00 sáng thứ Bảy (giờ VN) bot chốt tín hiệu A, D, B cho tuần sau.")
    L.append(f"<i>Twelve Data hôm nay: {state['credits'].get('n', 0)} lượt</i>")
    return "\n".join(L)


# ------------------------------------------------------------------ chay 1 lan
def run(now=None, fetcher=None, send=True, persist=True):
    from twelvedata_client import DailyQuotaExhausted
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).floor("min") if now is None else pd.Timestamp(now)
    fetcher = fetcher or default_fetcher
    state = load_state()
    boot = not state.get("boot_done")
    syms, full, week, why = plan(state, now, boot)
    msgs, fetched, quota = [], [], False
    for s in syms:
        try:
            update_symbol(s, now, fetcher, state); fetched.append(s)
        except DailyQuotaExhausted:
            quota = True
            if state.get("quota_alert_date") != str(now.date()):
                msgs.append("⚠️ <b>Hết hạn mức API Twelve Data hôm nay</b>\nBot dùng dữ liệu đã lưu, "
                            "tự lấy tiếp khi hạn mức reset (07:00 sáng giờ VN).")
                state["quota_alert_date"] = str(now.date())
            break
        except Exception as e:
            add_event(state, now, f"Lỗi lấy dữ liệu {s}: {e}")
    data = {}
    for s in FX_PAIRS + CRYPTO_PAIRS:
        df = load_cache(s)
        if df is not None and len(df) > 300:
            data[s] = df.assign(spr_pct=SPREAD_PCT.get(s, 0.02))
    if full or week or boot:
        parts = list(PARTS)
    else:
        parts = [p for p in ("BB",) if p in PARTS]
        if "E" in PARTS and any(s in FX_PAIRS for s in fetched):
            parts.append("E")
    if quota and not boot:
        parts = [p for p in parts if p in ("BB", "E")]
    res, extra = engine(data, now, parts) if data else ({}, {})
    process(state, res, data, now, notify=not boot, msgs=msgs)
    state.update({k: v for k, v in extra.items()})
    if full and not quota:
        state["last_full_bin"] = iso(now.floor(f"{FULL_EVERY_HOURS}h"))
    if week and not quota:
        state["week_close_done"] = str(last_friday(now).date())
    if boot:
        state["boot_done"] = True
        state["last_summary_date"] = str((now + VN).date())
        pos = state["positions"]
        L = [f"🤖 <b>Bot danh mục v4 đã chạy</b> · thành phần {', '.join(PARTS)}",
             f"Đang theo dõi {len(pos)} lệnh mở (dựng lại từ dữ liệu gần đây):"]
        L += [f"• {p['he']} {p['pair']} {side_txt(p['side'])} vào {px(p['gia_vao'])} ({fvn(p['vao'])}) · {p.get('r_now', 0):+.2f}R"
              + (f" · SL {px(p['sl'])}" if p.get("sl") is not None else "") for p in pos]
        msgs.append("\n".join(L))
        for q in state["pending"]:
            state["announced"][f"{q['he']}|{q['pair']}|{q['side']}|{q['t_vao']}"] = {"time": iso(now), "used": False}
            if want_notify(q["he"]):
                msgs.append(msg_signal(q, float(data[q["pair"]].Close.iloc[-1]) if q["pair"] in data else None, now))
    vnow = now + VN
    if not boot and state.get("last_summary_date") != str(vnow.date()) and vnow.hour >= DAILY_SUMMARY_HOUR_VN:
        msgs.append(summary(state, now)); state["last_summary_date"] = str(vnow.date())
    state["last_run"] = iso(now)
    state["last_fetch"] = {"symbols": fetched, "why": why, "parts": parts}
    state["parts"] = PARTS
    state["risk"] = eng.RISK
    state["floating_now"] = round(sum(p.get("pct_now", 0) for p in state["positions"]), 3)
    state["data_end"] = {s: iso(df.Time.iloc[-1]) for s, df in data.items()}
    if persist:
        save_state(state)
    if msgs and send:
        send_blocks(msgs)
    return state, msgs


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        print(err)
        try:
            send_blocks(["⚠️ <b>Bot gặp lỗi</b>\n<pre>" + esc(err[-1500:]) + "</pre>"])
        finally:
            sys.exit(1)
