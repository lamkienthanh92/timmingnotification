"""
TK2_SIGNAL.PY - trang thai hai tai khoan tu duong von (Equity) cua TK1.

TK1: vao MOI tin hieu lien tuc. LEN DAN khi Equity TK1 >= band tren Bollinger(50, 2.5);
     sau do CHOT HET cac lenh TK1 dang mo khi Equity cuoi ngay < muc thap nhat 5 ngay truoc, roi vao lenh moi tiep ngay.
TK2: (quy tac ben duoi) bat/tat theo Equity TK1.

Quy tac (da kiem chung tren backtest 2011-2026):
  - BAT TK2 khi duong von TK1 (Equity = von da chot + tha noi) cho tin hieu giam sau:
      trigger="wpr"  : WPR(14) + EMA(5) cua duong von < -80       (mac dinh)
      trigger="band" : duong von <= band duoi Bollinger(20, 2)      (it dot hon, drawdown thap hon)
      trigger="both" : ca hai cung luc                              (khong tot hon - chi de doi chieu)
  - LEN DAN khi duong von TK1 >= band tren Bollinger(50, 2.5) (--exit bb20: band tren BB(20,2); --exit wpr: WPR-EMA > -20)
  - CHOT HET TK2 theo trailing sau khi len dan:
      --trail day5 (mac dinh): Equity < muc thap nhat cua 5 ngay truoc do
      --trail std1           : Equity < dinh (tu luc len dan) - 1 x do lech chuan thay doi Equity hang ngay (60 ngay)
      --trail none           : chot ngay luc len dan
    Backtest 2011-2026 (bat WPR<-80, len dan BB(50,2.5), trailing day5): Sharpe TK2 ~1.60, lai ~21%/nam, MaxDD ~-10.6%,
    co lai 16/16 nam, tot hon bat tat ngau nhien o ca 2 giai doan.
  - Trong luc BAT: TK2 sao chep MOI LENH MOI cua TK1 (cung SL, cung cach quan ly). Khong mo lai lenh cu.
  - Tin hieu tinh tren gia tri Equity CUOI NGAY; ap dung tu ngay hom sau.

Dau vao: file CSV co 2 cot: ngay, equity (vi du xuat tu MT5 hoac ghi tay moi sang).
  date,equity
  2026-09-01,10250.3
  2026-09-02,10198.7
  ...
Can it nhat ~55 ngay du lieu (Bollinger 50 ngay cho muc chot).

Chay:
  python tk2_signal.py --equity tk1_equity.csv
  python tk2_signal.py --equity tk1_equity.csv --trigger band --history 30
"""
import argparse
import numpy as np
import pandas as pd

WPR_N, EMA_N, BB_N, BB_K, WPR_OS = 14, 5, 20, 2.0, -80.0
EXIT_BB_N, EXIT_BB_K, WPR_OB = 50, 2.5, -20.0          # chot: band tren BB(50, 2.5)


def load_equity(path):
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in df.columns if c in ("date", "ngay", "time", "datetime"))
    ecol = next(c for c in df.columns if c in ("equity", "von", "balance_equity"))
    s = pd.Series(df[ecol].astype(float).values, pd.to_datetime(df[tcol])).sort_index()
    return s.groupby(s.index.normalize()).last()                     # 1 gia tri moi ngay (cuoi ngay)


def indicators(eq):
    out = pd.DataFrame({"equity": eq})
    hh, ll = eq.rolling(WPR_N).max(), eq.rolling(WPR_N).min()
    wpr = -100 * (hh - eq) / (hh - ll).replace(0, np.nan)
    out["wpr_ema"] = wpr.ewm(span=EMA_N, adjust=False).mean()
    mid, sd = eq.rolling(BB_N).mean(), eq.rolling(BB_N).std()
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = mid, mid + BB_K * sd, mid - BB_K * sd
    m2, s2 = eq.rolling(EXIT_BB_N).mean(), eq.rolling(EXIT_BB_N).std()
    out["exit_upper"] = m2 + EXIT_BB_K * s2
    return out


