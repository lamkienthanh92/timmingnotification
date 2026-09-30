"""
================================================================================
LOGIC CHIEN LUOC: kiem tra tin hieu VAO va THOAT cho ca 3 tang
================================================================================
Goi 1 LAN MOI GIO (kien nghi chay cron moi gio dung phut 0). Ham main() trong
main.py se tu quyet dinh tang nao can kiem tra dua vao gio hien tai.
================================================================================
"""
import pandas as pd
import numpy as np
from datetime import timedelta
from config import (TANG1_H1, TANG2_H4_DOW, TANG3_H4_DOM, RISK,
                     SPREAD_PCT_M15, SPREAD_PCT_H4, MAX_HOLD_H1, MAX_HOLD_H4,
                     VN_OFFSET_HOURS)
from indicators import add_indicators
from state import add_position, close_position


def _now_vn(now_utc):
    return now_utc + timedelta(hours=VN_OFFSET_HOURS)


def check_tang1_entries(state, price_cache_h1, now_utc, is_paused):
    """price_cache_h1: dict {pair: DataFrame co indicator, da fetch san}.
    Kiem tra dung leg nao co entry_hour == gio VN hien tai, va WPR trong cua so
    co vuot nguong khong."""
    if is_paused:
        return []
    now_vn = _now_vn(now_utc)
    current_hour = now_vn.hour
    new_entries = []

    for pair, direction, window, entry_hour, thresh, excl_dow, atr_mult in TANG1_H1:
        if entry_hour != current_hour:
            continue
        if pair not in price_cache_h1:
            continue
        df = price_cache_h1[pair]
        ws, we = window
        win = df[(df["Hour_VN"] >= ws) & (df["Hour_VN"] < we) & (df["Date_VN"] == now_vn.date())]
        if len(win) == 0:
            continue
        sig = win["wpr"].min() if direction == "Long" else win["wpr"].max()
        cond = sig < thresh if direction == "Long" else sig > thresh
        if not cond:
            continue
        if excl_dow is not None and now_vn.weekday() == excl_dow:
            continue  # bo qua dung theo thu da loai (T4=2 vd)

        last_row = df.iloc[-1]
        entry_price = last_row["Close"]
        atr_now = last_row["atr"]
        if pd.isna(atr_now):
            continue
        sign = 1 if direction == "Long" else -1
        sl_dist = atr_now * atr_mult
        sl_price = entry_price - sign * sl_dist
        sl_pct = sl_dist / entry_price * 100

        leg_id = f"H1_{pair}_{direction}"
        add_position(state, leg_id, pair, direction, now_utc.isoformat(),
                     entry_price, sl_price, sl_pct, RISK["H1"], "H1")
        new_entries.append(leg_id)
    return new_entries


def check_tang2_entries(state, price_cache_h4, now_utc, is_paused):
    if is_paused:
        return []
    now_vn = _now_vn(now_utc)
    current_dow = now_vn.weekday()
    today_str = now_vn.date().isoformat()
    new_entries = []

    for pair, direction, dow, thresh, atr_mult in TANG2_H4_DOW:
        if dow != current_dow:
            continue
        leg_id = f"H4DOW_{pair}_{direction}"
        # CHAN LAP LAI: bo qua neu leg nay DA vao lenh trong dung ngay hom nay roi
        # (can vi script chay MOI GIO, nhung nen H4 chi doi moi 4 tieng -- neu khong
        # chan, dieu kien dung se bi kich hoat nhieu lan trong cung 1 ngay).
        already_today = any(
            p["leg_id"] == leg_id and p["entry_time"][:10] == today_str
            for p in state["open_positions"] + state["closed_positions"]
        )
        if already_today:
            continue
        if pair not in price_cache_h4:
            continue
        df = price_cache_h4[pair]
        last_row = df.iloc[-1]
        wpr_now = last_row["wpr"]
        cond = wpr_now < thresh if direction == "Long" else wpr_now > thresh
        if not cond:
            continue
        entry_price = last_row["Close"]
        atr_now = last_row["atr"]
        if pd.isna(atr_now):
            continue
        sign = 1 if direction == "Long" else -1
        sl_dist = atr_now * atr_mult
        sl_price = entry_price - sign * sl_dist
        sl_pct = sl_dist / entry_price * 100

        add_position(state, leg_id, pair, direction, now_utc.isoformat(),
                     entry_price, sl_price, sl_pct, RISK["H4DOW"], "H4")
        new_entries.append(leg_id)
    return new_entries


