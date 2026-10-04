"""
Backtest + tin hieu danh muc FX/crypto tren du lieu H1 xuat tu MT5 (phien ban 5).

THANH PHAN (mac dinh chay A B BB AQB D E; C la tuy chon). Phien ban 5: trong so W1, gioi han + ngat mach.
  A  - Mua sau ban thao, 18 cap khong JPY (+XAUUSD neu co). Ngay giao dich dau tuan, neu WPR(14)+EMA(5) H1
       o nen dong cua cuoi tuan truoc < -80 va gia dong cua hom truoc < SMA200 ngay -> LONG o gia mo dau tuan,
       dong o gia dong cua ngay giao dich thu 8. Khong SL. 1R = 1 ATR(14) ngay.
  B  - Theo xu huong yen yeu, 7 cap JPY. Supertrend(10,3) 4H chuyen tang -> LONG o gia mo nen ke tiep,
       SL = duong Supertrend, keo len theo moi nen. Ghi nguyen nhan cu dao chieu (JPY tu yeu / XX manh / hon hop);
       --b-filter: chi vao lenh khi JPY tu yeu (phu thuoc che do chinh sach BoJ, xem chi bao theo doi trong bao cao).
  BB - Squeeze Bollinger crypto (BTCUSD, ETHUSD, SOLUSD) H1: squeeze = do rong band < phan vi 10% cua 4000 nen
       (trong 20 nen gan nhat); dong cua vuot band -> vao o gia mo nen ke tiep; SL = band doi dien keo theo;
       giu toi da 10 ngay; khong vao thu Bay/Chu nhat; loc xu huong 30 ngay +/-2%; toi da 5 lenh chong.
       Chi phi moi lenh = max(COST_CRYPTO, spread thuc te trong file luc vao); bo lenh neu chi phi > 25% rui ro.
  C  - (tuy chon, bao hiem cho B) CUSUM short JPY: CUSUM(h=4, k=0.5) tren loi nhuan 4H tung cap JPY bao giam
       -> SHORT o gia mo nen ke tiep, SL 3 ATR(4H) keo theo diem thap nhat. 1R = 3 ATR 4H.
  D  - Dao chieu suc manh dong tien, khung NGAY. Tach 25 cap thanh 8 nhan to dong tien (neo trung vi), z = vi tri
       chi so dong tien so voi mean/SD 120 ngay. Dong tu so z >= 2 VA dong mau so z <= -2 -> SHORT cap
       (nguoc lai -> LONG), vao o gia mo ngay hom sau. Thoat khi |z_tu - z_mau| < 1 hoac sau 60 ngay giao dich.
       Khong SL. Toi da 2 lenh moi dong tien, tong 4 lenh. 1R = 1 ATR(14) ngay.
  E  - Lop phu 4H -> 1H. Cung cong thuc D nhung tinh tren nhan to 4H (N = 120 nen 4H). Trong boi canh cuc doan,
       Supertrend(10,3) 1H dao chieu theo huong ve mean -> vao o gia mo nen ke tiep. SL = duong Supertrend 1H
       luc vao (co dinh), TP = mean (SMA120 log gia 4H). Chi vao khi RR = khoang cach TP / khoang cach SL
       nam trong [2, 4]. 1R = khoang cach SL.

  AQB - Band phan vi thich ung (BTC, ETH, SOL, DOGE: vuot q95; XAU: vuot q99) H1: trong luc nen (bien dong < phan vi 10%
       cua 90 ngay), loi suat 4 nen da chuan hoa vuot phan vi -> vao theo chieu pha o gia mo nen ke tiep; SL = band p1/p99
       keo theo; giu toi da 5 ngay; loc xu huong 30 ngay +/-2%; crypto khong vao thu Bay/CN.

Trong so W1 (RISK): A 0.25 / D 0.15 (% von moi ATR ngay, toi thieu 0.4% gia), B 0.35, E 0.10, vang 0.75, crypto 0.25.
Gioi han: A toi da 2 lenh/dong tien; D toi da 2/dong, tong 4; crypto (BB+AQB) toi da 6 lenh mo; tong rui ro mo <= 4%.
Ngat mach: lo thang phan FX (B,D,E) >= 1% hoac phan A >= 3% -> phan do dung den het thang; lo tha noi >= 3% -> dong het;
sut giam >= 20% -> dung toan bo. Bao cao in them dong "DANH MUC THUC THI" (da ap gioi han + ngat mach).
Mac dinh co tinh spread va swap (--no-swap de tat).

Du lieu: file CSV H1 tu MT5, ten bat dau bang ma 6 ky tu (EURUSD_H1.csv, BTCUSDm_H1.csv, EURUSD.r_H1.csv ...),
hoac file nen 1 gio cua Binance (SOLUSDT_1hour.csv, cot timestamp/open_time tinh bang ms; khong co spread).
Ho tro header "Time Open High Low Close Volume Spread" va "<DATE> <TIME> <OPEN> ... <SPREAD>". Gio phai la UTC.
D va E can it nhat 12 cap forex de tach nhan to dong tien (khuyen nghi du 25-28 cap).

Cach chay:
    python portfolio_backtest.py --data ./data                       # backtest A B BB D E
    python portfolio_backtest.py --data ./data --parts A B C D E BB  # them C
    python portfolio_backtest.py --data ./data --b-filter            # B chi vao khi JPY tu yeu
    python portfolio_backtest.py --data ./data --signals             # lenh dang mo + tin hieu cho
    python portfolio_backtest.py --data ./data --parts D E --out de.csv
    python portfolio_backtest.py --load ab.csv de.csv --data ./data  # gop ket qua nhieu lan chay
    python portfolio_backtest.py --data ./data --start 2021-01-01    # bao cao tu 2021 (spread crypto da hep)
Can: pandas >= 2.0, numpy.
"""
import argparse
import glob
import os
import re

import numpy as np
import pandas as pd

# ------------------------------------------------------------------ tham so
# Trong so W1 (% von moi lenh; A, D: % von moi 1 ATR ngay, toi thieu 0.4% gia)
RISK = {"A": 0.25, "B": 0.35, "C": 0.10, "D": 0.15, "E": 0.10, "BB BTC": 0.25, "BB ETH": 0.25, "BB SOL": 0.25,
        "AQB BTC": 0.25, "AQB ETH": 0.25, "AQB SOL": 0.25, "AQB DOGE": 0.25, "AQB XAU": 0.75}
COST_CRYPTO = {"BTCUSD": 0.10, "ETHUSD": 0.25, "SOLUSD": 0.20, "DOGEUSD": 0.20}                 # % gia toi thieu moi lenh; dung spread file neu lon hon
CRYPTO = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD")
A_HOLD_DAYS = 8
FX = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
CUR = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]
SUPPORTED = {a + b for a in FX for b in FX if a != b} | {"XAUUSD"} | set(CRYPTO)
B_DRIVER_WIN = 24                       # so nen 4H (4 ngay) dung de xac dinh nguyen nhan cu dao chieu cua B
C_H, C_K = 4.0, 0.5                     # nguong va do nhay CUSUM cua C
D_N, D_T, D_EXIT, D_MAXAGE = 120, 2.0, 1.0, 60
D_MAX_PER_CCY, D_MAX_TOTAL = 2, 4
E_N, E_T, E_RR = 120, 2.0, (2.0, 4.0)
MIN_FX_PAIRS = 12
BB_MAX_COST_R = 0.25                    # BB, AQB bo lenh neu chi phi > 25% khoang rui ro (spread qua rong so voi SL)
ATR_FLOOR_PCT = 0.4                     # A, D: khoang tinh khoi luong = max(ATR ngay, 0.4% gia) -> chan ATR bi nen gia tao
A_MAX_PER_CCY = 2                       # A: toi da 2 lenh dang mo chung 1 dong tien (uu tien WPR qua ban sau nhat)
# AQB (band phan vi thich ung): (nen < phan vi %, vuot phan vi q, giu toi da ngay, loc xu huong 30 ngay)
AQB_PARAMS = {"BTCUSD": (10, 95, 5, True), "ETHUSD": (10, 95, 5, True), "SOLUSD": (10, 95, 5, True),
              "DOGEUSD": (10, 95, 5, True), "XAUUSD": (10, 99, 5, True)}
