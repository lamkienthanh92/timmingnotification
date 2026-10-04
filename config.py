"""
CAU HINH BOT (chien luoc danh muc v5: A, B, BB, AQB, D, E; C tuy chon).
Tham so chien luoc nam trong portfolio_backtest.py (dung chung voi backtest) -- KHONG sua o day.
"""
import os

# ------------------------------------------------------------------ Twelve Data
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# 25 cap forex giong bo du lieu da backtest (D, E tach nhan to dong tien tu dung bo cap nay -> khong them/bot tuy y)
FX_PAIRS = ["AUDJPY", "AUDUSD", "CADCHF", "CADJPY", "CHFJPY", "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY",
            "EURNZD", "EURUSD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD", "NZDCAD", "NZDCHF",
            "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"]
CRYPTO_PAIRS = ["BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD"]
METALS = ["XAUUSD"]                      # gio giao dich nhu forex (nghi cuoi tuan)
SYMBOL_MAP = {p: f"{p[:-3]}/{p[-3:]}" for p in FX_PAIRS + CRYPTO_PAIRS + METALS}

# ------------------------------------------------------------------ thanh phan & thong bao
# Thanh phan bot theo doi (bien moi truong PARTS, vd "A,B,BB,D,E" hoac them C)
PARTS = [s.strip().upper() for s in (os.environ.get("PARTS") or "A,B,BB,AQB,D,E").split(",") if s.strip()]
# Chi gui Telegram cho cac thanh phan nay (trong = tat ca). Bot van tinh du de dashboard day du.
NOTIFY_ONLY_PARTS = [s.strip().upper() for s in (os.environ.get("NOTIFY_ONLY_PARTS") or "").split(",") if s.strip()]
B_FILTER = (os.environ.get("B_FILTER") or "").strip().lower() in ("1", "true", "yes")   # B chi vao khi JPY tu yeu

# ------------------------------------------------------------------ lich lay mau (gio UTC)
# - Moi gio (phut :02): BTC, ETH, SOL, DOGE (BB, AQB), XAU (AQB) + cac cap forex dang trong boi canh E hoac co lenh E mo.
# - Moi 4 gio (00, 04, 08, 12, 16, 20 UTC = 07, 11, 15, 19, 23, 03 gio VN): ca 25 cap forex -> B, C, E (boi canh), A/D.
# - Thu Sau 22:00 UTC (5h sang thu Bay VN): lay nen cuoi tuan -> chot tin hieu A, D cho tuan sau.
FULL_EVERY_HOURS = 4
WEEK_CLOSE_HOUR_UTC = 22
VN_OFFSET_HOURS = 7
DAILY_SUMMARY_HOUR_VN = 7          # tom tat buoi sang o lan chay dau tien sau 7h VN (sau khi D/A cham nen ngay)

# ------------------------------------------------------------------ bo nho dem nen H1
CACHE_DIR = os.environ.get("CACHE_DIR") or "data/cache"
CACHE_MAX_BARS = 10500              # ~14 thang H1 forex: du cho SMA200 ngay (A), z 120 ngay (D), BB 4000 nen
BOOT_PAGES = 2                      # lan dau: 2 trang x 5000 nen H1 moi ma
STATE_FILE = os.environ.get("LIVE_STATE_FILE") or "data/live_state.json"

# ------------------------------------------------------------------ canh bao doi SL
SL_MOVE_MIN_R = {"B": 0.10, "C": 0.10, "BB BTC": 0.5, "BB ETH": 0.5, "BB SOL": 0.5,
                 "AQB BTC": 0.5, "AQB ETH": 0.5, "AQB SOL": 0.5, "AQB DOGE": 0.5, "AQB XAU": 0.5}     # chi bao doi SL khi dich >= x lan rui ro ban dau
SL_MOVE_MIN_HOURS = {"B": 0, "C": 0, "BB BTC": 4, "BB ETH": 4, "BB SOL": 4,
                     "AQB BTC": 4, "AQB ETH": 4, "AQB SOL": 4, "AQB DOGE": 4, "AQB XAU": 4}          # va cach lan bao truoc it nhat x gio

# ------------------------------------------------------------------ spread dien hinh (% gia)
# Twelve Data khong co spread -> dung trung vi 2025-2026 tu du lieu MT5 da backtest. Doi theo san cua ban neu khac nhieu.
SPREAD_PCT = {"AUDJPY": 0.0074, "AUDUSD": 0.0151, "BTCUSD": 0.0646, "CADCHF": 0.0278, "CADJPY": 0.0113, "CHFJPY": 0.0124,
              "ETHUSD": 0.195, "EURAUD": 0.0144, "EURCAD": 0.0136, "EURCHF": 0.0117, "EURGBP": 0.0093, "EURJPY": 0.0055,
              "EURNZD": 0.0216, "EURUSD": 0.0034, "GBPAUD": 0.0169, "GBPCAD": 0.0167, "GBPCHF": 0.018, "GBPJPY": 0.0093,
              "GBPNZD": 0.0253, "GBPUSD": 0.006, "NZDCAD": 0.0299, "NZDCHF": 0.0354, "NZDJPY": 0.0113, "NZDUSD": 0.0177,
              "USDCAD": 0.0094, "USDCHF": 0.0112, "USDJPY": 0.0034,
              "SOLUSD": 0.10, "DOGEUSD": 0.10, "XAUUSD": 0.017}   # SOL: uoc tinh (chua co du lieu spread san); chi phi BB toi thieu van la 0.20%

# ------------------------------------------------------------------ cong kiem soat (tran + ngat mach): xem portfolio_backtest.py
# MAX_OPEN_RISK, CRYPTO_MAX_OPEN, BREAK_SLEEVE_MONTH, BREAK_FLOAT, BREAK_DD dung chung voi backtest.
NOTIFY_SKIPPED = (os.environ.get("NOTIFY_SKIPPED") or "").strip().lower() in ("1", "true", "yes")   # bao ca tin hieu bi bo qua
