"""
================================================================================
LIVE_BOT.PY - chay MOI GIO (khuyen nghi phut :02 gio VN)
================================================================================
Moi lan chay:
  1. Xac dinh cap nao CAN lay du lieu (chi cap co leg den gio vao / dung ngay,
     hoac dang co lenh mo) -> tiet kiem API Twelve Data.
  2. Chi dung NEN DA DONG (loai bo nen dang chay) -> tin hieu khong bi "ve lai".
  3. Phat hien VAO lenh (logic giong het backtest) cho ca 60 leg.
  4. Theo doi THOAT lenh: SL -> WPR doi dien -> het so nen toi da (dung thu tu backtest).
  5. Ngat mach: danh gia floating cuoi ngay (lan chay dau tien sau 00:00 VN),
     < -4% -> khong vao lenh moi 45 ngay.
  6. Gui Telegram, luu trang thai vao data/live_state.json (app React doc file nay).

Lan chay DAU TIEN (chua co state): tu "khoi dong" bang cach phat lai ~10 ngay
gan nhat de biet lenh nao dang mo, KHONG gui thong bao tung lenh cu.

Bot KHONG dat lenh. SL nen dat san tren san ngay luc vao lenh.
================================================================================
"""
import json
import os
import sys
import traceback
from datetime import timedelta

import numpy as np
import pandas as pd

from config import (TANG1_H1, TANG2_H4_DOW, TANG3_H4_DOM, RISK, MAX_HOLD_H1, MAX_HOLD_H4,
                    CIRCUIT_BREAKER_TRIGGER, CIRCUIT_BREAKER_PAUSE_DAYS, VN_OFFSET_HOURS,
                    SPREAD_PCT_M15, SPREAD_PCT_H4)
from indicators import add_indicators

LIVE_STATE_FILE = os.environ.get("LIVE_STATE_FILE", "data/live_state.json")
# Chi gui thong bao cho cac leg nay (vd "H1_XAUUSD_Long,H4DOM_EURUSD_Long"). Trong = tat ca.
# Bot VAN theo doi du 60 leg de tinh ngat mach, chi loc phan thong bao.
NOTIFY_ONLY_LEGS = [s.strip() for s in os.environ.get("NOTIFY_ONLY_LEGS", "").split(",") if s.strip()]
DAILY_SUMMARY_HOUR_VN = 5          # gui tom tat ngay o lan chay dau tien sau 5h sang
CB_EVAL_HOUR_VN = 4                # cham diem floating ngay hom truoc luc 4h sang: nen 4H cuoi ngay
                                   # (bat dau 23h VN) dong luc 3h -> khop cach backtest cham diem
OUTPUTSIZE = {"1h": 150, "4h": 150}
BOOT_OUTPUTSIZE = {"1h": 260, "4h": 150}   # ~10 ngay H1, ~25 ngay H4
WARMUP_BARS = 40                   # bo qua tin hieu o nhung nen dau chuoi (chi bao chua on dinh)
STALE_ENTRY_HOURS = {"1h": 2, "4h": 5}  # tin hieu cu hon muc nay -> coi la "bo lo"
INTERVAL = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4)}
VN = pd.Timedelta(hours=VN_OFFSET_HOURS)
DOW_LABEL = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
TIER_LABEL = {"H1": "H1", "H4DOW": "4H-Thứ", "H4DOM": "4H-Ngày"}


