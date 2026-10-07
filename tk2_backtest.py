"""
TK2_BACKTEST.PY - kiem chung chien luoc tai khoan 2 (TK2) tren backtest.

Buoc 1: chay engine de co danh sach lenh cua TK1:
    python portfolio_backtest.py --data ./data --out tk1_trades.csv
Buoc 2: chay file nay (cung thu muc voi portfolio_backtest.py va tk2_signal.py):
    python tk2_backtest.py --data ./data --trades tk1_trades.csv --trigger wpr

Cach tinh:
  - Duong von TK1 theo ngay = tong (von da chot + tha noi theo gia dong cua ngay) cua moi lenh, % von ban dau, cong don.
  - TK2: BAT/TAT theo tk2_signal.tk2_states (tin hieu cuoi ngay, ap dung tu hom sau).
    Khi BAT, TK2 sao chep cac lenh TK1 MO TRONG thoi gian BAT, cung khoi luong; khi CHOT HET, dong cac lenh do
    o gia dong cua ngay chot (tru phi --cost R tren moi lenh bi dong som).
  - So voi "bat tat ngau nhien": dich lich BAT/TAT sang thoi diem khac (giu nguyen do dai cac dot).
"""
import argparse
import numpy as np
import pandas as pd
import portfolio_backtest as eng
from tk2_signal import tk2_states


def build_paths(trades, data, start):
    """Moi lenh -> (chi so ngay, thay doi % von theo ngay, chi so ngay vao)."""
    days = pd.date_range(start, pd.to_datetime(trades.ra).max().normalize())
    dpos = pd.Series(np.arange(len(days)), days)
    closes = {p: data[p].set_index("Time").Close for p in trades.pair.unique()}
    paths = []
    for r in trades.itertuples():
        rk = eng.RISK[r.he]
        x = closes[r.pair].loc[r.vao:pd.Timestamp(r.ra) - pd.Timedelta(hours=1)]
        d0, dx = pd.Timestamp(r.vao).normalize(), pd.Timestamp(r.ra).normalize()
        if len(x):
            v = pd.Series(r.side * (x.values - r.gia_vao) / r.rui_ro * rk, x.index + pd.Timedelta(hours=1))
            v = v.groupby(v.index.normalize()).last()
            v = v[v.index < dx]
        else:
            v = pd.Series(dtype=float)
        inc = v.diff()
        if len(v):
            inc.iloc[0] = v.iloc[0]
        ii = list(dpos.reindex(inc.index).values) + [dpos.get(dx, np.nan)]
        vals = list(inc.values) + [r.R * rk - (v.iloc[-1] if len(v) else 0.0)]
        keep = [not np.isnan(i) for i in ii]
        paths.append((np.array([int(i) for i, k in zip(ii, keep) if k]), np.array([a for a, k in zip(vals, keep) if k]),
                      int(dpos.get(d0, -1)), rk))
    return days, paths


def segments_from_states(st):
    seg, on = [], False
    flags = (st.tk2_ngay_mai == "BAT").values
    for t in range(len(flags) - 1):
        if not on and flags[t]:
            on, s = True, t + 1
        elif on and not flags[t]:
            on = False; seg.append((s, t + 1))
    if on:
        seg.append((s, len(flags) - 1))
    return seg


def tk2_pnl(paths, n, seg, cost):
    out, sid = np.zeros(n), np.full(n, -1)
    for q, (s, e) in enumerate(seg):
        sid[s:e] = q
    for ii, vv, j0, rk in paths:
        if j0 < 0 or sid[j0] < 0:
            continue
        e = seg[sid[j0]][1]
        for i, v in zip(ii, vv):
            if i >= e:
                out[e] -= rk * cost; break
            out[i] += v
    return out


