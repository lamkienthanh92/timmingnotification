"""
================================================================================
FILE CHAY CHINH -- goi 1 LAN MOI GIO (cron: "0 * * * *")
================================================================================
Quy trinh moi lan chay:
  1. Tai gia H1 cho 24 cap tang 1 + gia H4 cho ~30 cap tang 2/3 (co cache trong RAM).
  2. Tinh floating loss hien tai cua CAC LENH DANG MO -> kiem tra ngat mach.
  3. Kiem tra THOAT LENH cho tat ca lenh dang mo (SL / WPR / het gio).
  4. Neu KHONG bi khoa: kiem tra VAO LENH MOI cho ca 3 tang (tang 2/3 chi thuc
     su kich hoat dung gio/ngay quy dinh, ham se tu bo qua neu chua dung luc).
  5. Luu trang thai, ghi log.

CHAY THU (khong can cho du du lieu that):
    python main.py --dry-run

CHAY THAT (can TWELVE_DATA_API_KEY):
    export TWELVE_DATA_API_KEY=xxxxx
    python main.py
================================================================================
"""
import argparse
import sys
from datetime import datetime, timezone
import pandas as pd

from config import TANG1_H1, TANG2_H4_DOW, TANG3_H4_DOM, LOG_FILE
from twelvedata_client import fetch_time_series, TwelveDataError
from indicators import add_indicators
from state import load_state, save_state
from strategy import (check_tang1_entries, check_tang2_entries,
                       check_tang3_entries, check_exits)
from circuit_breaker import compute_floating_loss, is_paused, check_and_trigger


def build_price_cache(pairs_h1, pairs_h4, dry_run=False):
    """Tai gia cho tat ca cap can dung, tra ve 2 dict {pair: DataFrame co indicator}."""
    cache_h1, cache_h4 = {}, {}
    if dry_run:
        print("[DRY RUN] Bo qua goi API that, tra ve cache rong.")
        return cache_h1, cache_h4

    for pair in pairs_h1:
        try:
            df = fetch_time_series(pair, "1h", outputsize=60)
            cache_h1[pair] = add_indicators(df)
        except TwelveDataError as e:
            print(f"  [Loi] {pair} (1h): {e}")

    for pair in pairs_h4:
        try:
            df = fetch_time_series(pair, "4h", outputsize=40)
            cache_h4[pair] = add_indicators(df)
        except TwelveDataError as e:
            print(f"  [Loi] {pair} (4h): {e}")

    return cache_h1, cache_h4


def log_event(msg: str):
    print(msg)
    import os
    os.makedirs("data", exist_ok=True)
    with open(LOG_FILE.replace(".csv", ".txt"), "a") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()}  {msg}\n")


def main(dry_run=False):
    now_utc = datetime.now(timezone.utc)
    print(f"=== Chay luc {now_utc.isoformat()} ===")

    state = load_state()

    pairs_h1 = sorted(set(p for p, *_ in TANG1_H1))
    pairs_h4 = sorted(set(p for p, *_ in TANG2_H4_DOW) | set(p for p, *_ in TANG3_H4_DOM))

    cache_h1, cache_h4 = build_price_cache(pairs_h1, pairs_h4, dry_run=dry_run)

    # ---- 2. Ngat mach: tinh floating loss & kiem tra ----
    floating = compute_floating_loss(state, cache_h1, cache_h4)
    was_paused = is_paused(state, now_utc)
    just_triggered = check_and_trigger(state, floating, now_utc)
    if just_triggered:
        log_event(f"[NGAT MACH] Floating={floating:.2f}% < -4% -> KHOA lenh moi "
                   f"den {state['pause_until']}")
    paused_now = is_paused(state, now_utc)
    print(f"Floating loss hien tai: {floating:.2f}%  |  Dang khoa: {paused_now}")

    # ---- 3. Kiem tra thoat lenh (LUON LUON, ke ca khi dang khoa) ----
    closed = check_exits(state, cache_h1, cache_h4, now_utc)
    for c in closed:
        log_event(f"[THOAT] {c['leg_id']}: {c['reason']}, pnl={c['pnl_pct']:.3f}%, "
                   f"ret={c['ret']*100:.4f}%")

    # ---- 4. Kiem tra vao lenh moi (chi neu KHONG bi khoa) ----
    new_h1 = check_tang1_entries(state, cache_h1, now_utc, paused_now)
    new_h2 = check_tang2_entries(state, cache_h4, now_utc, paused_now)
    new_h3 = check_tang3_entries(state, cache_h4, now_utc, paused_now)
    for leg_id in new_h1 + new_h2 + new_h3:
        pos = state["open_positions"][-1]
        log_event(f"[VAO LENH] {leg_id}: gia={pos['entry_price']:.5f}, "
                   f"SL={pos['sl_price']:.5f}")

    # ---- 5. Luu trang thai ----
    save_state(state)
    print(f"So lenh dang mo: {len(state['open_positions'])}")
    print(f"So lenh da dong (luy ke): {len(state['closed_positions'])}")
    print("=== Xong ===\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Chay thu khong goi API that (kiem tra logic/luong chay)")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