# ------------------------------------------------------------------
# DANH SACH LEG (lay nguyen tu config.py da backtest)
# ------------------------------------------------------------------
def build_legs():
    legs = []
    for pair, dr, (ws, we), eh, th, ex, am in TANG1_H1:
        legs.append(dict(id=f"H1_{pair}_{dr}", tier="H1", tf="1h", pair=pair, direction=dr,
                         window=[ws, we], entry_hour=eh, threshold=th, exclude_dow=ex,
                         atr_mult=am, risk=RISK["H1"], max_hold=MAX_HOLD_H1,
                         spread=SPREAD_PCT_M15.get(pair, SPREAD_PCT_H4.get(pair, 0.02))))
    for pair, dr, dow, th, am in TANG2_H4_DOW:
        legs.append(dict(id=f"H4DOW_{pair}_{dr}", tier="H4DOW", tf="4h", pair=pair, direction=dr,
                         dow=dow, threshold=th, atr_mult=am, risk=RISK["H4DOW"],
                         max_hold=MAX_HOLD_H4, spread=SPREAD_PCT_H4.get(pair, 0.02)))
    for pair, dr, dom, th, am in TANG3_H4_DOM:
        legs.append(dict(id=f"H4DOM_{pair}_{dr}", tier="H4DOM", tf="4h", pair=pair, direction=dr,
                         dom=dom, threshold=th, atr_mult=am, risk=RISK["H4DOM"],
                         max_hold=MAX_HOLD_H4, spread=SPREAD_PCT_H4.get(pair, 0.02)))
    return legs


LEGS = build_legs()
LEG_BY_ID = {l["id"]: l for l in LEGS}


# ------------------------------------------------------------------
# TIEN ICH THOI GIAN (tat ca Timestamp la UTC, khong gan mui gio)
# ------------------------------------------------------------------
def ts(s):
    return None if s is None else pd.Timestamp(s)


def iso(t):
    return None if t is None else pd.Timestamp(t).isoformat()


def vn_date(t):
    return (pd.Timestamp(t) + VN).date()


def fmt_vn(t):
    return (pd.Timestamp(t) + VN).strftime("%d/%m %H:%M")


def px(x):
    return f"{x:.5f}".rstrip("0").rstrip(".") if abs(x) < 50 else f"{x:.3f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------
# TRANG THAI
# ------------------------------------------------------------------
def new_state():
    return {"version": 1, "positions": [], "closed": [], "events": [],
            "leg_checked": {}, "pair_next_due": {},
            "pause_until": None, "last_cb_date": None, "floating_history": [],
            "last_summary_date": None, "last_run": None, "boot_done": False,
            "quota_alert_date": None}


def load_state():
    if os.path.exists(LIVE_STATE_FILE):
        with open(LIVE_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return new_state()


def save_state(state):
    os.makedirs(os.path.dirname(LIVE_STATE_FILE) or ".", exist_ok=True)
    tmp = LIVE_STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, LIVE_STATE_FILE)


# ------------------------------------------------------------------
# DU LIEU: chi giu NEN DA DONG
# ------------------------------------------------------------------
def default_fetcher(pair, tf, outputsize):
    from twelvedata_client import fetch_time_series
    return fetch_time_series(pair, tf, outputsize=outputsize)


def get_closed(pair, tf, now, outputsize, fetcher):
    df = fetcher(pair, tf, outputsize)
    df = df[df["Time"] + INTERVAL[tf] <= now].reset_index(drop=True)
    return add_indicators(df)


def is_stale(df, tf, now):
    """Du lieu cu (thi truong dong cua / nghi le): nen dong gan nhat qua xa so voi hien tai."""
    last_close = df["Time"].iloc[-1] + INTERVAL[tf]
    return (now - last_close) > INTERVAL[tf] + pd.Timedelta(hours=1)


# ------------------------------------------------------------------
# NGAT MACH
# ------------------------------------------------------------------
def entries_allowed(state, day):
    pu = state.get("pause_until")
    return pu is None or day > pd.Timestamp(pu).date()


def pos_floating(p, mark):
    """Floating % VON cua 1 lenh (giong precompute_trade_floating trong backtest, chua tru spread)."""
    sign = 1 if p["direction"] == "Long" else -1
    size_mult = p["risk"] / p["sl_pct"]
    return size_mult * sign * (mark - p["entry_price"]) / p["entry_price"] * 100


