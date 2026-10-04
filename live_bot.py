"""
================================================================================
LIVE_BOT.PY - bot theo doi danh muc v5 (A, B, BB, AQB, D, E; C tuy chon), bao qua Telegram
================================================================================
Moi lan chay (khuyen nghi moi gio, phut :02):
  1. Lap ke hoach lay du lieu theo LICH LAY MAU (xem config.py):
       - moi gio: BTC, ETH, SOL (BB) + cap forex dang trong boi canh E / co lenh E mo
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
                    BOOT_PAGES, STATE_FILE, SL_MOVE_MIN_R, SL_MOVE_MIN_HOURS, SPREAD_PCT, METALS, NOTIFY_SKIPPED)

VN = pd.Timedelta(hours=VN_OFFSET_HOURS)
H1 = pd.Timedelta(hours=1)
NAME = {"A": "A · mua sau bán tháo", "B": "B · xu hướng JPY", "C": "C · CUSUM short JPY",
        "D": "D · đảo chiều sức mạnh", "E": "E · lớp phụ 4H→1H", "BB BTC": "BB · squeeze BTC",
        "BB ETH": "BB · squeeze ETH", "BB SOL": "BB · squeeze SOL", "AQB XAU": "AQB · vàng",
        "AQB BTC": "AQB · BTC", "AQB ETH": "AQB · ETH", "AQB SOL": "AQB · SOL", "AQB DOGE": "AQB · DOGE"}
ORDER = list(eng.ORDER)
DOW = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def part_of(he):
    return he.split()[0] if he.startswith(("BB", "AQB")) else he


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


def dist_txt(pair, d, ref=None):
    d = abs(float(d))
    if pair in CRYPTO_PAIRS:                              # crypto: khoang cach theo % gia
        return f"{px(d)} ({d / ref * 100:.2f}% giá)" if ref else px(d)
    return f"{px(d)} ({d / pip_size(pair):.0f} pip)"


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


def next_open(he, t, pair=None):
    """Thoi diem vao lenh thuc te (forex, vang nghi cuoi tuan -> dau phien thu Hai; crypto 24/7)."""
    t = pd.Timestamp(t)
    if he.startswith("BB") or pair in CRYPTO_PAIRS or (t.weekday() == 0 and t.hour == 0):
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
    if sym in FX_PAIRS or sym in METALS:                  # giong du lieu MT5 da backtest (nghi cuoi tuan)
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
    if "BB" in PARTS or "AQB" in PARTS:
        syms |= set(CRYPTO_PAIRS); why.append("crypto moi gio")
    if "AQB" in PARTS and not fx_closed(now):
        syms |= set(METALS); why.append("vang moi gio")
    full = week = False
    if boot:
        syms |= set(FX_PAIRS) | set(METALS); full = True; why.append("khoi dong")
        return sorted(syms), full, week, why
    fb = now.floor(f"{FULL_EVERY_HOURS}h")
    lf = ts(state.get("last_full_bin"))
    if not fx_closed(now) and (lf is None or lf < fb):
        full = True; why.append(f"nen {FULL_EVERY_HOURS}H dong")
    if week_view(now) and now.weekday() != 0 and state.get("week_close_done") != str(last_friday(now).date()):
        week = True; why.append("chot tuan")
    if full or week:
        syms |= set(FX_PAIRS) | set(METALS)
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
                     ("BB", eng.rule_BB), ("AQB", eng.rule_AQB)):
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
        return f"Khối lượng: {rk}% vốn ứng với khoảng SL ≈ {dist_txt(pair, ref_price - p['sl'], ref_price)} (theo giá hiện tại)"
    if p.get("sl_kc") is not None:
        return f"Khối lượng: {rk}% vốn ứng với khoảng SL = {dist_txt(pair, p['sl_kc'])}"
    return f"Khối lượng: {rk}% vốn mỗi lệnh"


EQUITY = float(os.environ.get("ACCOUNT_EQUITY") or 0)      # von (USD) de quy ra tien; trong = chi hien %


def money(pct):
    return f" (≈ {EQUITY * pct / 100:,.0f} USD)" if EQUITY > 0 else ""


def gap_txt(pair, d, ref):
    d = abs(float(d))
    if pair in CRYPTO_PAIRS or pair in METALS:
        dec = 1 if ref >= 1000 else (2 if ref >= 10 else 4)
        return f"{d:.{dec}f} = {d / ref * 100:.2f}% giá"
    return f"{d / pip_size(pair):.0f} pip"


def msg_signal(q, last_px, now):
    """Tin VAO dang ke hoach: Vao / SL / TP-thoat / khoi luong / ly do."""
    he, pair, s = q["he"], q["pair"], q["side"]; t = next_open(he, ts(q["t_vao"]), pair)
    rk = eng.RISK.get(he, 0); ref = last_px if last_px is not None and not np.isnan(last_px) else None
    late = now - t > pd.Timedelta(hours=26 if he in ("A", "D") else 2)
    side = "MUA" if s == 1 else "BÁN"
    L = [title("🟢" if s == 1 else "🔴", "VÀO", q)]
    if late:
        L.insert(0, "⚠️ <b>Tín hiệu cũ</b> (bot bị gián đoạn) — cân nhắc trước khi vào")
    P = []
    P.append(f"① <b>Vào:</b> {side} giá thị trường lúc mở nến {fvn(t)}" + (f" (giá hiện tại {px(ref)})" if ref else ""))
    sl_ref = None
    if he in ("A", "D"):
        P.append("② <b>SL:</b> KHÔNG đặt — thiết kế của hệ (backtest có SL kém hơn). Rủi ro kiểm soát bằng khối lượng theo ATR; "
                 f"danh mục có ngắt mạch thả nổi {eng.BREAK_FLOAT:g}%.")
        unit = q.get("rui_ro")
        if he == "A":
            ex = (t + pd.offsets.BDay(eng.A_HOLD_DAYS - 1)).normalize() + pd.Timedelta(days=1)
            P.append(f"③ <b>TP/thoát:</b> không có TP. Đóng ở giá đóng cửa ngày giao dịch thứ {eng.A_HOLD_DAYS}, "
                     f"tức trước <b>{fvn(ex)}</b>. Bot nhắc 'HÔM NAY ĐÓNG' sáng hôm đó.")
        else:
            P.append(f"③ <b>TP/thoát:</b> không có TP cố định. Đóng khi bot báo <b>THOÁT</b> (độ lệch z hai đồng về dưới "
                     f"{eng.D_EXIT:g}) — thường vài tuần; muộn nhất <b>{fvn(t + pd.offsets.BDay(eng.D_MAXAGE))}</b>.")
        P.append(f"④ <b>Khối lượng:</b> {rk}% vốn{money(rk)} ứng với 1 ATR ngày = {px(unit)} ({gap_txt(pair, unit, ref or 1)})."
                 " Ví dụ giá đi ngược 2 ATR ≈ lỗ " + f"{2 * rk:.2f}% vốn.")
    else:
        sl = q.get("sl")
        if he == "C" and sl is None and ref:
            sl = ref + q.get("sl_kc", 0)
        if sl is not None:
            sl_ref = sl
            dist = f" — cách {gap_txt(pair, ref - sl, ref)}" if ref else ""
            how = {"B": "đường Supertrend 4H", "C": "giá vào + 3 ATR 4H", "E": "đường Supertrend 1H lúc vào, cố định"}.get(
                he, "band Bollinger đối diện" if he.startswith("BB") else "band phân vị AQB p1/p99")
            P.append(f"② <b>SL: {px(sl)}</b> ({how}){dist}. Đặt SL trên sàn ngay khi vào.")
        if he == "E":
            tp = q.get("tp"); dtp = f" — cách {gap_txt(pair, tp - ref, ref)}" if ref and tp else ""
            P.append(f"③ <b>TP: {px(tp)}</b> (mean SMA120 khung 4H){dtp} · RR {q.get('rr', 0):.1f}. "
                     "Đặt sẵn cả SL và TP, không cần theo dõi; thoát khi chạm một trong hai.")
        elif he == "B":
            P.append("③ <b>TP:</b> không có — để lệnh chạy theo xu hướng. Mỗi 4 giờ dời SL lên theo Supertrend 4H "
                     "(bot báo DỜI SL). Thoát khi giá chạm SL.")
        elif he == "C":
            P.append("③ <b>TP:</b> không có — kéo SL xuống theo đáy mới (đáy + 3 ATR 4H), bot báo DỜI SL. Thoát khi chạm SL.")
        else:
            hold = 10 if he.startswith("BB") else eng.AQB_PARAMS.get(pair, (0, 0, 5, 0))[2]
            P.append(f"③ <b>TP:</b> không có — kéo SL theo band mỗi giờ (bot báo khi dời ≥ 0.5R, tối đa mỗi 4 giờ). "
                     f"Đóng muộn nhất sau {hold} ngày giao dịch: <b>"
                     f"{fvn(t + (pd.Timedelta(days=hold) if pair in CRYPTO_PAIRS else pd.offsets.BDay(hold)))}</b>.")
        if sl_ref is not None and ref:
            P.append(f"④ <b>Khối lượng:</b> rủi ro {rk}% vốn{money(rk)} nếu chạm SL → khối lượng = "
                     f"{rk}% vốn ÷ {gap_txt(pair, ref - sl_ref, ref)}.")
        else:
            P.append(f"④ <b>Khối lượng:</b> rủi ro {rk}% vốn{money(rk)} nếu chạm SL.")
    why = {"A": f"WPR-EMA H1 {q.get('wpr', 0):.1f} (quá bán) lúc đóng cửa thứ Sáu, giá dưới SMA200 ngày",
           "B": f"Supertrend 4H đảo lên · nguyên nhân: {q.get('nguyen_nhan', '?')}",
           "C": "CUSUM 4H báo yen tăng mạnh",
           "D": f"z {pair[:3]} {q.get('z_tu', 0):+.1f}, z {pair[3:]} {q.get('z_mau', 0):+.1f} (lệch cực đoan, đánh hồi về)",
           "E": "Bối cảnh 4H: hai đồng lệch cực đoan; Supertrend 1H vừa đảo về phía trung bình"}.get(
        he, "Squeeze Bollinger rồi phá band" if he.startswith("BB") else "Nén biến động rồi bứt phá vượt phân vị (AQB)")
    P.append(f"⑤ <b>Lý do:</b> {why}")
    return "\n".join(L + P)


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
                return v
    return None


def emit(state, now, notify, msgs, he, txt):
    add_event(state, now, txt)
    if notify and want_notify(he):
        msgs.append(txt)


def book_close(state, c, now):
    """Ghi nhan lai/lo da chot (% von) vao tong va vao phan cua thang."""
    pct = c.get("R", 0) * eng.RISK.get(c["he"], 0)
    state["realized"] = state.get("realized", 0.0) + pct
    mr = state.setdefault("month_real", {"key": f"{now:%Y-%m}"})
    if mr.get("key") != f"{now:%Y-%m}":
        state["month_real"] = mr = {"key": f"{now:%Y-%m}"}
    if f"{ts(c['ra']):%Y-%m}" == mr["key"]:
        sl = eng.sleeve(c["he"]); mr[sl] = mr.get(sl, 0.0) + pct


def process(state, res, data, now, notify, msgs):
    lastp = {s: float(df.Close.iloc[-1]) for s, df in data.items() if len(df)}
    blocked = set(state.setdefault("blocked_ids", []))
    new_signals = []
    for part, snap in res.items():
        prev = {p["id"]: p for p in state["positions"] if part_of(p["he"]) == part}
        cur = {p["id"]: p for p in snap["open"] if p["id"] not in blocked}
        closed = {c["id"]: c for c in snap["closed"] if c["id"] not in blocked}
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
                state["closed"].append(c); book_close(state, c, now)
            state["seen_closed"][pid] = iso(now)
        # 2) lenh vao va dong giua 2 lan tinh
        if last_calc is not None:
            for cid, c in closed.items():
                if cid in prev or cid in state["seen_closed"] or ts(c["ra"]) <= last_calc:
                    continue
                v = consume_pending(state, c)
                state["seen_closed"][cid] = iso(now)
                if v is not None and v.get("blocked"):
                    blocked.add(cid); continue
                emit(state, now, notify, msgs, c["he"], msg_close(c, "\n<i>Vào và chốt giữa 2 lần cập nhật</i>"))
                state["closed"].append(c); book_close(state, c, now)
        # 3) lenh moi mo / doi SL / nhac thoat
        for pid, p in cur.items():
            last = lastp.get(p["pair"], p["gia_vao"])
            p["last"] = last; p["r_now"] = round(r_now(p, last), 3)
            p["pct_now"] = round(p["r_now"] * eng.RISK.get(p["he"], 0), 3)
            old = prev.get(pid)
            if old is None:
                p["sl_bao"] = p.get("sl")
                v = consume_pending(state, p)
                if v is not None and v.get("blocked"):
                    blocked.add(pid); continue
                if v is None and last_calc is not None:
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
                new_signals.append((key, q))
        cur = {k: v for k, v in cur.items() if k not in blocked}
        state["positions"] = [p for p in state["positions"] if part_of(p["he"]) != part] + list(cur.values())
        state["pending"] = [q for q in state["pending"] if part_of(q["he"]) != part] + snap["pending"]
        state["last_calc"][part] = iso(now)
    state["closed"] = sorted(state["closed"], key=lambda c: c["ra"])[-200:]
    state["announced"] = dict(sorted(state["announced"].items(), key=lambda kv: kv[1]["time"])[-600:])
    state["seen_closed"] = dict(sorted(state["seen_closed"].items(), key=lambda kv: kv[1])[-1500:])
    state["blocked_ids"] = sorted(blocked)[-3000:]
    for p in state["positions"]:                          # gia moi nhat cho moi lenh
        if p["pair"] in lastp:
            p["last"] = lastp[p["pair"]]; p["r_now"] = round(r_now(p, p["last"]), 3)
            p["pct_now"] = round(p["r_now"] * eng.RISK.get(p["he"], 0), 3)
    return new_signals


# ------------------------------------------------------------------ ngat mach + cong kiem soat tin hieu
def breakers(state, now, notify, msgs):
    """Cap nhat von (cong don % da chot + tha noi), kich hoat ngat mach phan / tha noi / sut giam."""
    rs = state.setdefault("risk_state", {})
    pos = state["positions"]; mk = f"{now:%Y-%m}"
    if state.get("month_real", {}).get("key") != mk:
        state["month_real"] = {"key": mk}
    floating = sum(p.get("pct_now", 0) for p in pos)
    eq = state.get("realized", 0.0) + floating
    if os.environ.get("RESET_DD", "").strip() in ("1", "true"):
        state["dd_stop"] = False; state["eq_peak"] = eq
    state["eq_peak"] = max(state.get("eq_peak", 0.0), eq)
    dd = eq - state["eq_peak"]
    # 1) khan cap: lo tha noi
    if floating <= -eng.BREAK_FLOAT and pos:
        L = [f"🚨 <b>NGẮT MẠCH KHẨN CẤP</b> · lỗ thả nổi {floating:+.2f}% vốn (ngưỡng −{eng.BREAK_FLOAT:g}%)",
             "<b>Đóng tất cả lệnh đang mở ngay:</b>"]
        L += [f"• {p['he']} {p['pair']} {side_txt(p['side'])} · {p.get('r_now', 0):+.2f}R" for p in pos]
        L.append(f"Không vào lệnh mới đến {fvn(now.floor('D') + pd.Timedelta(days=1))}.")
        emit(state, now, notify, msgs, "A", "\n".join(L))
        bl = set(state.get("blocked_ids", []))
        for p in pos:
            bl.add(p["id"]); sl = eng.sleeve(p["he"])
            state["month_real"][sl] = state["month_real"].get(sl, 0.0) + p.get("pct_now", 0)
        state["blocked_ids"] = sorted(bl)[-3000:]; state["realized"] = state.get("realized", 0.0) + floating
        state["positions"] = []; floating = 0.0
        state["float_pause_until"] = iso(now.floor("D") + pd.Timedelta(days=1))
    # 2) phan (A, FX) lo trong thang
    stops = state.setdefault("sleeve_stop", {})
    mtd = {}
    for sl, lim in eng.BREAK_SLEEVE_MONTH.items():
        mtd[sl] = state["month_real"].get(sl, 0.0) + sum(p.get("pct_now", 0) for p in state["positions"] if eng.sleeve(p["he"]) == sl)
        if mtd[sl] <= -lim and stops.get(sl) != mk:
            stops[sl] = mk
            who = "A" if sl == "A" else "B, D, E"
            emit(state, now, notify, msgs, "A" if sl == "A" else "B",
                 f"⏸ <b>NGẮT MẠCH PHẦN {sl}</b> ({who}) · lỗ tháng {mtd[sl]:+.2f}% vốn (ngưỡng −{lim:g}%)\n"
                 f"Dừng vào lệnh mới của {who} đến hết tháng. Lệnh đang mở vẫn quản lý bình thường.")
    # 3) he thong: sut giam tu dinh
    if dd <= -eng.BREAK_DD and not state.get("dd_stop"):
        state["dd_stop"] = True
        emit(state, now, notify, msgs, "A", f"🛑 <b>DỪNG HỆ THỐNG</b> · sụt giảm {dd:.1f}% từ đỉnh (ngưỡng −{eng.BREAK_DD:g}%)\n"
             "Không báo tín hiệu VÀO nữa. Đánh giá lại chiến lược; muốn chạy lại đặt biến RESET_DD=1 cho 1 lần chạy.")
    rs.update(floating=round(floating, 3), equity=round(eq, 3), dd=round(dd, 3), month=mk,
              sleeve_mtd={k: round(v, 3) for k, v in mtd.items()},
              sleeve_paused=[k for k, v in stops.items() if v == mk], dd_stop=bool(state.get("dd_stop")),
              float_pause_until=state.get("float_pause_until"))


def gate(state, new_signals, data, now, notify, msgs):
    """Moi tin hieu moi phai qua: dung he thong, nghi sau ngat tha noi, ngat phan, tran rui ro mo, tran crypto."""
    lastp = {s: float(df.Close.iloc[-1]) for s, df in data.items() if len(df)}
    pos = state["positions"]; mk = f"{now:%Y-%m}"
    open_risk = sum(eng.RISK.get(p["he"], 0) for p in pos)
    n_cr = sum(1 for p in pos if p["pair"] in CRYPTO_PAIRS)
    paused = {k for k, v in state.get("sleeve_stop", {}).items() if v == mk}
    fp = ts(state.get("float_pause_until"))
    for key, q in new_signals:
        rk = eng.RISK.get(q["he"], 0); sl = eng.sleeve(q["he"]); why = None
        if state.get("dd_stop"):
            why = f"hệ thống đã dừng (sụt giảm ≥ {eng.BREAK_DD:g}%)"
        elif fp is not None and now < fp:
            why = "đang nghỉ sau ngắt mạch thả nổi"
        elif sl in paused:
            why = f"phần {sl} đã chạm ngưỡng lỗ tháng"
        elif open_risk + rk > eng.MAX_OPEN_RISK + 1e-9:
            why = f"vượt trần rủi ro mở {eng.MAX_OPEN_RISK:g}% (đang {open_risk:.2f}%)"
        elif q["pair"] in CRYPTO_PAIRS and n_cr >= eng.CRYPTO_MAX_OPEN:
            why = f"đã đủ {eng.CRYPTO_MAX_OPEN} lệnh crypto"
        if why:
            state["announced"][key] = {"time": iso(now), "used": False, "blocked": True, "ly_do": why}
            txt = title("⏭", "BỎ QUA", q) + f"\n{why}"
            add_event(state, now, txt)
            if notify and NOTIFY_SKIPPED and want_notify(q["he"]):
                msgs.append(txt)
            continue
        state["announced"][key] = {"time": iso(now), "used": False}
        open_risk += rk; n_cr += q["pair"] in CRYPTO_PAIRS
        emit(state, now, notify, msgs, q["he"], msg_signal(q, lastp.get(q["pair"]), now))
    state.setdefault("risk_state", {}).update(open_risk=round(open_risk, 3), crypto_open=n_cr)
    state["pending"] = [q for q in state["pending"] if not state["announced"].get(
        f"{q['he']}|{q['pair']}|{q['side']}|{q['t_vao']}", {}).get("blocked")]


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
    rs = state.get("risk_state", {})
    L.append(f"Rủi ro đang mở {rs.get('open_risk', 0):.2f}% / {eng.MAX_OPEN_RISK:g}% · crypto {rs.get('crypto_open', 0)}/"
             f"{eng.CRYPTO_MAX_OPEN} · thả nổi {rs.get('floating', 0):+.2f}% · từ đỉnh {rs.get('dd', 0):+.2f}%")
    flags = [f"phần {k} dừng đến hết tháng" for k in rs.get("sleeve_paused", [])] + (["HỆ THỐNG ĐÃ DỪNG"] if rs.get("dd_stop") else [])
    if flags:
        L.append("⏸ Ngắt mạch: " + "; ".join(flags))
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
    for s in FX_PAIRS + CRYPTO_PAIRS + METALS:
        df = load_cache(s)
        if df is not None and len(df) > 300:
            data[s] = df.assign(spr_pct=SPREAD_PCT.get(s, 0.02))
    if full or week or boot:
        parts = list(PARTS)
    else:
        parts = [p for p in ("BB", "AQB") if p in PARTS]
        if "E" in PARTS and any(s in FX_PAIRS for s in fetched):
            parts.append("E")
    if quota and not boot:
        parts = [p for p in parts if p in ("BB", "AQB", "E")]
    res, extra = engine(data, now, parts) if data else ({}, {})
    new_signals = process(state, res, data, now, notify=not boot, msgs=msgs)
    breakers(state, now, notify=not boot, msgs=msgs)
    state.update({k: v for k, v in extra.items()})
    if full and not quota:
        state["last_full_bin"] = iso(now.floor(f"{FULL_EVERY_HOURS}h"))
    if week and not quota:
        state["week_close_done"] = str(last_friday(now).date())
    if boot:
        state["boot_done"] = True
        state["last_summary_date"] = str((now + VN).date())
        pos = state["positions"]
        L = [f"🤖 <b>Bot danh mục v5 đã chạy</b> · thành phần {', '.join(PARTS)}",
             f"Đang theo dõi {len(pos)} lệnh mở (dựng lại từ dữ liệu gần đây):"]
        L += [f"• {p['he']} {p['pair']} {side_txt(p['side'])} vào {px(p['gia_vao'])} ({fvn(p['vao'])}) · {p.get('r_now', 0):+.2f}R"
              + (f" · SL {px(p['sl'])}" if p.get("sl") is not None else "") for p in pos]
        msgs.append("\n".join(L))
        gate(state, new_signals, data, now, notify=True, msgs=msgs)
    else:
        gate(state, new_signals, data, now, notify=True, msgs=msgs)
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