AQB_W, AQB_H = 2160, 4                  # cua so phan vi (nen H1, ~90 ngay crypto), do dai loi suat (4 nen)
# Gioi han cap danh muc + ngat mach (dung cho backtest danh muc va bot)
MAX_OPEN_RISK = 4.0                     # tong rui ro cac lenh dang mo <= 4% von; vuot -> bo tin hieu moi
CRYPTO_MAX_OPEN = 6                     # BB + AQB crypto: toi da 6 lenh mo cung luc
BREAK_SLEEVE_MONTH = {"A": 3.0, "FX": 1.0}   # lo trong thang cua phan (A; FX = B, D, E) >= x% -> phan do dung den het thang
BREAK_FLOAT = 3.0                       # lo tha noi toan danh muc >= 3% -> dong het, nghi den het ngay
BREAK_DD = 20.0                         # sut giam tu dinh >= 20% -> dung toan bo, danh gia lai

# Swap. Forex/vang: chenh lech lai suat dieu hanh (%/nam) tru phan san cat. Cap nhat CHG khi lai suat thay doi.
SWAP_MARKUP = 1.0          # %/nam san cat khoi swap, ap cho moi chieu
CRYPTO_SWAP = -20.0        # %/nam tren gia tri lenh crypto, ca Long lan Short (gia dinh; xem bang swap san)
ROLLOVER_HOUR = 21         # gio rollover (UTC) xap xi, 17:00 New York

CHG = {
 'USD': [('2010-01-01',.25),('2015-12-17',.5),('2016-12-15',.75),('2017-03-16',1),('2017-06-15',1.25),('2017-12-14',1.5),('2018-03-22',1.75),('2018-06-14',2),('2018-09-27',2.25),('2018-12-20',2.5),('2019-08-01',2.25),('2019-09-19',2),('2019-10-31',1.75),('2020-03-04',1.25),('2020-03-16',.25),('2022-03-17',.5),('2022-05-05',1),('2022-06-16',1.75),('2022-07-28',2.5),('2022-09-22',3.25),('2022-11-03',4),('2022-12-15',4.5),('2023-02-02',4.75),('2023-03-23',5),('2023-05-04',5.25),('2023-07-27',5.5),('2024-09-19',5),('2024-11-08',4.75),('2024-12-19',4.5),('2025-09-18',4.25),('2025-10-30',4),('2025-12-11',3.75)],
 'EUR': [('2010-01-01',.25),('2011-04-13',.5),('2011-07-13',.75),('2011-11-09',.5),('2011-12-14',.25),('2012-07-11',0),('2014-06-11',-.1),('2014-09-10',-.2),('2015-12-09',-.3),('2016-03-16',-.4),('2019-09-18',-.5),('2022-07-27',0),('2022-09-14',.75),('2022-11-02',1.5),('2022-12-21',2),('2023-02-08',2.5),('2023-03-22',3),('2023-05-10',3.25),('2023-06-21',3.5),('2023-08-02',3.75),('2023-09-20',4),('2024-06-12',3.75),('2024-09-18',3.5),('2024-10-23',3.25),('2024-12-18',3),('2025-02-05',2.75),('2025-03-12',2.5),('2025-04-23',2.25),('2025-06-11',2)],
 'GBP': [('2010-01-01',.5),('2016-08-04',.25),('2017-11-02',.5),('2018-08-02',.75),('2020-03-11',.25),('2020-03-19',.1),('2021-12-16',.25),('2022-02-03',.5),('2022-03-17',.75),('2022-05-05',1),('2022-06-16',1.25),('2022-08-04',1.75),('2022-09-22',2.25),('2022-11-03',3),('2022-12-15',3.5),('2023-02-02',4),('2023-03-23',4.25),('2023-05-11',4.5),('2023-06-22',5),('2023-08-03',5.25),('2024-08-01',5),('2024-11-07',4.75),('2025-02-06',4.5),('2025-05-08',4.25),('2025-08-07',4),('2025-12-18',3.75)],
 'JPY': [('2010-01-01',.1),('2016-02-16',-.1),('2024-03-19',.1),('2024-07-31',.25),('2025-01-24',.5),('2025-12-19',.75),('2026-04-28',1.0)],
 'CHF': [('2010-01-01',.25),('2011-08-03',0),('2014-12-18',-.25),('2015-01-15',-.75),('2022-06-16',-.25),('2022-09-22',.5),('2022-12-15',1),('2023-03-23',1.5),('2023-06-22',1.75),('2024-03-21',1.5),('2024-06-20',1.25),('2024-09-26',1),('2024-12-12',.5),('2025-03-20',.25),('2025-06-19',0)],
 'CAD': [('2010-01-01',.25),('2010-06-01',.5),('2010-07-20',.75),('2010-09-08',1),('2015-01-21',.75),('2015-07-15',.5),('2017-07-12',.75),('2017-09-06',1),('2018-01-17',1.25),('2018-07-11',1.5),('2018-10-24',1.75),('2020-03-04',1.25),('2020-03-13',.75),('2020-03-27',.25),('2022-03-02',.5),('2022-04-13',1),('2022-06-01',1.5),('2022-07-13',2.5),('2022-09-07',3.25),('2022-10-26',3.75),('2022-12-07',4.25),('2023-01-25',4.5),('2023-06-07',4.75),('2023-07-12',5),('2024-06-05',4.75),('2024-07-24',4.5),('2024-09-04',4.25),('2024-10-23',3.75),('2024-12-11',3.25),('2025-01-29',3),('2025-03-12',2.75),('2025-09-17',2.5),('2025-10-29',2.25)],
 'AUD': [('2010-01-01',3.75),('2010-03-02',4),('2010-04-06',4.25),('2010-05-04',4.5),('2010-11-02',4.75),('2011-11-01',4.5),('2011-12-06',4.25),('2012-05-01',3.75),('2012-06-05',3.5),('2012-10-02',3.25),('2012-12-04',3),('2013-05-07',2.75),('2013-08-06',2.5),('2015-02-03',2.25),('2015-05-05',2),('2016-05-03',1.75),('2016-08-02',1.5),('2019-06-04',1.25),('2019-07-02',1),('2019-10-01',.75),('2020-03-03',.5),('2020-03-19',.25),('2020-11-03',.1),('2022-05-03',.35),('2022-06-07',.85),('2022-07-05',1.35),('2022-08-02',1.85),('2022-09-06',2.35),('2022-10-04',2.6),('2022-11-01',2.85),('2022-12-06',3.1),('2023-02-07',3.35),('2023-03-07',3.6),('2023-05-02',3.85),('2023-06-06',4.1),('2023-11-07',4.35),('2025-02-18',4.1),('2025-05-20',3.85),('2025-08-12',3.6),('2026-02-03',3.85),('2026-05-05',4.1)],
 'NZD': [('2010-01-01',2.5),('2010-06-10',2.75),('2010-07-29',3),('2011-03-17',2.5),('2014-03-13',2.75),('2014-04-24',3),('2014-06-12',3.25),('2014-07-24',3.5),('2015-06-11',3.25),('2015-07-23',3),('2015-09-10',2.75),('2015-12-10',2.5),('2016-03-10',2.25),('2016-08-11',2),('2016-11-10',1.75),('2019-05-08',1.5),('2019-08-07',1),('2020-03-16',.25),('2021-10-06',.5),('2021-11-24',.75),('2022-02-23',1),('2022-04-13',1.5),('2022-05-25',2),('2022-07-13',2.5),('2022-08-17',3),('2022-10-05',3.5),('2022-11-23',4.25),('2023-02-22',4.75),('2023-04-05',5.25),('2024-08-14',5),('2024-10-09',4.5),('2024-11-27',4.25),('2025-02-19',3.75),('2025-04-09',3.5),('2025-05-28',3.25),('2025-08-20',3),('2025-10-08',2.5),('2025-11-26',2.25)],
}
CHG["XAU"] = [("2010-01-01", 0.0)]


def daily_rates(index):
    """Lai suat moi ngay. Truoc ngay dau bang CHG dung muc dau tien (gan dung), sau ngay cuoi giu muc cuoi."""
    out = {}
    for c, ch in CHG.items():
        s = pd.Series({pd.Timestamp(d): r for d, r in ch}).sort_index()
        out[c] = s.reindex(s.index.union(index)).ffill().bfill().reindex(index)
    return pd.DataFrame(out)


def rollover_nights(t0, t1, hour=ROLLOVER_HOUR):
    """So dem tinh swap forex: moi lan qua rollover ngay thuong tinh 1, thu Tu tinh 3."""
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    r = pd.date_range(t0.normalize(), t1.normalize(), freq="D") + pd.Timedelta(hours=hour)
    r = r[(r > t0) & (r <= t1) & (r.weekday < 5)]
    return len(r) + 2 * int((r.weekday == 2).sum())