# ------------------------------------------------------------------
# VAO LENH
# ------------------------------------------------------------------
def open_position(state, leg, bar, now, notify, msgs, paused):
    sign = 1 if leg["direction"] == "Long" else -1
    entry = float(bar["Close"])
    sl_dist = float(bar["atr"]) * leg["atr_mult"]
    sl = entry - sign * sl_dist
    close_time = bar["Time"] + INTERVAL[leg["tf"]]
    stale = (now - close_time) > pd.Timedelta(hours=STALE_ENTRY_HOURS[leg["tf"]])
    day = bar["Date_VN"]
    if paused:
        add_event(state, now, f"Bỏ qua (đang ngắt mạch): {leg['id']} lúc {fmt_vn(close_time)}")
        return None
    p = dict(id=f"{leg['id']}|{iso(bar['Time'])}", leg=leg["id"], tier=leg["tier"], tf=leg["tf"],
             pair=leg["pair"], direction=leg["direction"], entry_bar=iso(bar["Time"]),
             entry_time=iso(close_time), entry_date_vn=str(day), entry_price=entry,
             sl_price=sl, sl_pct=sl_dist / entry * 100, risk=leg["risk"], spread=leg["spread"],
             max_hold=leg["max_hold"], bars_held=0, last_bar=iso(bar["Time"]),
             last_price=entry, missed=bool(stale))
    state["positions"].append(p)
    arrow = "🟢" if leg["direction"] == "Long" else "🔴"
    text = (f"{arrow} VÀO {leg['direction'].upper()} · {TIER_LABEL[leg['tier']]} · {leg['pair']}\n"
            f"Giá: {px(entry)} | SL: {px(sl)} ({p['sl_pct']:.2f}%)\n"
            f"Thoát khi WPR {'> -20' if sign == 1 else '< -80'} hoặc sau {leg['max_hold']} nến "
            f"{'H1' if leg['tf'] == '1h' else 'H4'}")
    if stale:
        text = "⚠️ TÍN HIỆU CŨ (bỏ lỡ, chỉ để theo dõi):\n" + text + f"\n(nến đóng lúc {fmt_vn(close_time)})"
    add_event(state, now, text.replace("\n", " | "))
    if notify and want_notify(leg["id"]):
        msgs.append(text)
    return p


def process_entries_h1(state, leg, df, now, notify, msgs):
    ws, we = leg["window"]
    hours = df["Hour_VN"]
    win = df[(hours >= ws) & (hours < we)]
    sig = win.groupby("Date_VN")["wpr"].min() if leg["direction"] == "Long" else win.groupby("Date_VN")["wpr"].max()
    checked = ts(state["leg_checked"].get(leg["id"]))
    for idx in df.index[hours == leg["entry_hour"]]:
        bar = df.loc[idx]
        if checked is not None and bar["Time"] <= checked:
            continue
        if idx < WARMUP_BARS:
            continue
        d = bar["Date_VN"]
        if d not in sig.index or pd.isna(sig[d]) or pd.isna(bar["atr"]):
            continue
        ok = sig[d] < leg["threshold"] if leg["direction"] == "Long" else sig[d] > leg["threshold"]
        if leg["exclude_dow"] is not None and pd.Timestamp(d).dayofweek == leg["exclude_dow"]:
            ok = False
        if ok:
            open_position(state, leg, bar, now, notify, msgs, paused=not entries_allowed(state, d))


def process_entries_h4(state, leg, df, now, notify, msgs):
    checked = ts(state["leg_checked"].get(leg["id"]))
    tvn = df["Time_VN"]
    match = (tvn.dt.dayofweek == leg["dow"]) if leg["tier"] == "H4DOW" else (tvn.dt.day == leg["dom"])
    for idx in df.index[match]:
        bar = df.loc[idx]
        if checked is not None and bar["Time"] <= checked:
            continue
        if idx < WARMUP_BARS or pd.isna(bar["wpr"]) or pd.isna(bar["atr"]):
            continue
        ok = bar["wpr"] < leg["threshold"] if leg["direction"] == "Long" else bar["wpr"] > leg["threshold"]
        if ok:
            open_position(state, leg, bar, now, notify, msgs, paused=not entries_allowed(state, bar["Date_VN"]))


