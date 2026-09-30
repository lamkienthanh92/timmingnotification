"""
================================================================================
CLIENT GOI API TWELVE DATA
================================================================================
Tai lieu API: https://twelvedata.com/docs
Endpoint chinh dung: /time_series (lay nen OHLC theo interval)

BAN NAY DA CAP NHAT theo DUNG pattern da CHUNG MINH hoat dong tot trong
project fx-cmt-app-main/scripts/fetch-screener-data.mjs cua chinh ban:

  1. GIOI HAN THAT: goi mien phi Twelve Data la 8 CREDIT/PHUT (khong phai
     "khoang 8" nhu ban nhap truoc do) -- tuong duong ~7.5-8 GIAY/request.
     Ham nay tu dong CHO DU 7.8s giua MOI request (ke ca khi thanh cong),
     khong chi khi bi loi -- giong het cach ban lam trong .mjs.
  2. PHAN BIET 2 LOAI LOI KHAC NHAU (diem quan trong ban .py cu CHUA co):
       a. Rate-limit TAM THOI (429, hoac message chua "api rate limit") ->
          retry duoc, cho theo backoff tang dan.
       b. HET HAN MUC NGAY (message chua "current day"/"per day"/"daily") ->
          retry NGAY LAP TUC VO ICH (han muc chi reset luc 00:00 UTC) -- BAO
          LOI RO RANG va DUNG LAI, khong lang phi thoi gian retry mu quang.
  3. Retry backoff: 20 + attempt*20 giay (dung so cua ban, quy tu ms sang s).
================================================================================
"""
import requests
import pandas as pd
import time
from config import TWELVE_DATA_API_KEY, TWELVE_DATA_BASE_URL, SYMBOL_MAP

# 8 credit/phut (free tier that, theo xac nhan tu code fx-cmt-app-main) ->
# ~7.5s/request de an toan co bien (ho dung 7.8s, giu nguyen cho khop).
MIN_SECONDS_BETWEEN_CALLS = 7.8
_last_call_ts = [0.0]  # dung list de mutate duoc tu trong ham (khong can global)


class TwelveDataError(Exception):
    """Loi thong thuong (het luot retry, sai symbol, v.v.) -- CO THE thu lai
    o lan chay sau (vd ngay mai)."""
    pass


class DailyQuotaExhausted(TwelveDataError):
    """Da het HAN MUC NGAY cua Twelve Data -- retry NGAY BAY GIO vo ich, phai
    doi den khi han muc reset (thuong 00:00 UTC). Bat rieng loai nay de code
    goi ham co the QUYET DINH DUNG HAN, khong lang phi thoi gian retry."""
    pass


def _pace_request():
    """Dam bao it nhat MIN_SECONDS_BETWEEN_CALLS giay giua 2 lan goi API lien
    tiep (ke ca khi lan truoc thanh cong) -- dung cach fx-cmt-app-main lam."""
    elapsed = time.monotonic() - _last_call_ts[0]
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _last_call_ts[0] = time.monotonic()


def _fetch_json(url: str, params: dict) -> dict:
    """Goi API, tra ve JSON da parse. Phan loai loi giong het _fetchJSON
    trong fetch-screener-data.mjs: phan biet rate-limit tam thoi vs het han
    muc ngay, va bao loi ro rang neu response khong phai JSON hop le."""
    _pace_request()
    resp = requests.get(url, params=params, timeout=20)
    text = resp.text
    try:
        data = resp.json()
    except ValueError:
        data = None

    msg = (data or {}).get("message", "") if isinstance(data, dict) else ""
    code = (data or {}).get("code") if isinstance(data, dict) else None
    is_rate_limited = (
        resp.status_code == 429
        or code == 429
        or "run out of api credits" in msg.lower()
        or "api rate limit" in msg.lower()
    )
    if is_rate_limited:
        is_daily = any(k in msg.lower() for k in ("current day", "per day", "daily"))
        if is_daily:
            raise DailyQuotaExhausted(
                f"Da het HAN MUC NGAY cua Twelve Data ({msg or 'day limit'}) -- "
                f"can cho reset (thuong 00:00 UTC), retry ngay bay gio vo ich."
            )
        err = TwelveDataError(msg or "Twelve Data rate limit (429)")
        err.rate_limited = True
        raise err

    if not resp.ok:
        raise TwelveDataError(f"HTTP {resp.status_code}: {text[:200]}")
    if data is None:
        raise TwelveDataError(f"Phan hoi khong phai JSON hop le: {text[:200]}")
    return data


