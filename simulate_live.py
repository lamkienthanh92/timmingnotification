"""
Mo phong bot chay MOI GIO tren du lieu lich su (CSV H1 xuat tu MT5), thay Twelve Data bang nguon gia lap.
Dung de kiem chung: tin nhan bot co khop voi lenh backtest khong, va xem truoc tin nhan Telegram.

    python simulate_live.py --data ./mt5_csv --start "2026-09-14 00:02" --end "2026-10-02 14:02"

Ket qua: in tin nhan theo thoi gian, so lan goi API, va bang doi chieu voi backtest (cung engine, du lieu day du).
Khong gui Telegram, khong dung API that. Dung thu muc tam rieng (khong dung data/ that).
"""
import argparse
import os
import re
import sys
import tempfile
import time

import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True, help="thu muc CSV H1 MT5 (25 cap forex + BTCUSD, ETHUSD)")
ap.add_argument("--start", required=True, help="thoi diem chay dau tien (UTC), vd '2026-09-14 00:02'")
ap.add_argument("--end", required=True, help="thoi diem chay cuoi (UTC)")
ap.add_argument("--quiet", action="store_true", help="khong in noi dung tin nhan")
args = ap.parse_args()

tmp = tempfile.mkdtemp(prefix="sim_bot_")
os.environ["CACHE_DIR"] = os.path.join(tmp, "cache")
os.environ["LIVE_STATE_FILE"] = os.path.join(tmp, "live_state.json")

import portfolio_backtest as eng  # noqa: E402
import live_bot  # noqa: E402

FULL = {s: df[["Time", "Open", "High", "Low", "Close"]] for s, df in eng.load_folder(args.data).items()}
CALLS = [0]
NOW = [None]


def fake_fetcher(sym, outputsize, end_date=None):
    """Giong Twelve Data: tra ve ca nen dang chay (chua dong) o cuoi, toi da outputsize nen."""
    CALLS[0] += 1
    df = FULL[sym]
    df = df[df.Time <= NOW[0].floor("h")]
    if end_date is not None:
        df = df[df.Time <= pd.Timestamp(end_date)]
    return df.tail(outputsize).reset_index(drop=True)


t, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
log, t0 = [], time.time()
while t <= end:
    NOW[0] = t
    c0 = CALLS[0]
    st, msgs = live_bot.run(now=t, fetcher=fake_fetcher, send=False)
    for m in msgs:
        log.append((t, m))
        if not args.quiet:
            print(f"\n===== {t:%a %d/%m %H:%M} UTC ({live_bot.fvn(t)} VN) =====\n" + live_bot._plain(m))
    print(f"[{t:%d/%m %H:%M}] goi API {CALLS[0] - c0:2d} | {','.join(st['last_fetch']['parts']) or '-':<12} "
          f"| mo {len(st['positions'])} | tin {len(msgs)}", file=sys.stderr)
    t += pd.Timedelta(hours=1)
print(f"\nTong: {len(log)} khoi tin, {CALLS[0]} lan goi API, {time.time() - t0:.0f}s", file=sys.stderr)

# ---- doi chieu voi backtest (cung engine, du lieu day du den thoi diem cuoi) ----
data = {s: df[df.Time + pd.Timedelta(hours=1) <= end].assign(spr_pct=live_bot.SPREAD_PCT.get(s, 0.02)).reset_index(drop=True)
        for s, df in FULL.items()}
res, _ = live_bot.engine(data, end, live_bot.PARTS)
start = pd.Timestamp(args.start)
txt = "\n".join(live_bot._plain(m) for _, m in log)
print("\nDOI CHIEU VOI BACKTEST (lenh co gio vao trong khoang mo phong):")
ok = miss = skip = 0
blocked = set(st.get("blocked_ids", []))
for part, snap in res.items():
    for c in snap["closed"] + snap["open"]:
        if pd.Timestamp(c["vao"]) < start + pd.Timedelta(hours=2):
            continue
        side = "LONG" if c["side"] == 1 else "SHORT"
        if c["id"] in blocked:
            skip += 1
            print(f"  BO QUA {c['he']:<8}{c['pair']:<8}{side:<6} vao {c['vao'][:16]}  (bi chan boi tran/ngat mach)"); continue
        found = re.search(rf"(VÀO|ĐANG MỞ|ĐÃ CHỐT) · {c['pair']} {side}", txt) is not None
        ok += found; miss += not found
        print(f"  {'OK ' if found else 'THIEU'} {c['he']:<8}{c['pair']:<8}{side:<6} vao {c['vao'][:16]}"
              + (f"  ra {c['ra'][:16]}  R {c['R']:+.2f}" if "ra" in c else "  (con mo)"))
print(f"Khop {ok}/{ok + miss} | bi chan boi tran/ngat mach: {skip}")