# ------------------------------------------------------------------
# THOAT LENH (thu tu kiem tra giong backtest: SL -> WPR -> het so nen)
# ------------------------------------------------------------------
def process_exits(state, p, df, now, notify, msgs):
    last = ts(p["last_bar"])
    sign = 1 if p["direction"] == "Long" else -1
    for _, b in df[df["Time"] > last].iterrows():
        p["bars_held"] += 1
        exit_price, reason = None, None
        if sign == 1 and b["Low"] <= p["sl_price"]:
            exit_price, reason = min(b["Open"], p["sl_price"]), "SL"
        elif sign == -1 and b["High"] >= p["sl_price"]:
            exit_price, reason = max(b["Open"], p["sl_price"]), "SL"
        elif sign == 1 and not pd.isna(b["wpr"]) and b["wpr"] > -20:
            exit_price, reason = b["Close"], "WPR"
        elif sign == -1 and not pd.isna(b["wpr"]) and b["wpr"] < -80:
            exit_price, reason = b["Close"], "WPR"
        elif p["bars_held"] >= p["max_hold"]:
            exit_price, reason = b["Close"], "Hết giờ"
        p["last_bar"] = iso(b["Time"])
        p["last_price"] = float(b["Close"])
        if exit_price is not None:
            close_position(state, p, float(exit_price), reason, b, now, notify, msgs)
            return True
    return False


def close_position(state, p, exit_price, reason, bar, now, notify, msgs):
    sign = 1 if p["direction"] == "Long" else -1
    pnl = sign * (exit_price - p["entry_price"]) / p["entry_price"] * 100 - p["spread"]
    r_mult = pnl / p["sl_pct"]
    close_time = bar["Time"] + INTERVAL[p["tf"]]
    c = dict(p, exit_price=exit_price, exit_reason=reason, exit_time=iso(close_time),
             exit_date_vn=str(bar["Date_VN"]), pnl_pct=pnl, r=r_mult)
    state["positions"] = [x for x in state["positions"] if x["id"] != p["id"]]
    state["closed"].append(c)
    state["closed"] = state["closed"][-300:]
    icon = "✅" if pnl > 0 else "❌"
    text = (f"{icon} THOÁT {p['direction'].upper()} · {TIER_LABEL[p['tier']]} · {p['pair']}\n"
            f"Lý do: {reason} | Giá: {px(exit_price)}\n"
            f"Kết quả: {pnl:+.2f}% giá ({r_mult:+.2f}R) | Vào {fmt_vn(p['entry_time'])}")
    add_event(state, now, text.replace("\n", " | "))
    if notify and want_notify(p["leg"]) and not p.get("missed"):
        msgs.append(text)


def want_notify(leg_id):
    return not NOTIFY_ONLY_LEGS or leg_id in NOTIFY_ONLY_LEGS


def add_event(state, now, text):
    state["events"].append({"time": iso(now), "text": text})
    state["events"] = state["events"][-80:]


# ------------------------------------------------------------------
# LUA CHON CAP CAN LAY DU LIEU LAN NAY
# ------------------------------------------------------------------
def last_entry_bar_open(entry_hour, now):
    """Thoi diem MO (UTC) cua nen H1 gan nhat co gio VN = entry_hour va da dong."""
    latest_closed_open_vn = (now - pd.Timedelta(hours=1)).floor("h") + VN
    t = latest_closed_open_vn.normalize() + pd.Timedelta(hours=entry_hour)
    if t > latest_closed_open_vn:
        t -= pd.Timedelta(days=1)
    return t - VN


