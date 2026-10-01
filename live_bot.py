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
import html as _html
import json
import os
import re
import sys
import traceback
from datetime import timedelta

import numpy as np
import pandas as pd

from config import (TANG1_H1, TANG2_H4_DOW, TANG3_H4_DOM, RISK, MAX_HOLD_H1, MAX_HOLD_H4,
                    CIRCUIT_BREAKER_TRIGGER, CIRCUIT_BREAKER_PAUSE_DAYS, VN_OFFSET_HOURS,
                    SPREAD_PCT_M15, SPREAD_PCT_H4)
from indicators import add_indicators

# ------------------------------------------------------------------
# GUI TELEGRAM (gop san trong file nay, khong can file telegram_notify.py)
# Can 2 bien moi truong trong GitHub Secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# ------------------------------------------------------------------
TG_MAX_LEN = 3800
TG_SEP = "\n\n"


def _tg_plain(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s))


def _tg_pack(blocks):
    """Gop cac khoi thanh tung tin <= TG_MAX_LEN, khong cat ngang 1 khoi (tranh vo khung <pre>)."""
    out, buf = [], ""
    for b in blocks:
        if len(b) > TG_MAX_LEN:
            if buf:
                out.append(buf); buf = ""
            cur = ""
            for ln in _tg_plain(b).split("\n"):
                if len(cur) + len(ln) + 1 > TG_MAX_LEN and cur:
                    out.append(_html.escape(cur, quote=False)); cur = ""
                cur += ln + "\n"
            if cur.strip():
                out.append(_html.escape(cur, quote=False))
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
        print("[Telegram chua cau hinh - chi in ra log]\n" + _tg_plain(TG_SEP.join(blocks)))
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for msg in _tg_pack(blocks):
        try:
            r = requests.post(url, json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML",
                                         "disable_web_page_preview": True}, timeout=15)
            if r.status_code == 400:  # Telegram tu choi dinh dang -> gui lai dang chu thuong
                print("Telegram tu choi HTML, gui lai dang chu thuong:", r.text[:200])
                r = requests.post(url, json={"chat_id": chat_id, "text": _tg_plain(msg),
                                             "disable_web_page_preview": True}, timeout=15)
            if not r.ok:
                ok = False
                print("Loi gui Telegram:", r.status_code, r.text[:200])
        except requests.RequestException as e:
            ok = False
            print("Loi ket noi Telegram:", e)
    return ok

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
# Lop bao ve thu 2 (kiem chung walk-forward 16 nam): von he thong sut tu dinh -> giam khoi luong lenh moi.
# Vao bac khi sut >= nguong; ra khoi bac khi hoi con sut <= nguong/2.
RISK_TIERS = [(12.0, 0.5), (20.0, 0.25)]
# CHOT HET THEO FLOATING: tong floating (% von) cua cac lenh ban trade >= nguong -> bao chot het.
# Doi so nay de doi nguong; dat 0 de tat. Chi bao lai khi floating da xuong duoi (nguong - FLOAT_REARM_GAP).
FLOAT_CLOSE_PCT = 3.0
FLOAT_REARM_GAP = 1.0
# Khi cham nguong: giu lai bao nhieu phan khoi luong moi lenh (0.5 = chot mot nua; 0 = chot het).
# Moi lenh chi bi chot bot 1 lan.
KEEP_FRACTION = 0.5
FACTOR_LABEL = {1.0: "bình thường", 0.5: "½", 0.25: "¼"}
INTERVAL = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4)}
VN = pd.Timedelta(hours=VN_OFFSET_HOURS)
DOW_LABEL = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
TIER_LABEL = {"H1": "H1", "H4DOW": "4H-Thứ", "H4DOM": "4H-Ngày"}
TF_LABEL = {"1h": "H1", "4h": "H4"}
TIER_SHORT = {"H1": "H1", "H4DOW": "4H-T", "H4DOM": "4H-N"}
TIER_ORDER = {"H1": 0, "H4DOW": 1, "H4DOM": 2}
ARROW = {"Long": "▲", "Short": "▼"}
DOW_FULL = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]


def esc(s):
    return _html.escape(str(s), quote=False)


def plain(s):
    """Ban chu thuong (bo the HTML) de luu nhat ky cho app."""
    return _html.unescape(re.sub(r"<[^>]+>", "", s))