def check_tang3_entries(state, price_cache_h4, now_utc, is_paused):
    if is_paused:
        return []
    now_vn = _now_vn(now_utc)
    current_dom = now_vn.day
    today_str = now_vn.date().isoformat()
    new_entries = []

    for pair, direction, dom, thresh, atr_mult in TANG3_H4_DOM:
        if dom != current_dom:
            continue
        leg_id = f"H4DOM_{pair}_{direction}"
        already_today = any(
            p["leg_id"] == leg_id and p["entry_time"][:10] == today_str
            for p in state["open_positions"] + state["closed_positions"]
        )
        if already_today:
            continue
        if pair not in price_cache_h4:
            continue
        df = price_cache_h4[pair]
        last_row = df.iloc[-1]
        wpr_now = last_row["wpr"]
        cond = wpr_now < thresh if direction == "Long" else wpr_now > thresh
        if not cond:
            continue
        entry_price = last_row["Close"]
        atr_now = last_row["atr"]
        if pd.isna(atr_now):
            continue
        sign = 1 if direction == "Long" else -1
        sl_dist = atr_now * atr_mult
        sl_price = entry_price - sign * sl_dist
        sl_pct = sl_dist / entry_price * 100

        add_position(state, leg_id, pair, direction, now_utc.isoformat(),
                     entry_price, sl_price, sl_pct, RISK["H4DOM"], "H4")
        new_entries.append(leg_id)
    return new_entries


def check_exits(state, price_cache_h1, price_cache_h4, now_utc):
    """Kiem tra TAT CA lenh dang mo: cham SL / WPR doi dien / het gio toi da."""
    closed = []
    for pos in list(state["open_positions"]):
        tf = pos["timeframe"]
        df = price_cache_h1.get(pos["pair"]) if tf == "H1" else price_cache_h4.get(pos["pair"])
        if df is None or len(df) == 0:
            continue
        last_row = df.iloc[-1]
        current_price = last_row["Close"]
        wpr_now = last_row["wpr"]
        direction = pos["direction"]
        opp_thresh = -20 if direction == "Long" else -80
        entry_time = pd.Timestamp(pos["entry_time"])
        max_hold = MAX_HOLD_H1 if tf == "H1" else MAX_HOLD_H4 * 4  # quy doi H4-bar sang gio

        exit_reason = None
        exit_price = None

        # 1. cham SL (kiem tra bang Low/High cua nen gan nhat, gap-aware don gian)
        if direction == "Long" and last_row["Low"] <= pos["sl_price"]:
            exit_price = min(last_row["Open"], pos["sl_price"]); exit_reason = "SL"
        elif direction == "Short" and last_row["High"] >= pos["sl_price"]:
            exit_price = max(last_row["Open"], pos["sl_price"]); exit_reason = "SL"
        # 2. WPR cham nguong doi dien
        elif direction == "Long" and wpr_now > opp_thresh:
            exit_price = current_price; exit_reason = "WPR"
        elif direction == "Short" and wpr_now < opp_thresh:
            exit_price = current_price; exit_reason = "WPR"
        # 3. het gio toi da
        elif (now_utc - entry_time.tz_localize(None) if entry_time.tz is None else now_utc - entry_time) \
                >= pd.Timedelta(hours=max_hold):
            exit_price = current_price; exit_reason = "MAX_HOLD"

        if exit_reason is not None:
            c = close_position(state, pos, now_utc.isoformat(), float(exit_price), exit_reason)
            closed.append(c)
    return closed