# ------------------------------------------------------------------ doc du lieu
def to_time(s):
    s = s.astype(str).str.strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            pass
    return pd.to_datetime(s, format="mixed")                   # cham, chi dung khi khong khop dinh dang nao


def read_mt5(f):
    with open(f, encoding="utf-8", errors="ignore") as fh:
        head = fh.readline()
    sep = "\t" if "\t" in head else (";" if ";" in head else ",")
    x = pd.read_csv(f, sep=sep)
    x.columns = [c.strip().strip("<>").upper() for c in x.columns]
    if "TIME" not in x.columns and ("TIMESTAMP" in x.columns or "OPEN_TIME" in x.columns):   # file Binance (ms)
        x["T"] = pd.to_datetime(x["TIMESTAMP" if "TIMESTAMP" in x.columns else "OPEN_TIME"], unit="ms")
    elif "DATE" in x.columns and "TIME" in x.columns:
        x["T"] = to_time(x["DATE"].astype(str) + " " + x["TIME"].astype(str))
    elif "TIME" in x.columns:
        x["T"] = to_time(x["TIME"])
    else:
        raise ValueError(f"{os.path.basename(f)}: khong tim thay cot Time/<DATE>")
    x = x.rename(columns={"OPEN": "Open", "HIGH": "High", "LOW": "Low", "CLOSE": "Close"})
    x = x.rename(columns={"T": "Time"}).sort_values("Time").drop_duplicates("Time").reset_index(drop=True)
    dec = int(x["Close"].astype(str).str.extract(r"\.(\d+)")[0].fillna("").str.len().mode()[0])
    if "SPREAD" in x.columns:
        x["spr_pct"] = x["SPREAD"] * 10 ** (-dec) / x["Close"] * 100
    else:
        x["spr_pct"] = np.nan
        print(f"  ! {os.path.basename(f)} khong co cot Spread -> dung spread mac dinh")
    return x[["Time", "Open", "High", "Low", "Close", "spr_pct"]]


def load_folder(folder):
    files, skipped = {}, []
    for f in glob.glob(os.path.join(folder, "*.csv")):
        if not re.search(r"H1(?!\d)|1h(?!\d)|1hour", os.path.basename(f), re.I):   # chi nhan file khung H1
            continue
        m = re.match(r"(DOGEUSD|[A-Za-z]{6})", os.path.basename(f), re.I)
        sym = m.group(1).upper() if m else None
        if sym not in SUPPORTED:
            skipped.append(os.path.basename(f)); continue
        if sym not in files or os.path.getsize(f) > os.path.getsize(files[sym]):
            files[sym] = f
    if skipped:
        print("  Bo qua (khong nhan ra ma): " + ", ".join(skipped))
    return {s: read_mt5(f) for s, f in sorted(files.items())}


def check_utc(data):
    """Nen cuoi thu Sau phai mo luc 20:00 (mua he) / 21:00 (mua dong) neu du lieu la UTC."""
    ref = next((p for p in ("EURUSD", "GBPUSD", "USDJPY") if p in data), None) or next(iter(fx_pairs(data)), None)
    if ref is None:
        return
    t = data[ref].Time
    fri = t[t.dt.weekday == 4]                                   # nen cuoi cua tung ngay thu Sau
    last = fri.groupby(fri.dt.date).max()                        # (nhom theo tuan se lay nham nen Chu nhat)
    hrs = set(last.dt.hour.value_counts().head(2).index)
    if not hrs:
        print(f"  ! Khong kiem tra duoc mui gio tu {ref}"); return
    if hrs <= {20, 21}:
        print(f"  Kiem tra mui gio ({ref}): nen cuoi thu Sau mo luc {sorted(hrs)}h -> du lieu la UTC, OK")
    else:
        print(f"  !!! CANH BAO mui gio ({ref}): nen cuoi thu Sau mo luc {sorted(hrs)}h, KHONG giong UTC "
              f"(UTC phai la 20h/21h). Ranh gioi ngay, 'dau tuan', SMA200 se lech. Hay xuat du lieu theo UTC.")


# ------------------------------------------------------------------ chi bao
def wpr_ema(h, l, c, period=14, span=5):
    hh = pd.Series(h).rolling(period).max().values
    ll = pd.Series(l).rolling(period).min().values
    return pd.Series(-100 * (hh - c) / (hh - ll)).ewm(span=span, adjust=False).mean().values


def atr_ewm(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values


def supertrend(h, l, c, n=10, m=3.0):
    """Tra ve (chieu, duong tren, duong duoi). Chieu +1 = tang."""
    atr = atr_ewm(h, l, c, n)
    hl2 = (h + l) / 2
    ub, lb = hl2 + m * atr, hl2 - m * atr
    fu, fl, d = ub.copy(), lb.copy(), np.ones(len(c))
    for i in range(1, len(c)):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else (-1 if c[i] < fl[i - 1] else d[i - 1])
    return d, fu, fl


def daily_bars(x, weekdays_only=True):
    t = x.set_index("Time")
    d = t.resample("1D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    d["spr_pct"] = t["spr_pct"].resample("1D").median()
    if weekdays_only:
        d = d[d.index.weekday < 5]
    d["spr_pct"] = d["spr_pct"].ffill().fillna(0.03)
    return d


def bars_4h(x):
    b = x.set_index("Time").resample("4h").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "spr_pct": "median"}).dropna()
    last = x.Time.iat[-1]
    end = last + pd.Timedelta(hours=1)
    if last.weekday() == 4 and last.hour >= 20:
        end = last + pd.Timedelta(hours=4)                               # forex dong cua cuoi tuan -> nen 4H cuoi da xong
    return b[b.index + pd.Timedelta(hours=4) <= end]                    # bo nen 4H chua dong


def fx_pairs(data):
    return [p for p in data if p[:3] in FX and p[3:] in FX]


def a_symbols(data):
    return [q for q in fx_pairs(data) if "JPY" not in q]


OPEN, PENDING = [], []      # lenh con mo cuoi du lieu / tin hieu cho vao o nen ke tiep (dung cho --signals)


# ------------------------------------------------------------------ nhan to dong tien (cho B, D, E)
_FCACHE = {}


def currency_factors(data, freq):
    """Tach loi nhuan cac cap thanh 8 nhan to dong tien (binh phuong nho nhat), roi neo theo trung vi 7 dong con lai
    de mot cu soc cua 1 dong (vd SNB 2015) khong lan sang cac dong khac."""
    if freq in _FCACHE:
        return _FCACHE[freq]
    P = fx_pairs(data)
    if len(P) < MIN_FX_PAIRS:
        _FCACHE[freq] = None
        return None
    C = pd.DataFrame({p: data[p].set_index("Time").Close.resample(freq).last() for p in P})
    if freq == "1D":
        C = C[C.index.weekday < 5]
    r = np.log(C).diff()
    r = r[r.notna().sum(axis=1) >= len(P) - 2]
    A = np.zeros((len(P), 8))
    for i, p in enumerate(P):
        A[i, CUR.index(p[:3])] = 1; A[i, CUR.index(p[3:])] = -1
    R = r.values; M = ~np.isnan(R); F = np.full((len(r), 8), np.nan)
    for pat in np.unique(M, axis=0):
        rows = (M == pat).all(axis=1)
        Aa = np.vstack([A[pat], np.ones(8)])
        X = np.hstack([R[rows][:, pat], np.zeros((rows.sum(), 1))])
        F[rows] = np.linalg.lstsq(Aa, X.T, rcond=None)[0].T
    F = pd.DataFrame(F, index=r.index, columns=CUR).dropna()
    F = pd.DataFrame({c: F[c] - F.drop(columns=c).median(axis=1) for c in CUR})
    _FCACHE[freq] = F
    return F


def currency_z(F, N):
    I = F.cumsum()
    return (I - I.rolling(N).mean()) / I.rolling(N).std()


def extreme_state(za, zq, T, exit_lvl, max_age):
    """+1: boi canh LONG (tu so qua yeu, mau so qua manh), -1: boi canh SHORT, 0: khong."""
    s = za - zq; st = np.zeros(len(s)); cur = 0; age = 0
    for t in range(len(s)):
        if cur != 0:
            age += 1
            if abs(s[t]) < exit_lvl or age >= max_age:
                cur = 0
        if cur == 0 and not np.isnan(s[t]):
            if za[t] >= T and zq[t] <= -T:
                cur, age = -1, 0
            elif za[t] <= -T and zq[t] >= T:
                cur, age = 1, 0
        st[t] = cur
    return st


def need_factors(part):
    print(f"  ! {part}: can it nhat {MIN_FX_PAIRS} cap forex de tach nhan to dong tien -> bo qua")


