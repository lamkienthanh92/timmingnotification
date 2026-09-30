"""
================================================================================
SIMULATE_FULL_SYSTEM.PY -- mo phong DAY DU 40 leg goc (60 leg bao gom BTC/cac
cap ban khong trade), chay 1 LAN MOI NGAY, lam NGUON TIN HIEU NGAT MACH CHINH
THUC -- TACH BIET HOAN TOAN voi 10 lenh ban tu vao tay (daily_check.py).

Y TUONG COT LOI: du chi goi API 1 LAN/NGAY, van tai du du lieu LICH SU trong
ngay (outputsize du lon) de TAI TAO CHINH XAC moi tin hieu H1 da xay ra o TUNG
GIO rieng cua 24 leg tang 1 -- khong can chay hourly moi bat duoc chung, vi
gia tai moi gio TRONG NGAY DA QUA da co san trong du lieu tra ve.

Ket qua quan trong nhat: TONG FLOATING LOSS cua toan bo mo phong 40 leg. Neu
< -4%, HE THONG KHUYEN NGHI: du 10 lenh cua ban dang lai bao nhieu, van nen
NGUNG vao lenh moi 45 ngay -- vi day la tin hieu "suc khoe thi truong chung",
khong phai P&L rieng cua ban.

Chay:
    python simulate_full_system.py
================================================================================
"""
import json
import os
from datetime import datetime, timezone, timedelta
import pandas as pd
import numpy as np

from config import (TANG1_H1, TANG2_H4_DOW, TANG3_H4_DOM, RISK,
                     CIRCUIT_BREAKER_TRIGGER, CIRCUIT_BREAKER_PAUSE_DAYS,
                     VN_OFFSET_HOURS)
from twelvedata_client import fetch_time_series, TwelveDataError, DailyQuotaExhausted
from indicators import add_indicators

SIM_STATE_FILE = "data/simulation_state.json"
# outputsize du lon de bao phu vai ngay gan day (phong khi script bi gian doan
# vai hom khong chay, van "bat kip" duoc tin hieu da bo lo)
H1_OUTPUTSIZE = 200   # ~8 ngay
H4_OUTPUTSIZE = 60    # ~10 ngay


def load_sim_state():
    if not os.path.exists(SIM_STATE_FILE):
        return {"open_positions": [], "pause_until": None, "last_processed_date": None,
                "floating_history": []}
    with open(SIM_STATE_FILE, "r") as f:
        return json.load(f)


