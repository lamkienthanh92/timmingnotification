"""
================================================================================
DAILY_CHECK.PY -- chay 1 LAN MOI NGAY
================================================================================
KHONG tu dong vao lenh. Ban tu vao lenh tren TradingView, roi ghi lai vao
data/positions.json. Script nay chi doc file do, lay GIA HIEN TAI cho DUNG
NHUNG CAP BAN DANG GIU (khong phai het 20 cap), roi tra loi 3 cau hoi:

  1. Portfolio cua ban dang lai/lo NOI (floating) bao nhieu % tong the?
  2. Co dang bi "ngat mach" khong (floating < -4% trong 45 ngay gan day)?
     -> Neu co: KHUYEN NGHI khong vao lenh moi hom nay.
  3. Voi tung lenh dang giu: co dau hieu NEN CAN NHAC DONG khong (WPR da quay
     ve nguong doi dien, hoac da qua 96h) -- ban tu quyet dinh dong tren
     TradingView, script chi GOI Y, khong tu dong dong lenh.

Chay:
    python daily_check.py
================================================================================
"""
import json
import os
from datetime import datetime, timezone, timedelta
import pandas as pd

from config import VN_OFFSET_HOURS, CIRCUIT_BREAKER_TRIGGER, CIRCUIT_BREAKER_PAUSE_DAYS
from twelvedata_client import fetch_time_series, TwelveDataError
from indicators import add_indicators

POSITIONS_FILE = "data/positions.json"
BREAKER_STATE_FILE = "data/breaker_state.json"


def load_positions():
    with open(POSITIONS_FILE, "r") as f:
        data = json.load(f)
    return data["positions"]


def load_breaker_state():
    if not os.path.exists(BREAKER_STATE_FILE):
        return {"pause_until": None, "history": []}
    with open(BREAKER_STATE_FILE, "r") as f:
        return json.load(f)