# ------------------------------------------------------------------ A
def a_unit(atr, price):
    return max(atr, ATR_FLOOR_PCT / 100 * price)


def rule_A(data):
    """Ung vien moi cap, roi xet chung theo thoi gian: moi dong tien toi da A_MAX_PER_CCY lenh dang mo."""
    cands = []
    for p in a_symbols(data):
        x = data[p]
        d = daily_bars(x)
        o, h, l, c, sp = (d[k].values for k in ["Open", "High", "Low", "Close", "spr_pct"])
        atr = atr_ewm(h, l, c)
        s200 = pd.Series(c).rolling(200).mean().values
        xs = x[x.Time.dt.weekday != 6].reset_index(drop=True)
        w = wpr_ema(xs.High.values, xs.Low.values, xs.Close.values)
        h1_close = xs.Time.values + np.timedelta64(1, "h")
        wd = d.index.weekday.values
        for a in [i for i in range(201, len(d)) if wd[i] < wd[i - 1]]:
            k = np.searchsorted(h1_close, d.index.values[a], side="right") - 1
            if k < 30 or np.isnan(w[k]) or not (w[k] < -80 and c[a - 1] < s200[a - 1]):
                continue
            ex = a + A_HOLD_DAYS - 1; e = o[a]; u = a_unit(atr[a - 1], e)
            if ex >= len(d):
                cands.append(dict(he="A", pair=p, side=1, vao=d.index[a], ra=pd.Timestamp.max, gia_vao=e, rui_ro=u, wpr=w[k],
                                  con_ngay=ex - len(d) + 1, _open=True))
            else:
                cands.append(dict(he="A", pair=p, side=1, vao=d.index[a], ra=d.index[ex] + pd.Timedelta(hours=23, minutes=59),
                                  gia_vao=e, gia_ra=c[ex], rui_ro=u, R=(c[ex] - e - sp[a] / 100 * e) / u, wpr=w[k]))
    out, opn = [], []
    for cd in sorted(cands, key=lambda z: (z["vao"], z["wpr"])):        # cung ngay: qua ban sau nhat truoc
        opn = [z for z in opn if z["ra"] > cd["vao"]]
        cnt = {}
        for z in opn:
            for cc in (z["pair"][:3], z["pair"][3:]):
                cnt[cc] = cnt.get(cc, 0) + 1
        if cnt.get(cd["pair"][:3], 0) >= A_MAX_PER_CCY or cnt.get(cd["pair"][3:], 0) >= A_MAX_PER_CCY:
            continue
        opn.append(cd)
        if cd.get("_open"):
            OPEN.append(dict({k: v for k, v in cd.items() if k not in ("ra", "_open")},
                             ghi_chu=f"dong o gia dong cua ngay giao dich thu 8 (con {cd['con_ngay']} ngay)"))
        else:
            out.append(cd)
    return out


# ------------------------------------------------------------------ B
def rule_B(data, only_jpy_driven=False):
    F4 = currency_factors(data, "4h"); out = []
    for p in [q for q in fx_pairs(data) if "JPY" in q]:
        X = p[:3]; b = bars_4h(data[p])
        o, h, l, c = b.Open.values, b.High.values, b.Low.values, b.Close.values
        sp = np.nan_to_num(b.spr_pct.values, nan=0.02)
        d, _, fl = supertrend(h, l, c, 10, 3)
        if F4 is not None:
            fx = F4[X].reindex(b.index).fillna(0).rolling(B_DRIVER_WIN).sum().values
            fj = (-F4["JPY"]).reindex(b.index).fillna(0).rolling(B_DRIVER_WIN).sum().values
        for i in np.where((d[1:] == 1) & (d[:-1] == -1))[0] + 1:
            if i < 50:
                continue
            cause = "?"
            if F4 is not None:
                tot = fx[i] + fj[i]; sh = fx[i] / tot if tot > 0 else np.nan
                cause = "JPY tu yeu" if sh < 0.33 else ("XX manh" if sh > 0.67 else "hon hop")
            if only_jpy_driven and cause != "JPY tu yeu":
                continue
            a = i + 1
            if a >= len(b):
                PENDING.append(dict(he="B", pair=p, side=1, t_vao=b.index[i] + pd.Timedelta(hours=4), sl=fl[i], nguyen_nhan=cause,
                                    ghi_chu=f"LONG o gia mo nen 4H ke tiep, SL {fl[i]:.5g} ({cause})"))
                continue
            e, sl = o[a], fl[i]
            risk = e - sl
            if risk <= 0:
                continue
            xp = None
            for j in range(a, len(b)):
                if l[j] <= sl:
                    xp = min(o[j], sl) if j > a else sl
                    break
                sl = max(sl, fl[j])
            if xp is None:
                OPEN.append(dict(he="B", pair=p, side=1, vao=b.index[a], gia_vao=e, sl=sl, rui_ro=risk, nguyen_nhan=cause,
                                 ghi_chu=f"SL hien tai {sl:.5g} ({cause})"))
                continue
            out.append(dict(he="B", pair=p, side=1, vao=b.index[a], ra=b.index[j] + pd.Timedelta(hours=4),
                            gia_vao=e, gia_ra=xp, rui_ro=risk, R=(xp - e - sp[a] / 100 * e) / risk, nguyen_nhan=cause))
    return out


# ------------------------------------------------------------------ C (CUSUM short JPY)
def cusum_events(x, h, k=0.5, span=100):
    z = (x / x.ewm(span=span).std().shift(1)).fillna(0).values; sp = sn = 0; ev = []
    for i, v in enumerate(z):
        sp = max(0, sp + v - k); sn = min(0, sn + v + k)
        if sp > h:
            ev.append((i, 1)); sp = sn = 0
        elif sn < -h:
            ev.append((i, -1)); sp = sn = 0
    return ev


def rule_C(data):
    out = []
    for p in [q for q in fx_pairs(data) if "JPY" in q]:
        b = bars_4h(data[p]); o, h, l, c = b.Open.values, b.High.values, b.Low.values, b.Close.values
        atr = atr_ewm(h, l, c, 14); sp = np.nan_to_num(b.spr_pct.values, nan=0.02); busy = -1
        for i, s in cusum_events(np.log(b.Close).diff(), C_H, C_K):
            a = i + 1
            if s != -1 or i < 100 or a <= busy:
                continue
            if a >= len(b):
                PENDING.append(dict(he="C", pair=p, side=-1, t_vao=b.index[i] + pd.Timedelta(hours=4), sl_kc=3 * atr[i],
                                    ghi_chu=f"SHORT o gia mo nen 4H ke tiep, SL = gia vao + {3 * atr[i]:.5g}"))
                continue
            e = o[a]; risk = 3 * atr[i]; sl = e + risk; ext = e; xp = None
            for j in range(a, len(b)):
                if h[j] >= sl:
                    xp = max(o[j], sl) if j > a else sl
                    break
                ext = min(ext, l[j]); sl = min(sl, ext + 3 * atr[j])
            if xp is None:
                OPEN.append(dict(he="C", pair=p, side=-1, vao=b.index[a], gia_vao=e, sl=sl, rui_ro=risk, ghi_chu=f"SL hien tai {sl:.5g}"))
                busy = len(b); continue
            busy = j
            out.append(dict(he="C", pair=p, side=-1, vao=b.index[a], ra=b.index[j] + pd.Timedelta(hours=4),
                            gia_vao=e, gia_ra=xp, rui_ro=risk, R=(e - xp) / risk - sp[a] / 100 * e / risk))
    return out