def plan_fetches(state, now, force_keys):
    today = vn_date(now)
    days = {today, today - timedelta(days=1)}
    need = {}  # (pair, tf) -> ly do
    open_by = {}
    for p in state["positions"]:
        open_by.setdefault((p["pair"], p["tf"]), []).append(p)

    for leg in LEGS:
        key = (leg["pair"], leg["tf"])
        if leg["tf"] == "1h":
            checked = ts(state["leg_checked"].get(leg["id"]))
            if checked is None or checked < last_entry_bar_open(leg["entry_hour"], now):
                need[key] = "gio vao lenh"
        else:
            match = any((d.weekday() == leg["dow"]) if leg["tier"] == "H4DOW" else (d.day == leg["dom"])
                        for d in days)
            if match and due(state, key, now):
                need.setdefault(key, "dung ngay 4H")
    for key in open_by:
        if key not in need and due(state, key, now):
            need[key] = "theo doi lenh mo"
    for key in force_keys:
        need.setdefault(key, "cham diem cuoi ngay")
    return need


def due(state, key, now):
    nd = state["pair_next_due"].get(f"{key[0]}|{key[1]}")
    return nd is None or now >= pd.Timestamp(nd)


# ------------------------------------------------------------------
# XU LY 1 CAP / 1 KHUNG
# ------------------------------------------------------------------
def handle(state, pair, tf, df, now, notify, msgs):
    stale = is_stale(df, tf, now)
    latest_open = df["Time"].iloc[-1]
    # 1. vao lenh cho moi leg cua cap/khung nay
    for leg in LEGS:
        if leg["pair"] != pair or leg["tf"] != tf:
            continue
        if tf == "1h":
            process_entries_h1(state, leg, df, now, notify, msgs)
            mark = latest_open
            if stale:  # thi truong dong cua -> danh dau da kiem tra toi gio vao gan nhat, khoi hoi lai
                mark = max(latest_open, last_entry_bar_open(leg["entry_hour"], now))
        else:
            process_entries_h4(state, leg, df, now, notify, msgs)
            mark = latest_open
        prev = ts(state["leg_checked"].get(leg["id"]))
        state["leg_checked"][leg["id"]] = iso(mark if prev is None else max(prev, mark))
    # 2. thoat lenh cho cac lenh dang mo cua cap/khung nay (ke ca lenh vua mo)
    for p in [x for x in state["positions"] if x["pair"] == pair and x["tf"] == tf]:
        process_exits(state, p, df, now, notify, msgs)
    # 3. hen lan lay du lieu tiep theo (khi nen ke tiep dong)
    nxt = latest_open + 2 * INTERVAL[tf]
    if stale or nxt <= now:
        nxt = now + (pd.Timedelta(hours=4) if stale else INTERVAL[tf])
    state["pair_next_due"][f"{pair}|{tf}"] = iso(nxt)


# ------------------------------------------------------------------
# DANH GIA NGAT MACH CUOI NGAY (lan chay dau tien sau 00:00 VN)
# ------------------------------------------------------------------
def cb_eval_needed(state, now):
    yesterday = vn_date(now) - timedelta(days=1)
    last = state.get("last_cb_date")
    return (state.get("boot_done") and (now + VN).hour >= CB_EVAL_HOUR_VN
            and (last is None or pd.Timestamp(last).date() < yesterday))