def title(icon, action, pair, direction, tier):
    return f"{icon} <b>{action} · {pair} {direction.upper()}</b> · {TIER_LABEL[tier]}"


def exit_short(direction):
    return "WPR vượt -20" if direction == "Long" else "WPR xuống dưới -80"
# Canh bao "sap chot" (moi loai bao 1 lan / lenh)
NEAR_WPR_POINTS = 15               # WPR cach nguong chot <= 15 diem (Long: > -35, Short: < -65)
NEAR_BARS_LEFT = {"1h": 3, "4h": 1}  # con <= so nen nay truoc khi het gio
NEAR_SL_FRACTION = 0.25            # gia con cach SL <= 25% khoang SL ban dau


def pip_size(pair):
    if pair == "XAUUSD":
        return 0.1
    if pair == "BTCUSD":
        return 1.0
    return 0.01 if pair.endswith("JPY") else 0.0001


def pip_unit(pair):
    return "điểm" if pair == "BTCUSD" else "pip"


def pips(pair, diff):
    return diff / pip_size(pair)


def fp(pair, x, signed=False):
    """Dinh dang so pip, vd '+35.2 pip'."""
    return (f"{x:+.1f}" if signed else f"{x:.1f}") + " " + pip_unit(pair)


def exit_rule(direction):
    return "WPR vượt lên trên -20" if direction == "Long" else "WPR xuống dưới -80"


def _hour_open(t):
    wd, h = t.weekday(), t.hour  # gio UTC, cung quy tac voi drop_weekend()
    return not (wd == 5 or (wd == 4 and h >= 22) or (wd == 6 and h < 21))


def bar_exists(t, tf, pair):
    if tf == "4h" and t.weekday() == 6:
        return False
    n = int(INTERVAL[tf] / pd.Timedelta(hours=1))
    return any(_hour_open(t + pd.Timedelta(hours=k)) for k in range(n))


def project_deadline(last_bar_open, tf, bars_left, pair):
    """Uoc tinh gio dong cua nen cuoi cung neu giu toi da (bo qua cuoi tuan)."""
    t, n = pd.Timestamp(last_bar_open), 0
    while n < bars_left:
        t += INTERVAL[tf]
        if bar_exists(t, tf, pair):
            n += 1
    return t + INTERVAL[tf]


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
    """So chu so le co dinh de bang thang cot: 1.15480 / 150.335 / 4165.25 / 83921.5"""
    x = float(x)
    if abs(x) < 50:
        return f"{x:.5f}"
    if abs(x) < 1000:
        return f"{x:.3f}"
    return f"{x:.2f}" if abs(x) < 10000 else f"{x:.1f}"


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


def drop_weekend(df):
    """Bo nen luc thi truong dong cua, giong du lieu backtest: khong co nen thu 7,
    nen chu nhat chi tu 21h UTC, nen thu 6 chi den 21h UTC. (Twelve Data co tra
    nen cuoi tuan cho mot so cap -> neu khong bo se sinh lenh ao.)"""
    wd, h = df["Time"].dt.weekday, df["Time"].dt.hour
    closed = (wd == 5) | ((wd == 6) & (h < 21)) | ((wd == 4) & (h >= 22))
    return df[~closed]


def raw_size(tf, boot):
    """So nen H1 can tai de co du so nen cua khung tf."""
    n = (BOOT_OUTPUTSIZE if boot else OUTPUTSIZE)[tf]
    return n if tf == "1h" else n * 4 + 8