def stats(a, days, mid):
    d = pd.Series(a, days) / 100
    sh = lambda q: q.mean() / q.std() * np.sqrt(365) if q.std() > 0 else np.nan
    e = (1 + d).cumprod()
    return dict(Sharpe=sh(d), Sharpe_dau=sh(d[d.index < mid]), Sharpe_sau=sh(d[d.index >= mid]),
                lai_nam_pct=d.mean() * 365 * 100, MaxDD_pct=(e / e.cummax() - 1).min() * 100)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--trades", required=True, help="CSV lenh TK1 tu portfolio_backtest.py --out")
    ap.add_argument("--trigger", default="wpr", choices=["wpr", "band", "both"])
    ap.add_argument("--exit", default="bb50", choices=["bb50", "bb20", "wpr"])
    ap.add_argument("--trail", default="day5", choices=["day5", "std1", "none"])
    ap.add_argument("--start", default="2011-09-01")
    ap.add_argument("--split", default="2019-01-01", help="moc chia 2 giai doan")
    ap.add_argument("--cost", type=float, default=0.05, help="phi (R) moi lenh TK2 bi dong som")
    ap.add_argument("--random", type=int, default=150, help="so ban bat tat ngau nhien de doi chieu")
    a = ap.parse_args()

    data = eng.load_folder(a.data)
    T = pd.read_csv(a.trades, parse_dates=["vao", "ra"])
    T = T[(T.vao >= a.start) & T.pair.isin(list(data))].reset_index(drop=True)
    days, paths = build_paths(T, data, a.start)
    n, mid = len(days), pd.Timestamp(a.split)

    dE = np.zeros(n)
    for ii, vv, _, _ in paths:
        np.add.at(dE, ii, vv)
    eq1 = pd.Series(np.cumsum(dE), days)                               # duong von TK1 (% von, cong don)
    st = tk2_states(eq1, a.trigger, a.exit, a.trail)
    seg = segments_from_states(st)
    a2 = tk2_pnl(paths, n, seg, a.cost)

    s1, s2 = stats(dE, days, mid), stats(a2, days, mid)
    act = np.zeros(n, bool)
    for s, e in seg:
        act[s:e] = True
    print(f"TK1: Sharpe {s1['Sharpe']:.2f} | lai {s1['lai_nam_pct']:.1f}%/nam | MaxDD {s1['MaxDD_pct']:.1f}%")
    print(f"TK2 (bat {a.trigger}, len dan {a.exit}, trailing {a.trail}): {len(seg)} dot, bat {act.mean() * 100:.0f}% thoi gian | Sharpe {s2['Sharpe']:.2f} "
          f"(truoc {a.split[:4]}: {s2['Sharpe_dau']:.2f}, sau: {s2['Sharpe_sau']:.2f}) | lai {s2['lai_nam_pct']:.1f}%/nam | "
          f"MaxDD {s2['MaxDD_pct']:.1f}%")

    rng = np.random.default_rng(0); r1, r2 = [], []
    for _ in range(a.random):
        sft = int(rng.integers(200, n - 200))
        sg = sorted([((s + sft) % n, (e + sft) % n) for s, e in seg if (s + sft) % n < (e + sft) % n])
        x = stats(tk2_pnl(paths, n, sg, a.cost), days, mid)
        r1.append(x["Sharpe_dau"]); r2.append(x["Sharpe_sau"])
    print(f"Tot hon bat tat ngau nhien: giai doan dau {np.nanmean(np.array(r1) < s2['Sharpe_dau']) * 100:.0f}%, "
          f"giai doan sau {np.nanmean(np.array(r2) < s2['Sharpe_sau']) * 100:.0f}% so ban ngau nhien")
    yr = pd.Series(a2, days).groupby(days.year).sum()
    print("TK2 theo nam (% von):", {int(k): round(v, 1) for k, v in yr.items()})
    print("\n5 lan doi trang thai gan nhat:")
    for t, r in st[st.su_kien != ""].tail(5).iterrows():
        print(f"  {t:%d/%m/%Y}  {r.su_kien}")


if __name__ == "__main__":
    main()