# ------------------------------------------------------------------ D (dao chieu suc manh dong tien, khung ngay)
def rule_D(data):
    F = currency_factors(data, "1D")
    if F is None:
        need_factors("D"); return []
    P = fx_pairs(data); z = currency_z(F, D_N); idx = z.index; n = len(idx)
    O, Cl, SP, AT = [], [], [], []
    for p in P:
        db = daily_bars(data[p])
        AT.append(pd.Series(atr_ewm(db.High.values, db.Low.values, db.Close.values), db.index).reindex(idx).ffill().values)
        db = db.reindex(idx).ffill()
        O.append(db.Open.values); Cl.append(db.Close.values); SP.append(db.spr_pct.values / 100)
    O, Cl, SP, AT = (np.column_stack(v) for v in (O, Cl, SP, AT))
    ZA = np.column_stack([z[p[:3]].values for p in P]); ZQ = np.column_stack([z[p[3:]].values for p in P]); S = ZA - ZQ
    ccy = [(p[:3], p[3:]) for p in P]; opn = {}; out = []
    for t in range(D_N, n):
        for j in list(opn):
            q = opn[j]; q["age"] += 1
            if abs(S[t, j]) < D_EXIT or q["age"] >= D_MAXAGE:
                if t + 1 < n:
                    px = O[t + 1, j]; e = q["e"]
                    out.append(dict(he="D", pair=P[j], side=q["s"], vao=idx[q["t0"]], ra=idx[t + 1], gia_vao=e, gia_ra=px,
                                    rui_ro=q["u"], R=q["s"] * (px - e) / q["u"] - SP[q["t0"], j] * e / q["u"]))
                    del opn[j]
                else:
                    q["thoat"] = True
        cnt = {}
        for j in opn:
            for cc in ccy[j]:
                cnt[cc] = cnt.get(cc, 0) + 1
        cand = []
        for j in range(len(P)):
            if j in opn or np.isnan(S[t, j]) or np.isnan(AT[t, j]):
                continue
            if ZA[t, j] >= D_T and ZQ[t, j] <= -D_T:
                cand.append((abs(S[t, j]), j, -1))
            elif ZA[t, j] <= -D_T and ZQ[t, j] >= D_T:
                cand.append((abs(S[t, j]), j, 1))
        n_pend = 0
        for _, j, s in sorted(cand, reverse=True):                    # uu tien cap bi gian nhat
            a_, q_ = ccy[j]
            if len(opn) + n_pend >= D_MAX_TOTAL or cnt.get(a_, 0) >= D_MAX_PER_CCY or cnt.get(q_, 0) >= D_MAX_PER_CCY:
                continue
            cnt[a_] = cnt.get(a_, 0) + 1; cnt[q_] = cnt.get(q_, 0) + 1
            if t + 1 >= n:
                n_pend += 1
                PENDING.append(dict(he="D", pair=P[j], side=s, t_vao=pd.Timestamp(idx[t]).normalize() + pd.offsets.BDay(1),
                                    rui_ro=a_unit(AT[t, j], Cl[t, j]), z_tu=ZA[t, j], z_mau=ZQ[t, j],
                                    ghi_chu=f"{'LONG' if s == 1 else 'SHORT'} o gia mo ngay ke tiep (z {ccy[j][0]} {ZA[t, j]:+.1f}, "
                                            f"z {ccy[j][1]} {ZQ[t, j]:+.1f}), khong SL, thoat khi |z tu - z mau| < {D_EXIT}"))
                continue
            opn[j] = dict(s=s, t0=t + 1, e=O[t + 1, j], u=a_unit(AT[t, j], O[t + 1, j]), age=0)
    for j, q in opn.items():
        OPEN.append(dict(he="D", pair=P[j], side=q["s"], vao=idx[q["t0"]], gia_vao=q["e"], rui_ro=q["u"], do_lech=S[-1, j],
                         tuoi=q["age"], thoat=bool(q.get("thoat")),
                         ghi_chu=("THOAT o gia mo ngay ke tiep" if q.get("thoat") else
                                  f"do lech hien tai {S[-1, j]:+.2f} (thoat khi < {D_EXIT}), da giu {q['age']} ngay")))
    return out