def save_sim_state(state):
    os.makedirs("data", exist_ok=True)
    with open(SIM_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def fetch_all_data():
    """Tai H1 (24 cap) + H4 (~20 cap). Voi pacing 7.8s/request (8 credit/phut,
    dung theo xac nhan tu fx-cmt-app-main), tong thoi gian du kien:
    ~44 request x 7.8s =~ 5.7 PHUT -- BINH THUONG, khong phai loi. GitHub
    Actions khong gioi han thoi gian nay (job co the chay toi 6 tieng)."""
    pairs_h1 = sorted(set(p for p, *_ in TANG1_H1))
    pairs_h4 = sorted(set(p for p, *_ in TANG2_H4_DOW) | set(p for p, *_ in TANG3_H4_DOM))
    cache_h1, cache_h4 = {}, {}
    total = len(pairs_h1) + len(pairs_h4)
    print(f"Dang tai du lieu: {len(pairs_h1)} cap H1, {len(pairs_h4)} cap H4 "
          f"({total} request, du kien ~{total * 7.8 / 60:.1f} phut voi pacing 8 credit/phut)...")

    done = 0
    for pair in pairs_h1:
        try:
            df = fetch_time_series(pair, "1h", outputsize=H1_OUTPUTSIZE)
            cache_h1[pair] = add_indicators(df)
            done += 1
            print(f"  [{done}/{total}] OK {pair} (1h), {len(df)} nen")
        except DailyQuotaExhausted as e:
            # DUNG CA HAM NGAY -- moi cap con lai deu se loi giong het (cung
            # API key, cung han muc ngay), retry mu quang chi ton thoi gian.
            print(f"  [DUNG SOM] {e}")
            print(f"  Da tai duoc {len(cache_h1)}/{len(pairs_h1)} cap H1, "
                  f"{len(cache_h4)}/{len(pairs_h4)} cap H4 truoc khi het han muc.")
            return cache_h1, cache_h4
        except TwelveDataError as e:
            print(f"  [Loi] {pair} (1h): {e}")

    for pair in pairs_h4:
        try:
            df = fetch_time_series(pair, "4h", outputsize=H4_OUTPUTSIZE)
            cache_h4[pair] = add_indicators(df)
            done += 1
            print(f"  [{done}/{total}] OK {pair} (4h), {len(df)} nen")
        except DailyQuotaExhausted as e:
            print(f"  [DUNG SOM] {e}")
            print(f"  Da tai duoc {len(cache_h1)}/{len(pairs_h1)} cap H1, "
                  f"{len(cache_h4)}/{len(pairs_h4)} cap H4 truoc khi het han muc.")
            return cache_h1, cache_h4
        except TwelveDataError as e:
            print(f"  [Loi] {pair} (4h): {e}")

    return cache_h1, cache_h4


def scan_h1_signals_for_date(df, target_date, window, entry_hour, thresh, direction, excl_dow):
    """Kiem tra 1 leg H1 CO tin hieu vao lenh vao dung target_date hay khong,
    dung DUNG logic cua so/nguong nhu ban backtest."""
    if excl_dow is not None and target_date.weekday() == excl_dow:
        return None
    ws, we = window
    day_mask = df["Date_VN"] == target_date
    win = df[(df["Hour_VN"] >= ws) & (df["Hour_VN"] < we) & day_mask]
    if len(win) == 0:
        return None
    sig = win["wpr"].min() if direction == "Long" else win["wpr"].max()
    cond = sig < thresh if direction == "Long" else sig > thresh
    if not cond:
        return None
    entry_row = df[(df["Hour_VN"] == entry_hour) & day_mask]
    if len(entry_row) == 0:
        return None
    row = entry_row.iloc[-1]
    if pd.isna(row["atr"]):
        return None
    return row


def run_simulation():
    now_utc = datetime.now(timezone.utc)
    now_vn = now_utc + timedelta(hours=VN_OFFSET_HOURS)
    today_vn = now_vn.date()

    state = load_sim_state()
    cache_h1, cache_h4 = fetch_all_data()

    # Xac dinh CAC NGAY can xu ly (tu lan chay truoc +1, den hom nay) -- de
    # "bat kip" neu bi gian doan vai hom.
    if state["last_processed_date"] is None:
        dates_to_process = [today_vn]
    else:
        last = pd.Timestamp(state["last_processed_date"]).date()
        n_days = (today_vn - last).days
        dates_to_process = [last + timedelta(days=i + 1) for i in range(max(n_days, 0))]
        if not dates_to_process:
            dates_to_process = [today_vn]

    for process_date in dates_to_process:
        is_paused = (state["pause_until"] is not None and
                     pd.Timestamp(process_date) <= pd.Timestamp(state["pause_until"]).normalize())

        # ---- kiem tra vao lenh moi (chi neu KHONG bi khoa dung ngay do) ----
        if not is_paused:
            for pair, direction, window, entry_hour, thresh, excl_dow, atr_mult in TANG1_H1:
                if pair not in cache_h1:
                    continue
                leg_id = f"H1_{pair}_{direction}"
                already = any(p["leg_id"] == leg_id and p["entry_date"] == str(process_date)
                               for p in state["open_positions"])
                if already:
                    continue
                row = scan_h1_signals_for_date(cache_h1[pair], process_date, window,
                                                entry_hour, thresh, direction, excl_dow)
                if row is None:
                    continue
                sign = 1 if direction == "Long" else -1
                sl_dist = row["atr"] * atr_mult
                sl_price = row["Close"] - sign * sl_dist
                sl_pct = sl_dist / row["Close"] * 100
                state["open_positions"].append({
                    "leg_id": leg_id, "pair": pair, "direction": direction,
                    "entry_date": str(process_date), "entry_time": str(row["Time"]),
                    "entry_price": float(row["Close"]), "sl_price": float(sl_price),
                    "sl_pct": float(sl_pct), "risk_pct": RISK["H1"], "tier": "H1",
                })

            dow_p = process_date.weekday(); dom_p = process_date.day
            for pair, direction, dow, thresh, atr_mult in TANG2_H4_DOW:
                if dow != dow_p or pair not in cache_h4:
                    continue
                leg_id = f"H4DOW_{pair}_{direction}"
                already = any(p["leg_id"] == leg_id and p["entry_date"] == str(process_date)
                               for p in state["open_positions"])
                if already:
                    continue
                df = cache_h4[pair]
                day_rows = df[df["Date_VN"] == process_date]
                if len(day_rows) == 0:
                    continue
                sig = day_rows["wpr"].min() if direction == "Long" else day_rows["wpr"].max()
                cond = sig < thresh if direction == "Long" else sig > thresh
                if not cond:
                    continue
                row = day_rows.iloc[-1]
                if pd.isna(row["atr"]):
                    continue
                sign = 1 if direction == "Long" else -1
                sl_dist = row["atr"] * atr_mult
                sl_price = row["Close"] - sign * sl_dist
                sl_pct = sl_dist / row["Close"] * 100
                state["open_positions"].append({
                    "leg_id": leg_id, "pair": pair, "direction": direction,
                    "entry_date": str(process_date), "entry_time": str(row["Time"]),
                    "entry_price": float(row["Close"]), "sl_price": float(sl_price),
                    "sl_pct": float(sl_pct), "risk_pct": RISK["H4DOW"], "tier": "H4",
                })

            for pair, direction, dom, thresh, atr_mult in TANG3_H4_DOM:
                if dom != dom_p or pair not in cache_h4:
                    continue
                leg_id = f"H4DOM_{pair}_{direction}"
                already = any(p["leg_id"] == leg_id and p["entry_date"] == str(process_date)
                               for p in state["open_positions"])
                if already:
                    continue
                df = cache_h4[pair]
                day_rows = df[df["Date_VN"] == process_date]
                if len(day_rows) == 0:
                    continue
                sig = day_rows["wpr"].min() if direction == "Long" else day_rows["wpr"].max()
                cond = sig < thresh if direction == "Long" else sig > thresh
                if not cond:
                    continue
                row = day_rows.iloc[-1]
                if pd.isna(row["atr"]):
                    continue
                sign = 1 if direction == "Long" else -1
                sl_dist = row["atr"] * atr_mult
                sl_price = row["Close"] - sign * sl_dist
                sl_pct = sl_dist / row["Close"] * 100
                state["open_positions"].append({
                    "leg_id": leg_id, "pair": pair, "direction": direction,
                    "entry_date": str(process_date), "entry_time": str(row["Time"]),
                    "entry_price": float(row["Close"]), "sl_price": float(sl_price),
                    "sl_pct": float(sl_pct), "risk_pct": RISK["H4DOM"], "tier": "H4",
                })

    # ---- kiem tra thoat lenh cho TAT CA lenh dang mo (dung du lieu MOI NHAT) ----
    still_open = []
    closed_today = []
    for pos in state["open_positions"]:
        df = cache_h1.get(pos["pair"]) if pos["tier"] == "H1" else cache_h4.get(pos["pair"])
        if df is None or len(df) == 0:
            still_open.append(pos); continue
        last = df.iloc[-1]
        direction = pos["direction"]
        opp = -20 if direction == "Long" else -80
        sign = 1 if direction == "Long" else -1
        exit_price = None; reason = None
        if direction == "Long" and last["Low"] <= pos["sl_price"]:
            exit_price = min(last["Open"], pos["sl_price"]); reason = "SL"
        elif direction == "Short" and last["High"] >= pos["sl_price"]:
            exit_price = max(last["Open"], pos["sl_price"]); reason = "SL"
        elif direction == "Long" and last["wpr"] > opp:
            exit_price = last["Close"]; reason = "WPR"
        elif direction == "Short" and last["wpr"] < opp:
            exit_price = last["Close"]; reason = "WPR"
        else:
            entry_dt = pd.Timestamp(pos["entry_time"])
            hrs = (pd.Timestamp(last["Time"]) - entry_dt).total_seconds() / 3600
            if hrs >= 96:
                exit_price = last["Close"]; reason = "MAX_HOLD"
        if exit_price is not None:
            closed_today.append({**pos, "exit_price": float(exit_price), "reason": reason})
        else:
            still_open.append(pos)
    state["open_positions"] = still_open

    # ---- tinh floating loss cua CAC LENH CON MO (ca tong VA rieng tung lenh
    #      de dashboard React hien thi duoc) ----
    total_floating = 0.0
    for pos in state["open_positions"]:
        df = cache_h1.get(pos["pair"]) if pos["tier"] == "H1" else cache_h4.get(pos["pair"])
        if df is None or len(df) == 0:
            pos["current_floating_pct"] = 0.0
            continue
        current_price = df.iloc[-1]["Close"]
        sign = 1 if pos["direction"] == "Long" else -1
        size_mult = pos["risk_pct"] / pos["sl_pct"]
        floating_pct = sign * (current_price - pos["entry_price"]) / pos["entry_price"] * 100
        pos_floating = size_mult * floating_pct
        pos["current_floating_pct"] = round(float(pos_floating), 4)
        pos["current_price"] = round(float(current_price), 5)
        total_floating += pos_floating

    # ---- ngat mach ----
    just_triggered = False
    if total_floating < CIRCUIT_BREAKER_TRIGGER:
        new_pause = pd.Timestamp(now_utc) + timedelta(days=CIRCUIT_BREAKER_PAUSE_DAYS)
        old = state.get("pause_until")
        if old is None or new_pause > pd.Timestamp(old):
            state["pause_until"] = new_pause.isoformat()
            just_triggered = True

    state["last_processed_date"] = str(today_vn)
    state["total_floating_pct"] = round(float(total_floating), 4)
    state["generated_at"] = now_utc.isoformat()
    state["floating_history"].append({"date": str(today_vn), "floating": round(total_floating, 4)})
    state["floating_history"] = state["floating_history"][-90:]  # chi giu 90 ngay gan nhat

    # ---- BAO CAO ----
    print(f"\n{'='*60}")
    print(f"MO PHONG DAY DU 40 LEG -- ngay {today_vn}")
    print(f"So lenh dang mo (mo phong): {len(state['open_positions'])}")
    if closed_today:
        print(f"Lenh vua dong trong lan chay nay:")
        for c in closed_today:
            print(f"  {c['leg_id']}: {c['reason']}, gia thoat={c['exit_price']:.5f}")
    print(f"\n>>> TONG FLOATING LOSS MO PHONG: {total_floating:.3f}% <<<")
    if just_triggered:
        print(f"!!! NGAT MACH VUA KICH HOAT !!! -> KHUYEN NGHI KHONG vao lenh moi "
              f"(ke ca 10 lenh ban tu trade) den het {state['pause_until'][:10]}")
    elif state["pause_until"] and pd.Timestamp(state["pause_until"]) >= pd.Timestamp(now_utc):
        print(f"[Van dang trong thoi gian khoa] den het {state['pause_until'][:10]}")
    else:
        print("Khong bi khoa -- an toan de tiep tuc vao lenh binh thuong.")
    print(f"{'='*60}\n")

    save_sim_state(state)
    return total_floating, state["pause_until"]


if __name__ == "__main__":
    run_simulation()
