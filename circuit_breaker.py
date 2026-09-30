"""
================================================================================
NGAT MACH THEO FLOATING LOSS (da kiem chung: -4% / nghi 45 ngay)
================================================================================
"""
import pandas as pd
from datetime import timedelta
from config import CIRCUIT_BREAKER_TRIGGER, CIRCUIT_BREAKER_PAUSE_DAYS


def compute_floating_loss(state, price_cache_h1, price_cache_h4) -> float:
    """Tong floating loss (%) cua TAT CA lenh dang mo, dung GIA HIEN TAI (chua
    tru spread -- spread chi tru khi thuc su dong lenh, giong dung ban backtest)."""
    total = 0.0
    for pos in state["open_positions"]:
        tf = pos["timeframe"]
        df = price_cache_h1.get(pos["pair"]) if tf == "H1" else price_cache_h4.get(pos["pair"])
        if df is None or len(df) == 0:
            continue
        current_price = df.iloc[-1]["Close"]
        sign = 1 if pos["direction"] == "Long" else -1
        size_mult = pos["risk_pct"] / pos["sl_pct"]
        floating_pct = sign * (current_price - pos["entry_price"]) / pos["entry_price"] * 100
        total += size_mult * floating_pct
    return total


def is_paused(state, now_utc) -> bool:
    if state.get("pause_until") is None:
        return False
    pause_until = pd.Timestamp(state["pause_until"])
    now = pd.Timestamp(now_utc)
    if pause_until.tz is not None and now.tz is None:
        now = now.tz_localize(pause_until.tz)
    return now <= pause_until


def check_and_trigger(state, floating_loss: float, now_utc) -> bool:
    """Neu floating_loss < trigger, GIA HAN pause_until them CIRCUIT_BREAKER_PAUSE_DAYS
    ngay KE TU HOM NAY (tu dong gia han neu dang trong luc khoa va van xau -- day la
    CHU DICH, xem ghi chu trong final_trading_system.py). Tra ve True neu VUA kich hoat."""
    if floating_loss < CIRCUIT_BREAKER_TRIGGER:
        new_pause_until = pd.Timestamp(now_utc) + timedelta(days=CIRCUIT_BREAKER_PAUSE_DAYS)
        old = state.get("pause_until")
        if old is None or new_pause_until > pd.Timestamp(old):
            state["pause_until"] = new_pause_until.isoformat()
        return True
    return False