def evaluate_cb(state, now, frames, msgs):
    D = vn_date(now) - timedelta(days=1)
    total, n = 0.0, 0
    for p in state["positions"] + state["closed"]:
        if pd.Timestamp(p["entry_date_vn"]).date() > D:
            continue
        exit_d = pd.Timestamp(p["exit_date_vn"]).date() if p.get("exit_date_vn") else None
        if exit_d is not None and exit_d < D:
            continue
        if exit_d == D:
            mark = p["exit_price"]
        else:
            df = frames.get((p["pair"], p["tf"]))  # dung DUNG khung cua lenh, giong backtest
            if df is None or len(df) == 0:
                mark = p["last_price"]
            else:
                sub = df[df["Date_VN"] == D]
                if len(sub) == 0:
                    continue  # cap nay khong co nen nao trong ngay D (cuoi tuan) -> backtest cung khong tinh
                mark = float(sub["Close"].iloc[-1])
        total += pos_floating(p, mark)
        n += 1
    state["last_cb_date"] = str(D)
    state["floating_history"].append({"date": str(D), "floating": round(total, 3), "n": n})
    state["floating_history"] = state["floating_history"][-120:]
    was_paused = not entries_allowed(state, vn_date(now))
    if total < CIRCUIT_BREAKER_TRIGGER:
        new_pu = pd.Timestamp(D) + pd.Timedelta(days=CIRCUIT_BREAKER_PAUSE_DAYS)
        old = state.get("pause_until")
        if old is None or new_pu > pd.Timestamp(old):
            state["pause_until"] = str(new_pu.date())
        txt = (f"⛔ NGẮT MẠCH{' (gia hạn)' if was_paused else ''}: floating ngày {D:%d/%m} = {total:.2f}% "
               f"(< {CIRCUIT_BREAKER_TRIGGER}%)\nKhông vào lệnh mới đến hết {pd.Timestamp(state['pause_until']):%d/%m/%Y}. "
               f"Lệnh đang mở vẫn giữ theo quy tắc thoát.")
        msgs.append(txt)
        add_event(state, now, txt.replace("\n", " | "))
    elif was_paused and entries_allowed(state, vn_date(now)):
        txt = f"▶️ Hết thời gian ngắt mạch — từ hôm nay được vào lệnh mới trở lại."
        msgs.append(txt)
        add_event(state, now, txt)
    return total


# ------------------------------------------------------------------
# TOM TAT NGAY + LICH HOM NAY
# ------------------------------------------------------------------
def today_schedule(day):
    wd = day.weekday()
    h1 = sorted([l for l in LEGS if l["tier"] == "H1" and l["exclude_dow"] != wd], key=lambda l: l["entry_hour"])
    h4 = [l for l in LEGS if (l["tier"] == "H4DOW" and l["dow"] == wd) or (l["tier"] == "H4DOM" and l["dom"] == day.day)]
    return h1, h4


def daily_summary(state, now):
    day = vn_date(now)
    paused = not entries_allowed(state, day)
    fh = state["floating_history"][-1] if state["floating_history"] else None
    lines = [f"📋 TÓM TẮT {DOW_LABEL[day.weekday()]} {day:%d/%m}"]
    lines.append("⛔ ĐANG NGẮT MẠCH đến " + pd.Timestamp(state["pause_until"]).strftime("%d/%m/%Y")
                 if paused else "✅ Được vào lệnh bình thường")
    if fh:
        lines.append(f"Floating cuối ngày {pd.Timestamp(fh['date']):%d/%m}: {fh['floating']:+.2f}% (ngưỡng {CIRCUIT_BREAKER_TRIGGER}%)")
    lines.append(f"Lệnh đang mở: {len(state['positions'])}")
    for p in sorted(state["positions"], key=lambda x: x["entry_time"]):
        f = pos_floating(p, p["last_price"])
        lines.append(f"  • {p['direction'][0]} {TIER_LABEL[p['tier']]} {p['pair']} từ {fmt_vn(p['entry_time'])} ({f:+.2f}% vốn)")
    if not paused:
        h1, h4 = today_schedule(day)
        if want_any := [l for l in h1 if want_notify(l["id"])]:
            hours = {}
            for l in want_any:
                hours.setdefault(l["entry_hour"] + 1, []).append(f"{l['pair']} {l['direction'][0]}")
            lines.append("Lịch H1 (giờ kiểm tra): " + "; ".join(f"{h % 24}h: {', '.join(v)}" for h, v in sorted(hours.items())))
        h4 = [l for l in h4 if want_notify(l["id"])]
        if h4:
            lines.append("4H hôm nay: " + ", ".join(f"{l['pair']} {l['direction']} ({TIER_LABEL[l['tier']]})" for l in h4))
    return "\n".join(lines)