def tk2_states(eq, trigger="wpr", exit="bb50", trail="day5"):
    """Tra ve bang theo ngay: chi bao + trang thai TK2 ap dung cho NGAY HOM SAU + su kien."""
    d = indicators(eq)
    lo_band = d.equity <= d.bb_lower
    os_wpr = d.wpr_ema < WPR_OS
    trig = {"wpr": os_wpr, "band": lo_band, "both": lo_band & os_wpr}[trigger].fillna(False)
    hit_upper = {"bb50": d.equity >= d.exit_upper, "bb20": d.equity >= d.bb_upper,
                 "wpr": d.wpr_ema > WPR_OB}[exit].fillna(False)
    low5 = d.equity.rolling(5).min().shift(1)
    sd1 = d.equity.diff().rolling(60, min_periods=20).std()
    state, event, armed_col, on, armed, pk = [], [], [], False, False, np.nan
    for t in d.index:
        ev, v = "", d.equity[t]
        if not on:
            if trig[t]:
                on, armed, ev = True, False, "BAT TK2 (tu ngay mai sao chep lenh moi)"
        else:
            if not armed and hit_upper[t]:
                armed, pk = True, v
                ev = "LEN DAN (cham band tren) - chua chot, theo doi trailing" if trail != "none" else ""
            if armed:
                pk = max(pk, v)
                stop = (trail == "none") or (trail == "day5" and v < low5[t]) or (trail == "std1" and v < pk - sd1[t])
                if stop:
                    on, armed, ev = False, False, "CHOT HET TK2 (dong moi lenh TK2 dang mo)"
        state.append("BAT" if on else "TAT"); event.append(ev); armed_col.append("co" if armed else "")
    d["tk2_ngay_mai"], d["su_kien"], d["len_dan"] = state, event, armed_col
    # TK1: trailing tren chinh Equity cua no (luon vao lenh)
    up50 = d.exit_upper; ev1, arm1, a1 = [], [], False
    for t in d.index:
        e1, v = "", d.equity[t]
        if not a1 and v >= up50[t]:
            a1, e1 = True, "LEN DAN (cham band tren BB50) - tiep tuc vao lenh"
        elif a1 and v < low5[t]:
            a1, e1 = False, "CHOT HET cac lenh TK1 dang mo, vao lenh moi tiep"
        ev1.append(e1); arm1.append("co" if a1 else "")
    d["tk1_su_kien"], d["tk1_len_dan"] = ev1, arm1
    d["muc_trailing"] = low5 if trail == "day5" else np.nan
    return d


def main():
    ap = argparse.ArgumentParser(description="Tin hieu TK2 tu duong von TK1")
    ap.add_argument("--equity", required=True, help="CSV: date,equity")
    ap.add_argument("--trigger", default="wpr", choices=["wpr", "band", "both"])
    ap.add_argument("--exit", default="bb50", choices=["bb50", "bb20", "wpr"], help="muc len dan")
    ap.add_argument("--trail", default="day5", choices=["day5", "std1", "none"], help="trailing sau khi len dan")
    ap.add_argument("--history", type=int, default=15, help="so ngay gan nhat de in")
    a = ap.parse_args()
    eq = load_equity(a.equity)
    need = (EXIT_BB_N if a.exit == "bb50" else BB_N) + 5
    if len(eq) < need:
        raise SystemExit(f"Can it nhat {need} ngay du lieu equity (hien co {len(eq)}).")
    d = tk2_states(eq, a.trigger, a.exit, a.trail)
    last = d.iloc[-1]
    print(f"Ngay {d.index[-1]:%d/%m/%Y} | Equity {last.equity:,.2f} | WPR-EMA {last.wpr_ema:.1f} | "
          f"band duoi BB(20,2) {last.bb_lower:,.2f} | muc chot BB(50,2.5) {last.exit_upper:,.2f}")
    print(f"==> TK1: {'DA LEN DAN' if last.tk1_len_dan else 'binh thuong'}" + (f"  ({last.tk1_su_kien})" if last.tk1_su_kien else ""))
    if last.tk1_len_dan:
        print(f"    TK1 chot het neu Equity cuoi ngay < {d.equity.tail(5).min():,.2f} (thap nhat 5 ngay)")
    print(f"==> TK2 cho ngay mai: {last.tk2_ngay_mai}" + (f"  ({last.su_kien})" if last.su_kien else ""))
    if last.len_dan and a.trail == "day5":
        print(f"    Da len dan: CHOT HET neu Equity cuoi ngay < {last.equity if np.isnan(last.muc_trailing) else min(d.equity.tail(5)):,.2f} (thap nhat 5 ngay)")
    ev = d[(d.su_kien != "") | (d.tk1_su_kien != "")]
    if len(ev):
        print("\nCac lan doi trang thai gan nhat:")
        for t, r in ev.tail(8).iterrows():
            if r.tk1_su_kien:
                print(f"  {t:%d/%m/%Y}  TK1: {r.tk1_su_kien}")
            if r.su_kien:
                print(f"  {t:%d/%m/%Y}  TK2: {r.su_kien}")
    print(f"\n{a.history} ngay gan nhat:")
    show = d[["equity", "wpr_ema", "exit_upper", "tk1_len_dan", "len_dan", "tk2_ngay_mai"]].tail(a.history)
    show.columns = ["equity", "wpr_ema", "band_tren_BB50", "TK1_len_dan", "TK2_len_dan", "TK2_ngay_mai"]
    print(show.round(2).to_string())


if __name__ == "__main__":
    main()