def get_closed(pair, tf, now, raw_h1):
    """raw_h1: nen H1 tu Twelve Data. Nen 4H duoc GHEP tu H1 theo moc 00/04/08/.. UTC
    (giong du lieu backtest) thay vi dung nen 4H cua Twelve Data (moc lech 1-2 gio)."""
    h1 = drop_weekend(raw_h1)
    h1 = h1[h1["Time"] + INTERVAL["1h"] <= now]
    if tf == "1h":
        df = h1
    else:
        df = (h1.set_index("Time")
                .resample("4h", origin="epoch", label="left", closed="left")
                .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"})
                .dropna().reset_index())
        # Du lieu 4H backtest khong co nen chu nhat 20:00 UTC (3 nen H1 luc vua mo cua dau tuan)
        df = df[(df["Time"].dt.weekday != 6) & (df["Time"] + INTERVAL["4h"] <= now)]
    return add_indicators(df.reset_index(drop=True))


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
def open_position(state, leg, bar, now, notify, msgs, paused, boot=False):
    sign = 1 if leg["direction"] == "Long" else -1
    entry = float(bar["Close"])
    sl_dist = float(bar["atr"]) * leg["atr_mult"]
    sl = entry - sign * sl_dist
    close_time = bar["Time"] + INTERVAL[leg["tf"]]
    stale = (not boot) and (now - close_time) > pd.Timedelta(hours=STALE_ENTRY_HOURS[leg["tf"]])
    day = bar["Date_VN"]
    if paused:
        add_event(state, now, f"Bỏ qua (đang ngắt mạch): {leg['id']} lúc {fmt_vn(close_time)}")
        return None
    pair = leg["pair"]
    sl_pips = pips(pair, sl_dist)
    deadline = project_deadline(bar["Time"], leg["tf"], leg["max_hold"], pair)
    wpr_now = None if pd.isna(bar["wpr"]) else float(bar["wpr"])
    factor = state.get("risk_factor", 1.0)
    p = dict(id=f"{leg['id']}|{iso(bar['Time'])}", leg=leg["id"], tier=leg["tier"], tf=leg["tf"],
             pair=pair, direction=leg["direction"], entry_bar=iso(bar["Time"]),
             entry_time=iso(close_time), entry_date_vn=str(day), entry_price=entry,
             sl_price=sl, sl_pct=sl_dist / entry * 100, risk=leg["risk"] * factor, size_factor=factor,
             spread=leg["spread"],
             max_hold=leg["max_hold"], bars_held=0, last_bar=iso(bar["Time"]),
             last_price=entry, missed=bool(stale),
             pip=pip_size(pair), sl_pips=sl_pips, pips_to_sl=sl_pips, pnl_pips=0.0,
             last_wpr=wpr_now, deadline=iso(deadline), warned=[], rebuilt=bool(boot))
    state["positions"].append(p)
    icon = "🟢" if leg["direction"] == "Long" else "🔴"
    tfl = TF_LABEL[leg["tf"]]
    cond = "WPR > -20" if leg["direction"] == "Long" else "WPR < -80"
    wpr_txt = f" (đang {wpr_now:.0f})" if wpr_now is not None else ""
    box = (f"Vào   {px(entry)}\n"
           f"SL    {px(sl)}  ({fp(pair, sl_pips)})\n"
           f"Chốt  {cond}{wpr_txt}\n"
           f"Hạn   {fmt_vn(deadline)} · {leg['max_hold']} nến")
    size_txt = "" if factor >= 1 else (f"\n⚠️ <b>Khối lượng {FACTOR_LABEL.get(factor, factor)} mức thường</b> "
                                        f"(vốn hệ thống đang sụt {state.get('equity_dd', 0):.1f}%)")
    text = (title(icon, "VÀO", pair, leg["direction"], leg["tier"]) + "\n"
            f"<pre>{esc(box)}</pre>{size_txt}\nĐặt SL trên sàn ngay khi vào lệnh.")
    if stale:
        text = (f"⚠️ <b>Tín hiệu cũ</b> (nến đóng {fmt_vn(close_time)}, bot bị gián đoạn) — chỉ để theo dõi\n" + text)
    add_event(state, now, plain(text).replace("\n", " | "))
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
            open_position(state, leg, bar, now, notify, msgs, paused=not entries_allowed(state, d),
                          boot=not notify)


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
            open_position(state, leg, bar, now, notify, msgs, paused=not entries_allowed(state, bar["Date_VN"]),
                          boot=not notify)


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
        if not pd.isna(b["wpr"]):
            p["last_wpr"] = float(b["wpr"])
        if exit_price is not None:
            close_position(state, p, float(exit_price), reason, b, now, notify, msgs)
            return True
    if len(df[df["Time"] > last]):
        update_and_warn(state, p, now, notify, msgs)
    return False