def fetch_time_series(pair: str, interval: str, outputsize: int = 100,
                       max_retries: int = 4) -> pd.DataFrame:
    """Lay du lieu OHLC cho 1 cap, tra ve DataFrame voi cot Time(UTC), Open,
    High, Low, Close (da sap CU->MOI). interval: '1h' hoac '4h'.

    Neu het han muc NGAY, nem DailyQuotaExhausted NGAY (khong retry mu quang)
    -- noi goi ham (vd simulate_full_system.py) nen bat rieng loai nay va
    DUNG CA VONG LAP thay vi tiep tuc thu tung cap con lai (deu se loi giong
    nhau vi cung 1 API key)."""
    symbol = SYMBOL_MAP.get(pair)
    if symbol is None:
        raise TwelveDataError(f"Khong tim thay symbol Twelve Data cho cap {pair}")

    url = f"{TWELVE_DATA_BASE_URL}/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "timezone": "UTC",
        "order": "ASC",
        "apikey": TWELVE_DATA_API_KEY,
    }

    for attempt in range(max_retries):
        try:
            data = _fetch_json(url, params)
        except DailyQuotaExhausted:
            raise  # KHONG retry -- day len tren de dung han
        except TwelveDataError as e:
            if getattr(e, "rate_limited", False) and attempt < max_retries - 1:
                wait_s = 20 + attempt * 20  # giong het backoff cua fetch-screener-data.mjs
                print(f"  [rate-limit] {pair}/{interval} -- cho {wait_s}s "
                      f"(lan {attempt + 1}/{max_retries})...")
                time.sleep(wait_s)
                continue
            raise

        if data.get("status") == "error" or (isinstance(data.get("code"), int) and data["code"] >= 400):
            raise TwelveDataError(f"Twelve Data loi ({pair}/{interval}): {data.get('message')}")
        values = data.get("values")
        if not values:
            raise TwelveDataError(f"Khong co du lieu cho {pair}/{interval}")

        df = pd.DataFrame(values)
        df["Time"] = pd.to_datetime(df["datetime"])
        df = df.rename(columns={"open": "Open", "high": "High",
                                 "low": "Low", "close": "Close"})
        for c in ["Open", "High", "Low", "Close"]:
            df[c] = df[c].astype(float)
        df = df[["Time", "Open", "High", "Low", "Close"]].sort_values("Time").reset_index(drop=True)
        if len(df) < 30:
            raise TwelveDataError(f"Chuoi {pair}/{interval} qua ngan ({len(df)} nen)")
        return df

    raise TwelveDataError(f"Het so lan thu lai cho {pair}/{interval}")


def fetch_latest_price(pair: str) -> float:
    """Lay gia hien tai (dung endpoint /price, nhe hon /time_series).
    Van tuan thu pacing 7.8s giong fetch_time_series."""
    symbol = SYMBOL_MAP.get(pair)
    if symbol is None:
        raise TwelveDataError(f"Khong tim thay symbol Twelve Data cho cap {pair}")
    url = f"{TWELVE_DATA_BASE_URL}/price"
    params = {"symbol": symbol, "apikey": TWELVE_DATA_API_KEY}
    data = _fetch_json(url, params)
    if "price" in data:
        return float(data["price"])
    raise TwelveDataError(f"Loi lay gia {pair}: {data}")