# ------------------------------------------------------------------
# CHAY 1 LAN
# ------------------------------------------------------------------
def run(now=None, fetcher=None, send=True, state=None, persist=True):
    from twelvedata_client import DailyQuotaExhausted
    now = pd.Timestamp.now(tz="UTC").tz_localize(None).floor("min") if now is None else pd.Timestamp(now)
    fetcher = fetcher or default_fetcher
    state = state if state is not None else load_state()
    msgs = []
    boot = not state.get("boot_done")

    if boot:
        need = {(l["pair"], l["tf"]): "khoi dong" for l in LEGS}
    else:
        force = []
        if cb_eval_needed(state, now):
            D = vn_date(now) - timedelta(days=1)
            # lenh dang mo + lenh da dong SAU ngay D (vd dong luc 1h sang) deu can gia cuoi ngay D
            force = sorted({(p["pair"], p["tf"]) for p in state["positions"]} |
                           {(p["pair"], p["tf"]) for p in state["closed"]
                            if pd.Timestamp(p["exit_date_vn"]).date() > D
                            and pd.Timestamp(p["entry_date_vn"]).date() <= D})
        need = plan_fetches(state, now, force)

    frames, quota_hit = {}, False
    for (pair, tf) in sorted(need, key=lambda k: (k[1], k[0])):
        try:
            size = BOOT_OUTPUTSIZE[tf] if boot else OUTPUTSIZE[tf]
            df = get_closed(pair, tf, now, size, fetcher)
        except DailyQuotaExhausted as e:
            quota_hit = True
            if state.get("quota_alert_date") != str(vn_date(now)):
                msgs.append(f"⚠️ Hết hạn mức API Twelve Data trong ngày — bot tạm dừng lấy dữ liệu tới khi reset.\n{e}")
                state["quota_alert_date"] = str(vn_date(now))
            break
        except Exception as e:  # loi rieng 1 cap: ghi lai, lam tiep cap khac
            add_event(state, now, f"Lỗi lấy dữ liệu {pair} {tf}: {e}")
            continue
        if len(df) < WARMUP_BARS + 5:
            add_event(state, now, f"Dữ liệu {pair} {tf} quá ngắn ({len(df)} nến)")
            continue
        frames[(pair, tf)] = df
        handle(state, pair, tf, df, now, notify=not boot, msgs=msgs)

    if boot and not quota_hit:
        state["boot_done"] = True
        state["last_cb_date"] = str(vn_date(now) - timedelta(days=1))
        msgs.append(f"🤖 Bot đã khởi động. Đang theo dõi {len(state['positions'])} lệnh mở của hệ thống "
                    f"(tái dựng từ dữ liệu gần đây). Thông báo sẽ bắt đầu từ tín hiệu mới.")
    elif not quota_hit and cb_eval_needed(state, now):
        evaluate_cb(state, now, frames, msgs)

    today = vn_date(now)
    if (state.get("boot_done") and state.get("last_summary_date") != str(today)
            and (now + VN).hour >= DAILY_SUMMARY_HOUR_VN):
        msgs.append(daily_summary(state, now))
        state["last_summary_date"] = str(today)

    # thong tin cho app React
    state["legs"] = LEGS
    state["floating_now"] = round(sum(pos_floating(p, p["last_price"]) for p in state["positions"]), 3)
    state["last_run"] = iso(now)
    state["last_fetch"] = [f"{p}|{t}" for (p, t) in need]
    if persist:
        save_state(state)
    if msgs and send:
        import telegram_notify
        telegram_notify.send("\n\n".join(msgs))
    return state, msgs


if __name__ == "__main__":
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        print(err)
        try:
            import telegram_notify
            telegram_notify.send("⚠️ Bot gặp lỗi:\n" + err[-1500:])
        finally:
            sys.exit(1)