def update_and_warn(state, p, now, notify, msgs):
    """Cap nhat pip/han chot cua lenh dang mo va gui canh bao 'sap chot' (moi loai 1 lan)."""
    pair, sign = p["pair"], (1 if p["direction"] == "Long" else -1)
    p.setdefault("warned", [])
    p.setdefault("sl_pips", pips(pair, abs(p["entry_price"] - p["sl_price"])))
    p["pip"] = pip_size(pair)
    p["pnl_pips"] = pips(pair, sign * (p["last_price"] - p["entry_price"]))
    p["pips_to_sl"] = pips(pair, sign * (p["last_price"] - p["sl_price"]))
    left = p["max_hold"] - p["bars_held"]
    p["deadline"] = iso(project_deadline(p["last_bar"], p["tf"], left, pair))
    if not notify:  # dang khoi dong: chi cap nhat so lieu, de canh bao duoc gui o lan chay that dau tien
        return
    tfl = TF_LABEL[p["tf"]]
    pnl = f"Tạm tính <b>{fp(pair, p['pnl_pips'], True)}</b>"
    out = []
    w = p.get("last_wpr")
    if w is not None and "wpr" not in p["warned"]:
        near = w > -20 - NEAR_WPR_POINTS if sign == 1 else w < -80 + NEAR_WPR_POINTS
        if near:
            p["warned"].append("wpr")
            out.append(title("⏳", "SẮP CHỐT", pair, p["direction"], p["tier"]) + "\n"
                       f"WPR {tfl} đang {w:.1f}, chốt khi {exit_short(p['direction'])} "
                       f"(có thể ngay nến {tfl} kế tiếp)\n{pnl}")
    if left <= NEAR_BARS_LEFT[p["tf"]] and "time" not in p["warned"]:
        p["warned"].append("time")
        out.append(title("⏳", "SẮP HẾT GIỜ", pair, p["direction"], p["tier"]) + "\n"
                   f"Còn {left} nến {tfl}, tự chốt khoảng {fmt_vn(p['deadline'])}\n{pnl}")
    if p["pips_to_sl"] <= NEAR_SL_FRACTION * p["sl_pips"] and "sl" not in p["warned"]:
        p["warned"].append("sl")
        out.append(title("⚠️", "GẦN CẮT LỖ", pair, p["direction"], p["tier"]) + "\n"
                   f"Còn {fp(pair, max(p['pips_to_sl'], 0))} tới SL {px(p['sl_price'])}\n{pnl}")
    for t in out:
        t += origin_note(p)
        add_event(state, now, plain(t).replace("\n", " | "))
        if notify and want_notify(p["leg"]):
            msgs.append(t)


def close_position(state, p, exit_price, reason, bar, now, notify, msgs):
    sign = 1 if p["direction"] == "Long" else -1
    pnl = sign * (exit_price - p["entry_price"]) / p["entry_price"] * 100 - p["spread"]
    r_mult = pnl / p["sl_pct"]
    close_time = bar["Time"] + INTERVAL[p["tf"]]
    ret = p["risk"] / 100 * r_mult  # loi/lo theo ty le von (da tinh he so khoi luong)
    c = dict(p, exit_price=exit_price, exit_reason=reason, exit_time=iso(close_time),
             exit_date_vn=str(bar["Date_VN"]), pnl_pct=pnl, r=r_mult, ret=ret)
    state["realized"] = state.get("realized", 0.0) + ret
    state["positions"] = [x for x in state["positions"] if x["id"] != p["id"]]
    state["closed"].append(c)
    state["closed"] = state["closed"][-300:]
    pair = p["pair"]
    pip_res = pips(pair, sign * (exit_price - p["entry_price"]))
    c["pnl_pips"] = pip_res
    why = {"SL": "chạm SL", "WPR": exit_rule(p["direction"]),
           "Hết giờ": f"hết {p['max_hold']} nến {TF_LABEL[p['tf']]}",
           "Chốt hết": "chốt hết theo floating",
           "Chốt một nửa": "chốt một phần theo floating"}[reason]
    icon = "✅" if pnl > 0 else "❌"
    text = (title(icon, "ĐÃ CHỐT", pair, p["direction"], p["tier"]) + "\n"
            f"<b>{fp(pair, pip_res, True)}</b>  ({r_mult:+.2f}R)\n"
            f"Lý do: {why}\n"
            f"{px(p['entry_price'])} → {px(exit_price)} · giữ {p['bars_held']} nến {TF_LABEL[p['tf']]}")
    text += origin_note(p)
    add_event(state, now, plain(text).replace("\n", " | "))
    if notify and want_notify(p["leg"]):
        msgs.append(text)