# ------------------------------------------------------------------ E (lop phu 4H -> 1H)
def rule_E(data):
    F4 = currency_factors(data, "4h")
    if F4 is None:
        need_factors("E"); return []
    z4 = currency_z(F4, E_N); out = []
    for p in fx_pairs(data):
        A, Q = p[:3], p[3:]
        su = pd.Series(extreme_state(z4[A].values, z4[Q].values, E_T, 1.0, E_N // 2), z4.index)
        b4 = bars_4h(data[p]); mean = np.exp(np.log(b4.Close).rolling(E_N).mean())
        b1 = data[p].set_index("Time"); slot = b1.index.floor("4h")
        SU = su.shift(1).reindex(slot, method="ffill").fillna(0).values          # chi dung nen 4H da dong
        TP = mean.shift(1).reindex(slot, method="ffill").values
        o, h, l, c = b1.Open.values, b1.High.values, b1.Low.values, b1.Close.values
        sp = np.nan_to_num(b1.spr_pct.values, nan=0.03)
        d, fu, fl = supertrend(h, l, c, 10, 3); busy = -1
        for i in range(1, len(b1)):
            s = int(SU[i])
            if s == 0 or i <= busy or not (d[i] == s and d[i - 1] == -s):
                continue
            a = i + 1; sl = fl[i] if s == 1 else fu[i]; tp = TP[i]
            ref = o[a] if a < len(b1) else c[i]
            risk = s * (ref - sl)
            if risk <= 0 or np.isnan(tp) or s * (tp - ref) <= 0:
                continue
            rr = s * (tp - ref) / risk
            if not (E_RR[0] <= rr <= E_RR[1]):
                continue
            if a >= len(b1):
                PENDING.append(dict(he="E", pair=p, side=s, t_vao=b1.index[i] + pd.Timedelta(hours=1), sl=sl, tp=tp, rr=rr,
                                    ghi_chu=f"{'LONG' if s == 1 else 'SHORT'} o gia mo nen 1H ke tiep, "
                                                                     f"SL {sl:.5g}, TP {tp:.5g} (RR ~{rr:.1f})"))
                continue
            e = o[a]; xp = None
            for j in range(a, len(b1)):
                if (s == 1 and l[j] <= sl) or (s == -1 and h[j] >= sl):
                    xp = (min(o[j], sl) if s == 1 else max(o[j], sl)) if j > a else sl
                    break
                if (s == 1 and h[j] >= tp) or (s == -1 and l[j] <= tp):
                    xp = (max(o[j], tp) if s == 1 else min(o[j], tp)) if j > a else tp
                    break
            if xp is None:
                OPEN.append(dict(he="E", pair=p, side=s, vao=b1.index[a], gia_vao=e, sl=sl, tp=tp, rui_ro=risk,
                                 ghi_chu=f"SL {sl:.5g}, TP {tp:.5g}"))
                busy = len(b1); continue
            busy = j
            out.append(dict(he="E", pair=p, side=s, vao=b1.index[a], ra=b1.index[j] + pd.Timedelta(hours=1), gia_vao=e,
                            gia_ra=xp, rui_ro=risk, R=s * (xp - e) / risk - sp[a] / 100 * e / risk, RR=rr))
    return out


# ------------------------------------------------------------------ BB squeeze (crypto)
def bb_squeeze(df, cost, N=20, W=4000, hold_days=10, bpd=24, k=2.0, pct=10,
               trend_days=30, band=0.02, max_open=5):
    c, o, h, l = df.Close.values, df.Open.values, df.High.values, df.Low.values
    spr = df.spr_pct.values if "spr_pct" in df else np.full(len(df), np.nan)
    mid = df.Close.rolling(N).mean()
    sd = df.Close.rolling(N).std(ddof=0)
    up, lo = (mid + k * sd).values, (mid - k * sd).values
    width = (up - lo) / mid.values
    thr = pd.Series(width).rolling(W, min_periods=int(60 * bpd)).quantile(pct / 100).values
    sq = pd.Series((width < thr).astype(float)).rolling(N, min_periods=1).max().values > 0
    c_lag = pd.Series(c).shift(int(trend_days * bpd)).values
    wd = df.Time.dt.weekday.values
    hold = int(hold_days * bpd)
    trades, opn, last, pend = [], [], -10 ** 9, []
    for i in range(len(df)):
        keep = []
        for p in opn:
            s = p["s"]
            if (s == 1 and l[i] <= p["sl"]) or (s == -1 and h[i] >= p["sl"]):
                xp = (min(o[i], p["sl"]) if s == 1 else max(o[i], p["sl"])) if i > p["i"] else p["sl"]
                trades.append((p, df.Time.iat[i] + pd.Timedelta(hours=1), xp)); continue
            if i - p["i"] >= hold:
                trades.append((p, df.Time.iat[i] + pd.Timedelta(hours=1), c[i])); continue
            nb = lo[i] if s == 1 else up[i]
            if not np.isnan(nb):
                p["sl"] = max(p["sl"], nb) if s == 1 else min(p["sl"], nb)
            keep.append(p)
        opn = keep
        if np.isnan(thr[i]) or not sq[i] or wd[i] >= 5 or i - last < N:
            continue
        s = 1 if c[i] > up[i] else (-1 if c[i] < lo[i] else 0)
        if s == 0:
            continue
        if not np.isnan(c_lag[i]) and ((s == 1 and c[i] < c_lag[i] * (1 - band)) or
                                       (s == -1 and c[i] > c_lag[i] * (1 + band))):
            continue
        if len(opn) >= max_open or any(p["s"] != s for p in opn):
            continue
        sl = lo[i] if s == 1 else up[i]
        if i + 1 >= len(df):
            pend.append((s, sl, df.Time.iat[i] + pd.Timedelta(hours=1))); continue
        e = o[i + 1]
        r0 = (e - sl) * s / e * 100
        if r0 > 0:
            cst = max(cost, spr[i + 1]) if not np.isnan(spr[i + 1]) else cost     # chi phi = max(gia dinh, spread thuc te)
            if cst > BB_MAX_COST_R * r0:                                         # phi an qua nhieu rui ro -> bo
                continue
            opn.append(dict(t=df.Time.iat[i + 1], i=i + 1, s=s, e=e, sl=sl, r0=r0, cost=cst))
            last = i
    res = [(p["t"], t_out, p["s"], p["e"], xp, p["e"] * p["r0"] / 100,
            (p["s"] * (xp - p["e"]) / p["e"] * 100 - p["cost"]) / p["r0"]) for p, t_out, xp in trades]
    return res, opn, pend


def rule_BB(data):
    out = []
    for p, lab in [("BTCUSD", "BB BTC"), ("ETHUSD", "BB ETH"), ("SOLUSD", "BB SOL")]:
        if p not in data:
            continue
        df = data[p][["Time", "Open", "High", "Low", "Close", "spr_pct"]].reset_index(drop=True)
        res, opn, pend = bb_squeeze(df, COST_CRYPTO[p])
        for t_in, t_out, s, e, xp, risk, R in res:
            out.append(dict(he=lab, pair=p, side=s, vao=t_in, ra=t_out, gia_vao=e, gia_ra=xp, rui_ro=risk, R=R))
        for q in opn:
            OPEN.append(dict(he=lab, pair=p, side=q["s"], vao=q["t"], gia_vao=q["e"], sl=q["sl"], rui_ro=q["e"] * q["r0"] / 100,
                             gio_giu=len(df) - q["i"], ghi_chu=f"SL hien tai {q['sl']:.6g}"))
        for s, sl, tv in pend:
            PENDING.append(dict(he=lab, pair=p, side=s, t_vao=tv, sl=sl,
                                ghi_chu=f"{'LONG' if s == 1 else 'SHORT'} o gia mo nen 1H ke tiep, SL {sl:.6g}"))
    return out


# ------------------------------------------------------------------ AQB (band phan vi thich ung: crypto, vang)
def aqb_label(sym):
    return "AQB " + sym.replace("USD", "")


def rule_AQB(data):
    """Squeeze -> loi suat 4 nen da chuan hoa theo bien dong vuot phan vi q -> vao theo chieu pha;
    SL = band p1/p99, keo theo band; giu toi da N ngay; crypto khong vao thu Bay/CN."""
    out = []
    for sym, (sqp, qe, hold, flt) in AQB_PARAMS.items():
        if sym not in data:
            continue
        df = data[sym].reset_index(drop=True); lab = aqb_label(sym); H, W = AQB_H, AQB_W
        c = df.Close; lr = np.log(c).diff(); sig = np.sqrt((lr ** 2).ewm(halflife=24).mean()).shift(1)
        z = (np.log(c / c.shift(H)) / (sig.shift(H) * np.sqrt(H))).values
        q = {pp: pd.Series(z).rolling(W, min_periods=720).quantile(pp / 100).values for pp in (1, 100 - qe, qe, 99)}
        sq = (sig < sig.rolling(W, min_periods=720).quantile(sqp / 100)).astype(float).rolling(24, min_periods=1).max().values > 0
        o, h, l, cc, sg = df.Open.values, df.High.values, df.Low.values, c.values, sig.values; T = df.Time
        wd = T.dt.weekday.values; spr = np.nan_to_num(df.spr_pct.values, nan=0.0); lag = c.shift(720).values
        crypto = sym in CRYPTO; floor = COST_CRYPTO.get(sym, 0.0); hi, lo = q[qe], q[100 - qe]; busy, last = -1, -99
        band = lambda j, s: cc[j] * np.exp((q[1][j] if s == 1 else q[99][j]) * sg[j] * np.sqrt(H))
        for i in range(W // 3, len(df)):
            if i <= busy or i - last < 4 or not sq[i] or (crypto and wd[i] >= 5) or np.isnan(hi[i]):
                continue
            s = 1 if (z[i] > hi[i] and z[i - 1] <= hi[i - 1]) else (-1 if (z[i] < lo[i] and z[i - 1] >= lo[i - 1]) else 0)
            if s == 0:
                continue
            if flt and not np.isnan(lag[i]) and ((s == 1 and cc[i] < lag[i] * 0.98) or (s == -1 and cc[i] > lag[i] * 1.02)):
                continue
            sl = band(i, s)
            if i + 1 >= len(df):
                if np.isfinite(sl):
                    PENDING.append(dict(he=lab, pair=sym, side=s, t_vao=T.iat[i] + pd.Timedelta(hours=1), sl=sl,
                                        ghi_chu=f"{'LONG' if s == 1 else 'SHORT'} o gia mo nen 1H ke tiep, SL {sl:.6g} (band, keo theo)"))
                continue
            a = i + 1; e = o[a]; risk = s * (e - sl)
            if not risk > 0:
                continue
            cost = max(floor, spr[a]) / 100 * e
            if cost > BB_MAX_COST_R * risk:
                continue
            xp = None
            for j in range(a, len(df)):
                if (s == 1 and l[j] <= sl) or (s == -1 and h[j] >= sl):
                    xp = (min(o[j], sl) if s == 1 else max(o[j], sl)) if j > a else sl; break
                if j - a >= hold * 24:
                    xp = cc[j]; break
                nb = band(j, s)
                if not np.isnan(nb):
                    sl = max(sl, nb) if s == 1 else min(sl, nb)
            if xp is None:
                OPEN.append(dict(he=lab, pair=sym, side=s, vao=T.iat[a], gia_vao=e, sl=sl, rui_ro=risk, gio_giu=len(df) - a,
                                 ghi_chu=f"SL hien tai {sl:.6g}, toi da {hold} ngay"))
                busy, last = len(df), i
                continue
            out.append(dict(he=lab, pair=sym, side=s, vao=T.iat[a], ra=T.iat[j] + pd.Timedelta(hours=1), gia_vao=e, gia_ra=xp,
                            rui_ro=risk, R=s * (xp - e) / risk - cost / risk))
            busy, last = j, i
    return out


# ------------------------------------------------------------------ danh muc: gioi han + ngat mach
def sleeve(he):
    return "A" if he == "A" else ("FX" if he in ("B", "C", "D", "E") else ("Crypto" if he.split()[-1] in
                                  ("BTC", "ETH", "SOL", "DOGE") else "Vang"))


def portfolio_sim(T, data, start):
    """Mo phong theo ngay, xet tung lenh theo thu tu vao: tran rui ro mo, tran crypto, ngat mach phan/tha noi/sut giam.
    Tra ve (loi nhuan ngay, lenh duoc vao, so lan kich hoat)."""
    T = T[(pd.to_datetime(T.vao) >= start) & T.pair.isin(list(data))].sort_values("vao").reset_index(drop=True)
    closes = {p: daily_bars(data[p], weekdays_only=p not in CRYPTO).Close for p in T.pair.unique()}
    days = pd.date_range(pd.Timestamp(start).normalize(), pd.to_datetime(T.ra).max().normalize()); di = {d: i for i, d in enumerate(days)}
    INC, ENT, LAST = [], [], []
    for r in T.itertuples():
        sc = RISK[r.he] / r.rui_ro; d0, d1 = pd.Timestamp(r.vao).normalize(), pd.Timestamp(r.ra).normalize(); prev = 0.0; inc = {}
        for d, px in closes[r.pair].loc[d0:d1 - pd.Timedelta(days=1)].items():
            v = r.side * (px - r.gia_vao) * sc; inc[di[d]] = inc.get(di[d], 0) + v - prev; prev = v
        inc[di[d1]] = inc.get(di[d1], 0) + r.R * RISK[r.he] - prev
        INC.append(inc); ENT.append(di[d0]); LAST.append(di[d1])
    by_day = {}
    for k, e0 in enumerate(ENT):
        by_day.setdefault(e0, []).append(k)
    SL_ = [sleeve(h) for h in T.he]; RK = [RISK[h] for h in T.he]; CR = [p in CRYPTO for p in T.pair]
    pnl = np.zeros(len(days)); eq = peak = 1.0; active, cum = {}, {}; month = None; mtd = {}; stop = {}; dd_stop = False
    trig = {"phan A": 0, "phan FX": 0, "tha noi": 0, "sut giam": 0, "tran rui ro": 0, "tran crypto": 0}; taken = []
    for t, d in enumerate(days):
        if month != (d.year, d.month):
            month = (d.year, d.month); mtd = {k: 0.0 for k in BREAK_SLEEVE_MONTH}; stop = {k: False for k in BREAK_SLEEVE_MONTH}
        for k in by_day.get(t, []):
            if dd_stop or stop.get(SL_[k], False):
                continue
            if sum(RK[j] for j in active) + RK[k] > MAX_OPEN_RISK + 1e-9:
                trig["tran rui ro"] += 1; continue
            if CR[k] and sum(CR[j] for j in active) >= CRYPTO_MAX_OPEN:
                trig["tran crypto"] += 1; continue
            active[k] = True; cum[k] = 0.0; taken.append(k)
        tot = 0.0; sv = {k: 0.0 for k in BREAK_SLEEVE_MONTH}
        for k in list(active):
            v = INC[k].get(t, 0.0); tot += v; cum[k] += v
            if SL_[k] in sv:
                sv[SL_[k]] += v
            if t >= LAST[k]:
                del active[k]; del cum[k]
        pnl[t] = tot / 100; eq *= 1 + pnl[t]; peak = max(peak, eq)
        for k_, lim in BREAK_SLEEVE_MONTH.items():
            mtd[k_] += sv[k_] / 100
            if not stop[k_] and mtd[k_] <= -lim / 100:
                stop[k_] = True; trig["phan " + k_] += 1
        if sum(cum.values()) / 100 <= -BREAK_FLOAT / 100:
            active.clear(); cum.clear(); trig["tha noi"] += 1
        if not dd_stop and eq / peak - 1 <= -BREAK_DD / 100:
            dd_stop = True; trig["sut giam"] += 1
    return pd.Series(pnl, days), T.loc[taken], trig


# ------------------------------------------------------------------ swap
def add_swap(T):
    """Forex/vang: dem so lan qua rollover (thu Tu x3). Crypto: tinh theo ngay lich."""
    vao, ra = pd.to_datetime(T.vao), pd.to_datetime(T.ra)
    rates = daily_rates(pd.date_range(min(vao.min().normalize(), pd.Timestamp("2009-01-01")),
                                      max(ra.max().normalize(), pd.Timestamp.today().normalize())))
    sw_pct = []
    for r, t0, t1 in zip(T.itertuples(), vao, ra):
        if r.pair in CRYPTO:
            sw_pct.append(CRYPTO_SWAP * (t1 - t0).total_seconds() / 86400 / 365); continue
        b, q = r.pair[:3], r.pair[3:]
        rr = rates.loc[t0.normalize():t1.normalize()]
        diff = (rr[b] - rr[q]).mean() * r.side if len(rr) else 0.0
        sw_pct.append((diff - SWAP_MARKUP) * rollover_nights(t0, t1) / 365)
    T["swap_R"] = np.array(sw_pct) / (T.rui_ro / T.gia_vao * 100)     # doi % gia tri lenh -> R
    T["R"] = T["R"] + T["swap_R"]
    return T


# ------------------------------------------------------------------ danh gia theo ngay (gom floating)
def daily_mtm(T, data):
    """Lai/lo moi ngay tinh ca floating: danh dau lenh theo gia dong cua moi ngay dang giu."""
    T = T[T.pair.isin(list(data))]
    closes = {p: daily_bars(data[p], weekdays_only=p not in CRYPTO).Close for p in T.pair.unique()}
    inc = {}
    for r in T.itertuples():
        scale = RISK[r.he] / r.rui_ro
        d0, d1 = pd.Timestamp(r.vao).normalize(), pd.Timestamp(r.ra).normalize()
        prev = 0.0
        for d, px in closes[r.pair].loc[d0:d1 - pd.Timedelta(days=1)].items():
            v = r.side * (px - r.gia_vao) * scale
            inc[d] = inc.get(d, 0.0) + v - prev; prev = v
        inc[d1] = inc.get(d1, 0.0) + r.R * RISK[r.he] - prev
    return pd.Series(inc, dtype=float).sort_index() / 100


# ------------------------------------------------------------------ bao cao
ORDER = ["A", "B", "C", "D", "E", "AQB XAU", "BB BTC", "BB ETH", "BB SOL", "AQB BTC", "AQB ETH", "AQB SOL", "AQB DOGE"]


def report(T, data, start="2011-09-01"):
    if T.empty:
        print("Khong co lenh nao."); return
    T = T[pd.to_datetime(T.vao) >= start].copy()
    T["pct"] = T.R * T.he.map(RISK)
    T["ra_d"] = pd.to_datetime(T.ra).dt.normalize()
    missing = sorted(set(T.pair) - set(data))
    if missing:
        print(f"  ! Khong co du lieu gia cho {', '.join(missing)} -> MaxDD floating bo qua cac lenh nay")
    idx = pd.date_range(start, T.ra_d.max(), freq="D")
    real = {h: (g.groupby("ra_d").pct.sum() / 100).reindex(idx).fillna(0) for h, g in T.groupby("he")}
    mtm = {h: daily_mtm(g, data).reindex(idx).fillna(0) for h, g in T.groupby("he")}
    real["TOAN DANH MUC"] = sum(real.values()); mtm["TOAN DANH MUC"] = sum(mtm.values())

    def stats(r):
        nz = r[r != 0]
        if len(nz) < 2:
            return None
        r = r.loc[nz.index.min():]
        e = (1 + r).cumprod(); yrs = max((r.index[-1] - r.index[0]).days / 365.25, 1 / 365.25)
        wk = r.resample("W").sum(); m = r.resample("ME").sum()
        return dict(tu=r.index[0].year, cagr=(e.iloc[-1] ** (1 / yrs) - 1) * 100, dd=(e / e.cummax() - 1).min() * 100,
                    sharpe=wk.mean() / wk.std() * np.sqrt(52) if wk.std() > 0 else np.nan,
                    omega=m[m > 0].sum() / -m[m < 0].sum() if (m < 0).any() else np.nan)

    print(f"\nRui ro moi lenh (% von): " + ", ".join(f"{k} {v}" for k, v in RISK.items() if k in real))
    print(f"\n{'Thanh phan':<15}{'lenh/nam':>9}{'TB R':>8}{'thang':>7} | {'tu':>5}{'Loi/nam':>9}{'Sharpe':>8}{'Omega':>7}"
          f" | {'MaxDD chot':>11}{'MaxDD floating':>15}")
    for k in [k for k in ORDER if k in real] + ["TOAN DANH MUC"]:
        m = T if k == "TOAN DANH MUC" else T[T.he == k]
        a, b_ = stats(real[k]), stats(mtm[k])
        if a is None or b_ is None:
            continue
        yrs = max((pd.to_datetime(m.ra).max() - pd.to_datetime(m.vao).min()).days / 365.25, 0.1)
        print(f"{k:<15}{len(m) / yrs:>9.0f}{m.R.mean():>+8.3f}{(m.R > 0).mean() * 100:>6.0f}% | {b_['tu']:>5}{b_['cagr']:>8.1f}%"
              f"{b_['sharpe']:>8.2f}{b_['omega']:>7.2f} | {a['dd']:>10.1f}%{b_['dd']:>14.1f}%")
    print("Loi/nam, Sharpe (theo tuan), Omega (theo thang) tinh tren chuoi gom floating. Co tinh spread"
          + (" va swap." if "swap_R" in T else ", CHUA tinh swap."))
    ex, taken, trig = portfolio_sim(T, data, start)
    s_ex = stats(ex)
    if s_ex:
        mm = ex.resample("ME").sum()
        print(f"\nDANH MUC THUC THI (tran rui ro mo {MAX_OPEN_RISK:g}%, crypto <= {CRYPTO_MAX_OPEN} lenh, ngat mach):")
        print(f"  {len(taken)}/{len(T)} lenh duoc vao | Loi/nam {s_ex['cagr']:.1f}% | Sharpe {s_ex['sharpe']:.2f} | "
              f"MaxDD {s_ex['dd']:.1f}% | thang te nhat {mm.min() * 100:.1f}%")
        print("  So lan kich hoat: " + ", ".join(f"{k} {v}" for k, v in trig.items()))
        mtm["THUC THI"] = ex.reindex(idx).fillna(0)
    yr = pd.DataFrame({k: v.groupby(v.index.year).apply(lambda s: ((1 + s).prod() - 1) * 100) for k, v in mtm.items()}).round(1)
    print("\nLoi nhuan tung nam (%, gom floating):")
    print(yr[[k for k in ORDER if k in yr] + ["TOAN DANH MUC"] + (["THUC THI"] if "THUC THI" in yr else [])].to_string())
    comp = [k for k in ORDER if k in mtm]
    if len(comp) > 1:
        print("\nTuong quan loi nhuan thang giua cac thanh phan:")
        print(pd.DataFrame({k: mtm[k].resample("ME").sum() for k in comp}).corr().round(2).to_string())
    if "nguyen_nhan" in T and (T.he == "B").any():
        b = T[T.he == "B"]
        print("\nB theo nguyen nhan cu dao chieu (TB R, so lenh): " +
              ", ".join(f"{k} {g.R.mean():+.3f} ({len(g)})" for k, g in b.groupby("nguyen_nhan")))
        j = b[b.nguyen_nhan == "JPY tu yeu"]
        if len(j):
            r12 = j[pd.to_datetime(j.ra) >= pd.to_datetime(j.ra).max() - pd.Timedelta(days=365)].R.sum()
            print(f"  Chi bao che do: tong R cua lenh 'JPY tu yeu' 12 thang gan nhat = {r12:+.1f}R"
                  + ("  -> AM: can nhac giam khoi luong B" if r12 < 0 else ""))
    if "swap_R" in T:
        print("\nAnh huong cua swap (R moi lenh): " + ", ".join(f"{h} {g.swap_R.mean():+.3f}" for h, g in T.groupby("he")))


def a_pending(data, require_week_close=False):
    """Tin hieu A cho tuan toi: WPR-EMA H1 nen cuoi < -80 va gia dong cua ngay cuoi < SMA200 ngay."""
    out = []
    for p in a_symbols(data):
        x = data[p]; xs = x[x.Time.dt.weekday != 6]
        if len(xs) < 300:
            continue
        last = xs.Time.iat[-1]; ok = last.weekday() == 4 and last.hour >= 20
        if require_week_close and not ok:
            continue
        db = daily_bars(x); c = db.Close.values; s200 = pd.Series(c).rolling(200).mean().values
        atr = atr_ewm(db.High.values, db.Low.values, c)
        w = wpr_ema(xs.High.values, xs.Low.values, xs.Close.values)
        if w[-1] < -80 and c[-1] < s200[-1]:
            note = "" if ok else f"  (nen cuoi {last:%a %d/%m %H:%M}, chua phai dong cua thu Sau)"
            out.append(dict(he="A", pair=p, side=1, t_vao=last.normalize() + pd.offsets.BDay(1), rui_ro=a_unit(atr[-1], c[-1]),
                            wpr=w[-1], ghi_chu=f"WPR-EMA {w[-1]:.1f}, duoi SMA200 -> LONG dau tuan{note}"))
    cnt, keep = {}, []                                   # gioi han theo dong tien, tinh ca lenh A dang mo (con ngay > 1)
    for z in OPEN:
        if z["he"] == "A" and z.get("con_ngay", 9) > 1:
            for cc in (z["pair"][:3], z["pair"][3:]):
                cnt[cc] = cnt.get(cc, 0) + 1
    for z in sorted(out, key=lambda v: v["wpr"]):
        a_, q_ = z["pair"][:3], z["pair"][3:]
        if cnt.get(a_, 0) < A_MAX_PER_CCY and cnt.get(q_, 0) < A_MAX_PER_CCY:
            keep.append(z); cnt[a_] = cnt.get(a_, 0) + 1; cnt[q_] = cnt.get(q_, 0) + 1
    return keep


# ------------------------------------------------------------------ tin hieu hien tai
def print_signals(data, parts):
    fx_end = max((data[p].Time.iat[-1] for p in a_symbols(data) + fx_pairs(data)), default=None)
    cr_end = max((data[p].Time.iat[-1] for p in CRYPTO if p in data), default=None)
    print("\nTIN HIEU" + (f" | forex den {fx_end:%a %d/%m/%Y %H:%M} UTC" if fx_end is not None else "")
          + (f" | crypto den {cr_end:%a %d/%m/%Y %H:%M} UTC" if cr_end is not None else ""))
    if fx_end is not None and (pd.Timestamp.now() - fx_end).total_seconds() > 6 * 3600 and not (fx_end.weekday() == 4 and fx_end.hour >= 20):
        print("  ! Du lieu forex chua cap nhat den nen moi nhat (hoac chua co nen dong cua thu Sau). "
              "Tin hieu 'CHO VAO' cua A/B/C/D/E co the da qua thoi diem; hay xuat lai du lieu.")
    if "A" in parts:
        print("\nA: doc o nen dong cua thu Sau; vao luc 00:00 UTC thu Hai, giu 8 ngay giao dich.")
        for x in a_pending(data):
            print(f"  CHO   A  {x['pair']}: {x['ghi_chu']}")
    for lab, L in [("CHO VAO", PENDING), ("DANG MO", OPEN)]:
        rows = [x for x in L if x["he"] in parts or x["he"].split()[0] in parts]
        rows.sort(key=lambda x: ORDER.index(x["he"]) if x["he"] in ORDER else 99)
        print(f"\n{lab} ({len(rows)}):")
        for x in rows:
            vao = f" tu {x['vao']:%d/%m/%Y %H:%M} gia {x['gia_vao']:.6g}" if "vao" in x else ""
            print(f"  {x['he']:<7}{x['pair']:<8}{'LONG ' if x['side'] == 1 else 'SHORT'}{vao}  {x['ghi_chu']}")
    if "D" in parts or "E" in parts:
        d_open = sum(1 for x in OPEN if x["he"] == "D")
        print(f"\nGhi chu: D gioi han {D_MAX_PER_CCY} lenh/dong, tong {D_MAX_TOTAL} lenh (hien mo {d_open}). "
              f"Tin hieu 'CHO VAO' da tinh gioi han nay.")


# ------------------------------------------------------------------ main
def run_parts(data, parts, b_filter=False):
    rows = []
    for part, fn in [("A", rule_A), ("B", lambda d: rule_B(d, b_filter)), ("C", rule_C), ("D", rule_D),
                     ("E", rule_E), ("BB", rule_BB), ("AQB", rule_AQB)]:
        if part in parts:
            r = fn(data); rows += r; print(f"{part}: xong ({len(r)} lenh da dong)")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".", help="thu muc chua file CSV H1 xuat tu MT5")
    ap.add_argument("--parts", nargs="+", default=["A", "B", "BB", "AQB", "D", "E"], choices=["A", "B", "BB", "AQB", "C", "D", "E"])
    ap.add_argument("--b-filter", action="store_true", help="B chi vao lenh khi cu dao chieu do JPY tu yeu")
    ap.add_argument("--no-swap", action="store_true", help="khong tinh swap")
    ap.add_argument("--signals", action="store_true", help="in lenh dang mo va tin hieu cho vao")
    ap.add_argument("--load", nargs="+", help="gop danh sach lenh tu cac file CSV da luu, khong chay lai")
    ap.add_argument("--out", default="portfolio_trades.csv", help="file luu danh sach lenh")
    ap.add_argument("--start", default="2011-09-01", help="ngay bat dau tinh bao cao (vd 2021-01-01)")
    args = ap.parse_args()

    data = load_folder(args.data)
    print(f"Da doc {len(data)} ma: {', '.join(data)}")
    print(f"  {len(fx_pairs(data))} cap forex" + ("" if len(fx_pairs(data)) >= MIN_FX_PAIRS else
                                                  f" (< {MIN_FX_PAIRS}: D, E va phan nguyen nhan cua B se bi bo qua)"))
    check_utc(data)
    if args.signals:
        run_parts(data, args.parts, args.b_filter)
        print_signals(data, args.parts)
    else:
        if args.load:
            parts = [pd.read_csv(f, parse_dates=["vao", "ra"]) for f in args.load]
            has_swap = ["swap_R" in p.columns for p in parts]
            if args.no_swap:
                print("  ! --no-swap bi bo qua khi dung --load: swap chi duoc tinh luc chay backtest va luu file.")
            if any(has_swap) and not all(has_swap):
                print("  ! CANH BAO: dang gop file CO swap voi file KHONG co swap. Ket qua khong dong nhat.")
            T = pd.concat(parts, ignore_index=True)
        else:
            T = pd.DataFrame(run_parts(data, args.parts, args.b_filter))
            if not args.no_swap and not T.empty:
                T = add_swap(T)
            if not T.empty:
                T.to_csv(args.out, index=False); print(f"Da luu danh sach lenh vao {args.out}")
        report(T, data, args.start)