def save_breaker_state(state):
    os.makedirs("data", exist_ok=True)
    with open(BREAKER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def fetch_price_for_position(pos):
    """Lay 1 chuoi gia gan day cho dung cap+timeframe cua vi the nay.
    H1 -> lay nen 1h (de kiem tra WPR/SL chinh xac hon).
    H4DOW/H4DOM -> lay nen 4h."""
    interval = "1h" if pos["tier"] == "H1" else "4h"
    df = fetch_time_series(pos["pair"], interval, outputsize=60)
    return add_indicators(df)


def main():
    now_utc = datetime.now(timezone.utc)
    now_vn = now_utc + timedelta(hours=VN_OFFSET_HOURS)
    print(f"=== Kiem tra danh muc luc {now_vn.strftime('%Y-%m-%d %H:%M')} (gio VN) ===\n")

    positions = load_positions()
    if not positions:
        print("Chua co lenh nao trong data/positions.json -- khong co gi de kiem tra.")
        return

    breaker_state = load_breaker_state()

    total_floating = 0.0
    price_cache = {}   # cache theo (pair,tier) trong 1 lan chay, tranh goi API trung
    results = []

    for pos in positions:
        key = (pos["pair"], pos["tier"])
        if key not in price_cache:
            try:
                price_cache[key] = fetch_price_for_position(pos)
            except TwelveDataError as e:
                print(f"  [Loi] Khong lay duoc gia {pos['pair']}: {e}")
                continue
        df = price_cache[key]
        last = df.iloc[-1]
        current_price = last["Close"]
        wpr_now = last["wpr"]

        sign = 1 if pos["direction"] == "Long" else -1
        size_mult = pos["risk_pct"] / (abs(pos["entry_price"] - pos["sl_price"]) / pos["entry_price"] * 100)
        floating_pct_price = sign * (current_price - pos["entry_price"]) / pos["entry_price"] * 100
        floating_acc = size_mult * floating_pct_price / 100 * 100  # dang % von, de doc
        total_floating += floating_acc

        # goi y co nen can nhac dong khong
        suggestions = []
        opp_thresh = -20 if pos["direction"] == "Long" else -80
        if pos["direction"] == "Long" and wpr_now > opp_thresh:
            suggestions.append("WPR da quay ve vung doi dien -- CAN NHAC CHOT LOI")
        if pos["direction"] == "Short" and wpr_now < opp_thresh:
            suggestions.append("WPR da quay ve vung doi dien -- CAN NHAC CHOT LOI")
        if pos["direction"] == "Long" and current_price <= pos["sl_price"]:
            suggestions.append("!!! GIA DA CHAM/VUOT SL -- NEN DONG NGAY !!!")
        if pos["direction"] == "Short" and current_price >= pos["sl_price"]:
            suggestions.append("!!! GIA DA CHAM/VUOT SL -- NEN DONG NGAY !!!")
        entry_dt = pd.Timestamp(pos["entry_date"])
        now_ts = pd.Timestamp(now_utc)
        if entry_dt.tzinfo is not None and now_ts.tzinfo is None:
            now_ts = now_ts.tz_localize("UTC")
        elif entry_dt.tzinfo is None and now_ts.tzinfo is not None:
            entry_dt = entry_dt.tz_localize("UTC")
        hours_held = (now_ts - entry_dt).total_seconds() / 3600
        max_hold = 96
        if hours_held >= max_hold:
            suggestions.append(f"Da giu {hours_held:.0f}h, vuot 96h toi da -- NEN DONG (het gio)")

        results.append({
            "leg_id": pos.get("leg_id", f"{pos['pair']}_{pos['direction']}"),
            "pair": pos["pair"], "direction": pos["direction"],
            "entry_price": pos["entry_price"], "current_price": current_price,
            "floating_pct_von": floating_acc, "wpr_now": wpr_now,
            "hours_held": hours_held, "suggestions": suggestions,
        })

    # ---- In bao cao tung lenh ----
    print(f"{'Leg':<22s} {'Vao':>10s} {'HienTai':>10s} {'Floating':>10s} {'WPR':>8s} {'GioGiu':>8s}")
    for r in results:
        print(f"{r['leg_id']:<22s} {r['entry_price']:>10.4f} {r['current_price']:>10.4f} "
              f"{r['floating_pct_von']:>9.3f}% {r['wpr_now']:>8.1f} {r['hours_held']:>7.0f}h")
        for s in r["suggestions"]:
            print(f"      -> {s}")

    print(f"\n{'='*60}")
    print(f"TONG FLOATING LOSS/LAI TOAN DANH MUC: {total_floating:.3f}% von")

    # ---- Ngat mach ----
    now_ts_utc = pd.Timestamp(now_utc)
    if now_ts_utc.tzinfo is None:
        now_ts_utc = now_ts_utc.tz_localize("UTC")
    was_paused = breaker_state.get("pause_until") is not None and \
        pd.Timestamp(breaker_state["pause_until"]) >= now_ts_utc

    if total_floating < CIRCUIT_BREAKER_TRIGGER:
        new_pause = now_ts_utc + timedelta(days=CIRCUIT_BREAKER_PAUSE_DAYS)
        old = breaker_state.get("pause_until")
        if old is None or new_pause > pd.Timestamp(old):
            breaker_state["pause_until"] = new_pause.isoformat()
        breaker_state["history"].append({"date": now_utc.isoformat(), "floating": total_floating})
        print(f"\n!!! NGAT MACH KICH HOAT !!! Floating {total_floating:.2f}% < {CIRCUIT_BREAKER_TRIGGER}%")
        print(f"    KHUYEN NGHI: KHONG vao lenh moi den het {breaker_state['pause_until'][:10]}")
    elif was_paused:
        print(f"\n[Dang trong thoi gian khoa tu truoc] KHUYEN NGHI: KHONG vao lenh moi den het "
              f"{breaker_state['pause_until'][:10]}")
    else:
        print(f"\nKhong bi khoa -- co the vao lenh moi binh thuong neu co tin hieu tren TradingView.")
    print(f"{'='*60}\n")

    save_breaker_state(breaker_state)


if __name__ == "__main__":
    main()