def origin_note(p):
    kept = p.get("kept_frac", 1.0)
    if kept < 1 and not p.get("is_partial"):
        return f"\n<i>Phần còn lại {kept * 100:.0f}% khối lượng (đã chốt bớt theo floating)</i>"
    if p.get("rebuilt"):
        return "\n<i>Lệnh có từ trước khi bot chạy</i>"
    if p.get("missed"):
        return "\n<i>Tín hiệu bỏ lỡ lúc bot gián đoạn</i>"
    return ""


def cur_price(p):
    return p.get("mark", p["last_price"])


def refresh_marks(state, now, raw, fetcher):
    """Gia moi nhat (nen H1 da dong) cho MOI cap dang co lenh mo, ke ca lenh 4H, de canh floating moi gio."""
    from twelvedata_client import DailyQuotaExhausted
    for pair in sorted({p["pair"] for p in state["positions"]}):
        try:
            if pair not in raw:
                raw[pair] = fetcher(pair, "1h", 12)
            h1 = drop_weekend(raw[pair])
            h1 = h1[h1["Time"] + INTERVAL["1h"] <= now]
            if not len(h1):
                continue
            last = h1.iloc[-1]
        except DailyQuotaExhausted:
            return False
        except Exception as e:
            add_event(state, now, f"Lỗi cập nhật giá {pair}: {e}")
            continue
        for p in state["positions"]:
            if p["pair"] == pair and pd.Timestamp(p["last_bar"]) <= last["Time"] + INTERVAL["1h"]:
                p["mark"] = float(last["Close"])
                p["mark_time"] = iso(last["Time"] + INTERVAL["1h"])
    return True


