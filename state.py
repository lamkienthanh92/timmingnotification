"""
================================================================================
QUAN LY TRANG THAI: luu lai cac lenh DANG MO giua cac lan chay script
================================================================================
Vi script chay theo lich (cron / GitHub Actions), khong phai 1 tien trinh song
lien tuc, nen PHAI luu trang thai ra file (JSON) sau moi lan chay, va doc lai
o lan chay ke tiep. Neu ban chuyen sang dung database that (SQLite/Postgres),
chi can thay 2 ham load_state/save_state ben duoi, phan con lai giu nguyen.
================================================================================
"""
import json
import os
from datetime import datetime, timezone
from config import STATE_FILE


def _default_state():
    return {
        "open_positions": [],     # list cac lenh dang mo
        "closed_positions": [],   # lich su lenh da dong (de tinh floating/thong ke)
        "pause_until": None,      # ISO string hoac None -- ngay het khoa ngat mach
        "last_run": None,
    }


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return _default_state()
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def add_position(state: dict, leg_id: str, pair: str, direction: str,
                  entry_time: str, entry_price: float, sl_price: float,
                  sl_pct: float, risk_pct: float, timeframe: str):
    """Them 1 lenh MOI vao danh sach dang mo."""
    state["open_positions"].append({
        "leg_id": leg_id, "pair": pair, "direction": direction,
        "entry_time": entry_time, "entry_price": entry_price,
        "sl_price": sl_price, "sl_pct": sl_pct, "risk_pct": risk_pct,
        "timeframe": timeframe,
    })


def close_position(state: dict, position: dict, exit_time: str, exit_price: float, reason: str):
    """Chuyen 1 lenh tu open_positions sang closed_positions."""
    sign = 1 if position["direction"] == "Long" else -1
    pnl_pct = sign * (exit_price - position["entry_price"]) / position["entry_price"] * 100
    size_mult = position["risk_pct"] / position["sl_pct"]
    ret = size_mult * pnl_pct / 100
    closed = dict(position)
    closed.update({"exit_time": exit_time, "exit_price": exit_price,
                    "reason": reason, "pnl_pct": pnl_pct, "ret": ret})
    state["closed_positions"].append(closed)
    state["open_positions"] = [p for p in state["open_positions"] if p is not position]
    return closed