def check_close_all(state, now, msgs):
    """Tong floating cac lenh ban trade >= FLOAT_CLOSE_PCT -> chot bot (KEEP_FRACTION) hoac chot het.
    Moi lenh chi bi chot bot 1 lan; phan con lai giu SL va dieu kien thoat cu."""
    sel = [p for p in state["positions"] if want_notify(p["leg"])]
    F = sum(pos_floating(p, cur_price(p)) for p in sel)
    state["floating_sel"] = round(F, 3)
    if FLOAT_CLOSE_PCT <= 0:
        return
    armed = state.get("fc_armed", True)
    if not armed and F < FLOAT_CLOSE_PCT - FLOAT_REARM_GAP:
        state["fc_armed"] = armed = True
    targets = [p for p in sel if p.get("kept_frac", 1.0) >= 1.0]   # chua tung bi chot bot
    if not armed or not targets or F < FLOAT_CLOSE_PCT:
        return
    keep = KEEP_FRACTION if 0 < KEEP_FRACTION < 1 else 0.0
    rows = []
    for p in sorted(targets, key=lambda x: (TIER_ORDER[x["tier"]], x["pair"])):
        sign = 1 if p["direction"] == "Long" else -1
        pp = pips(p["pair"], sign * (cur_price(p) - p["entry_price"]))
        rows.append(f"{ARROW[p['direction']]} {p['pair']:<6} {TIER_SHORT[p['tier']]:<4} {pp:>+6.0f}p  {px(cur_price(p))}")
    for p in targets:
        mt = pd.Timestamp(p.get("mark_time") or p["last_bar"])
        bar = {"Time": mt - INTERVAL[p["tf"]], "Date_VN": (mt - INTERVAL["1h"] + VN).date()}
        if keep == 0:
            close_position(state, p, cur_price(p), "Chốt hết", bar, now, notify=False, msgs=msgs)
        else:
            part = dict(p, id=p["id"] + "|mot_phan", risk=p["risk"] * (1 - keep), is_partial=True)
            close_position(state, part, cur_price(p), "Chốt một nửa", bar, now, notify=False, msgs=msgs)
            p["risk"] *= keep
            p["size_factor"] = p.get("size_factor", 1.0) * keep
            p["kept_frac"] = keep
    state["fc_armed"] = False
    if keep == 0:
        head = f"💰 <b>CHỐT HẾT — floating {F:+.2f}% vốn</b> (ngưỡng {FLOAT_CLOSE_PCT:.0f}%)\nĐóng toàn bộ {len(targets)} lệnh:"
        tail = "Tín hiệu mới vẫn vào bình thường, đúng khối lượng hệ thống."
    else:
        head = (f"💰 <b>CHỐT {'MỘT NỬA' if keep == 0.5 else f'{(1 - keep) * 100:.0f}%'} — floating {F:+.2f}% vốn</b> "
                f"(ngưỡng {FLOAT_CLOSE_PCT:.0f}%)\nĐóng <b>{(1 - keep) * 100:.0f}% khối lượng</b> của mỗi lệnh ({len(targets)} lệnh):")
        tail = ("Phần còn lại giữ nguyên SL và điều kiện thoát — bot vẫn báo thoát như bình thường.\n"
                "Tín hiệu mới vẫn vào đúng khối lượng hệ thống.")
    txt = f"{head}\n<pre>{esc(chr(10).join(rows))}</pre>\n{tail}\n<b>Không gỡ, không tăng lot.</b>"
    msgs.append(txt)
    add_event(state, now, plain(txt).replace("\n", " | "))


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
    total, n, float_open = 0.0, 0, 0.0
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
        v = pos_floating(p, mark)
        total += v
        n += 1
        if exit_d != D:
            float_open += v
    state["last_cb_date"] = str(D)
    update_equity_tiers(state, now, D, float_open, msgs)
    state["floating_history"].append({"date": str(D), "floating": round(total, 3), "n": n,
                                      "equity_dd": round(state.get("equity_dd", 0.0), 2)})
    state["floating_history"] = state["floating_history"][-120:]
    was_paused = not entries_allowed(state, vn_date(now))
    if total < CIRCUIT_BREAKER_TRIGGER:
        new_pu = pd.Timestamp(D) + pd.Timedelta(days=CIRCUIT_BREAKER_PAUSE_DAYS)
        old = state.get("pause_until")
        if old is None or new_pu > pd.Timestamp(old):
            state["pause_until"] = str(new_pu.date())
        txt = (f"⛔ <b>NGẮT MẠCH{' (gia hạn)' if was_paused else ''}</b>\n"
               f"Floating chốt ngày {D:%d/%m}: <b>{total:+.2f}%</b> (ngưỡng {CIRCUIT_BREAKER_TRIGGER:.0f}%)\n"
               f"Không vào lệnh mới đến hết <b>{pd.Timestamp(state['pause_until']):%d/%m/%Y}</b>.\n"
               f"Lệnh đang mở vẫn giữ, chốt theo quy tắc cũ.")
        msgs.append(txt)
        add_event(state, now, plain(txt).replace("\n", " | "))
    elif was_paused and entries_allowed(state, vn_date(now)):
        txt = "▶️ <b>Hết ngắt mạch</b>\nTừ hôm nay vào lệnh mới bình thường."
        msgs.append(txt)
        add_event(state, now, plain(txt).replace("\n", " | "))
    return total


def update_equity_tiers(state, now, D, float_open_pct, msgs):
    """Von he thong = 1 + loi/lo da chot (tinh den het ngay D) + floating lenh con mo cuoi ngay D.
    Sut tu dinh >= 12% -> khoi luong 1/2; >= 20% -> 1/4; hoi ve <= nguong/2 thi nang lai 1 bac."""
    later = sum(c.get("ret", 0.0) for c in state["closed"]
                if c.get("exit_date_vn") and pd.Timestamp(c["exit_date_vn"]).date() > D)
    eq = 1.0 + state.get("realized", 0.0) - later + float_open_pct / 100
    peak = max(state.get("equity_peak") or eq, eq)
    dd = (1 - eq / peak) * 100
    state["equity"], state["equity_peak"], state["equity_dd"] = round(eq, 5), round(peak, 5), round(dd, 3)
    lvl = old = state.get("risk_level", 0)
    while lvl < len(RISK_TIERS) and dd >= RISK_TIERS[lvl][0]:
        lvl += 1
    while lvl > 0 and dd <= RISK_TIERS[lvl - 1][0] / 2:
        lvl -= 1
    state["risk_level"] = lvl
    state["risk_factor"] = RISK_TIERS[lvl - 1][1] if lvl else 1.0
    if lvl != old:
        f = FACTOR_LABEL.get(state["risk_factor"], state["risk_factor"])
        if lvl > old:
            nxt = RISK_TIERS[lvl - 1][0] / 2
            txt = (f"⚠️ <b>GIẢM KHỐI LƯỢNG còn {f}</b>\nVốn hệ thống sụt <b>{dd:.1f}%</b> so với đỉnh "
                   f"(ngưỡng {RISK_TIERS[lvl - 1][0]:.0f}%).\nMọi lệnh mới vào với {f} khối lượng thường "
                   f"cho đến khi mức sụt về dưới {nxt:.0f}%.")
        else:
            txt = (f"▶️ <b>Nâng khối lượng lên {f}</b>\nVốn hệ thống đã hồi, còn sụt {dd:.1f}% so với đỉnh.")
        msgs.append(txt)
        add_event(state, now, plain(txt).replace("\n", " | "))


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
    hour_now = (now + VN).hour
    paused = not entries_allowed(state, day)
    L = [f"📋 <b>{DOW_FULL[day.weekday()]}, {day:%d/%m}</b>"]
    if paused:
        L.append(f"⛔ Đang ngắt mạch đến <b>{pd.Timestamp(state['pause_until']):%d/%m}</b>, không vào lệnh mới")
    else:
        L.append("✅ Được vào lệnh bình thường")
    fh = state["floating_history"][-1] if state["floating_history"] else None
    if fh:
        L.append(f"Floating chốt {pd.Timestamp(fh['date']):%d/%m}: <b>{fh['floating']:+.2f}%</b> "
                 f"· ngưỡng {CIRCUIT_BREAKER_TRIGGER:.0f}%")
    if "equity_dd" in state:
        fct = state.get("risk_factor", 1.0)
        L.append(f"Vốn hệ thống sụt {state['equity_dd']:.1f}% so với đỉnh · khối lượng "
                 + (f"<b>{FACTOR_LABEL.get(fct, fct)}</b>" if fct < 1 else "bình thường")
                 + f" (giảm ½ khi sụt {RISK_TIERS[0][0]:.0f}%)")

    pos = sorted(state["positions"], key=lambda p: (TIER_ORDER[p["tier"]], p["pair"], p["entry_time"]))
    L.append("")
    if pos:
        total = sum(pos_floating(p, cur_price(p)) for p in pos)
        L.append(f"<b>Đang mở {len(pos)} lệnh</b> · tạm tính {total:+.2f}% vốn")
        if FLOAT_CLOSE_PCT > 0:
            fs = sum(pos_floating(p, cur_price(p)) for p in pos if want_notify(p["leg"]))
            act = "chốt hết" if not (0 < KEEP_FRACTION < 1) else ("chốt một nửa" if KEEP_FRACTION == 0.5 else f"chốt {(1 - KEEP_FRACTION) * 100:.0f}%")
            L.append(f"Floating các lệnh bạn trade: {fs:+.2f}% · báo {act} ở +{FLOAT_CLOSE_PCT:.0f}%")
        rows = []
        for p in pos:
            sign = 1 if p["direction"] == "Long" else -1
            pnl_p = pips(p["pair"], sign * (cur_price(p) - p["entry_price"]))
            to_sl = pips(p["pair"], sign * (cur_price(p) - p["sl_price"]))
            half = "½" if p.get("kept_frac", 1.0) < 1 else " "
            rows.append(f"{ARROW[p['direction']]} {p['pair']:<6} {TIER_SHORT[p['tier']]:<4}"
                        f"{pnl_p:>+5.0f}p  SL {max(to_sl, 0):>3.0f}p {half}")
        L.append("<pre>" + esc("\n".join(rows)) + "</pre>")
        L.append("<i>p = pip đang lãi/lỗ · SL = pip còn tới cắt lỗ · ½ = đã chốt một nửa</i>")
    else:
        L.append("Không có lệnh nào đang mở.")

    if not paused:
        h1, h4 = today_schedule(day)
        day_vn0 = pd.Timestamp(day)  # 00:00 gio VN cua ngay
        groups = {}
        for l in h1:
            h = (l["entry_hour"] + 1) % 24  # gio bao = luc nen gio vao dong
            bar_open_utc = day_vn0 + pd.Timedelta(hours=l["entry_hour"]) - VN
            if h > hour_now and want_notify(l["id"]) and bar_exists(bar_open_utc, "1h", l["pair"]):
                groups.setdefault(h, []).append(f"{l['pair']}{ARROW[l['direction']]}")
        if groups:
            L.append("")
            L.append("<b>Lịch H1 còn lại hôm nay</b> (giờ báo)")
            lines = []
            for h, v in sorted(groups.items()):  # toi da 3 cap / dong cho vua man hinh dien thoai
                for i in range(0, len(v), 3):
                    lines.append((f"{h:02d}h  " if i == 0 else " " * 5) + " ".join(v[i:i + 3]))
            L.append("<pre>" + esc("\n".join(lines)) + "</pre>")
        # cac nen 4H cua ngay VN nay (mo luc 03,07,11,15,19,23h VN) chua dong va thi truong co mo
        closes = []
        for k in range(6):
            open_utc = (day_vn0 + pd.Timedelta(hours=3 + 4 * k)) - VN
            close_utc = open_utc + INTERVAL["4h"]
            if close_utc > now and bar_exists(open_utc, "4h", "EURUSD"):
                closes.append((close_utc + VN).hour)
        h4 = [l for l in h4 if want_notify(l["id"])]
        if h4 and closes:
            L.append("")
            L.append("<b>4H hôm nay</b>")
            L.append("Xét lúc " + ", ".join(f"{h:02d}h" for h in closes))
            L.append("<pre>" + esc("\n".join(
                f"{ARROW[l['direction']]} {l['pair']:<6} {'theo thứ' if l['tier'] == 'H4DOW' else 'theo ngày'}"
                for l in sorted(h4, key=lambda x: (x['tier'], x['pair'])))) + "</pre>")
        if not groups and not (h4 and closes):
            L.append("")
            L.append("Hôm nay không còn giờ xét tín hiệu nào (thị trường nghỉ hoặc đã qua hết).")
    return "\n".join(L)


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
    if state.get("boot_done") and not state.get("boot_fix_v2"):
        for p in state["positions"] + state["closed"]:
            if p.get("missed"):
                p["missed"], p["rebuilt"] = False, True
                p["warned"] = []  # canh bao da bi danh dau am tham luc khoi dong -> cho gui lai
        state["boot_fix_v2"] = True

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

    frames, quota_hit, raw = {}, False, {}
    sizes = {}
    for (pair, tf) in need:
        sizes[pair] = max(sizes.get(pair, 0), raw_size(tf, boot))
    for (pair, tf) in sorted(need, key=lambda k: (k[0], k[1])):
        try:
            if pair not in raw:
                raw[pair] = fetcher(pair, "1h", sizes[pair])
            df = get_closed(pair, tf, now, raw[pair])
        except DailyQuotaExhausted as e:
            quota_hit = True
            if state.get("quota_alert_date") != str(vn_date(now)):
                msgs.append("⚠️ <b>Hết hạn mức API Twelve Data hôm nay</b>\n"
                            "Bot tạm dừng lấy dữ liệu, tự chạy lại khi hạn mức reset (7h sáng giờ VN).")
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

    if not boot and not quota_hit and state["positions"]:
        if refresh_marks(state, now, raw, fetcher):
            check_close_all(state, now, msgs)

    if boot and not quota_hit:
        state["boot_done"] = True
        state["boot_fix_v2"] = True
        state["realized"] = 0.0          # von he thong tinh tu luc bot chay
        state["equity_peak"] = None
        state["last_cb_date"] = str(vn_date(now) - timedelta(days=1))
        msgs.append(f"🤖 <b>Bot đã chạy</b>\nĐang theo dõi {len(state['positions'])} lệnh mở của hệ thống "
                    f"(dựng lại từ dữ liệu gần đây). Từ giờ bot báo khi có tín hiệu mới.")
    elif not quota_hit and cb_eval_needed(state, now):
        evaluate_cb(state, now, frames, msgs)

    today = vn_date(now)
    if (state.get("boot_done") and state.get("last_summary_date") != str(today)
            and (now + VN).hour >= DAILY_SUMMARY_HOUR_VN):
        msgs.append(daily_summary(state, now))
        state["last_summary_date"] = str(today)

    # thong tin cho app React
    state["legs"] = LEGS
    state["floating_now"] = round(sum(pos_floating(p, cur_price(p)) for p in state["positions"]), 3)
    state["float_close_pct"] = FLOAT_CLOSE_PCT
    state["last_run"] = iso(now)
    state["last_fetch"] = [f"{p}|{t}" for (p, t) in need]
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
