"""
================================================================================
CAU HINH HE THONG - dung chung cho toan bo project
================================================================================
Copy nguyen tham so tu final_trading_system.py (ban backtest da kiem chung).
KHONG tu y doi so o day neu chua backtest lai.
================================================================================
"""
import os

# ------------------------------------------------------------------
# TWELVE DATA API
# ------------------------------------------------------------------
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "DAN_API_KEY_CUA_BAN_VAO_DAY")
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Twelve Data dung dinh dang "EUR/USD" cho forex, "BTC/USD" cho crypto.
# Map tu ten cap noi bo (khong co dau /) sang dinh dang Twelve Data.
SYMBOL_MAP = {
    "XAUUSD": "XAU/USD", "USDJPY": "USD/JPY", "GBPUSD": "GBP/USD",
    "AUDCHF": "AUD/CHF", "EURUSD": "EUR/USD", "EURCAD": "EUR/CAD",
    "USDCAD": "USD/CAD", "EURAUD": "EUR/AUD", "NZDJPY": "NZD/JPY",
    "NZDCAD": "NZD/CAD", "GBPJPY": "GBP/JPY", "GBPCHF": "GBP/CHF",
    "EURNZD": "EUR/NZD", "EURJPY": "EUR/JPY", "EURGBP": "EUR/GBP",
    "EURCHF": "EUR/CHF", "CHFJPY": "CHF/JPY", "CADCHF": "CAD/CHF",
    "AUDUSD": "AUD/USD", "AUDJPY": "AUD/JPY", "BTCUSD": "BTC/USD",
    "AUDCAD": "AUD/CAD", "GBPAUD": "GBP/AUD", "USDCHF": "USD/CHF",
}

# ------------------------------------------------------------------
# THAM SO CHI BAO & CHIEN LUOC (giu nguyen tu ban da kiem chung)
# ------------------------------------------------------------------
WPR_PERIOD = 14
EMA_SPAN = 5
ATR_PERIOD = 14
MAX_HOLD_H1 = 96          # gio
MAX_HOLD_H4 = 24          # nen H4 (=96h)
VN_OFFSET_HOURS = 7        # UTC+7 -- CAN XAC MINH LAI voi du lieu Twelve Data that
                            # (xem README.md muc "Canh bao mui gio")

CIRCUIT_BREAKER_TRIGGER = -4.0   # % floating loss se kich hoat ngat mach
CIRCUIT_BREAKER_PAUSE_DAYS = 45  # so ngay ngung vao lenh moi

RISK = {"H1": 0.30, "H4DOW": 0.5, "H4DOM": 1.0}

# ------------------------------------------------------------------
# TANG 1 - H1 (24 leg)
# ------------------------------------------------------------------
TANG1_H1 = [
    # pair, direction, window(start,end), entry_hour, threshold, exclude_dow, atr_mult
    ("XAUUSD","Long",(2,4),3,-70,5,6), ("USDJPY","Long",(10,12),11,-70,None,8),
    ("GBPUSD","Long",(18,20),19,-70,3,8),
    ("EURUSD","Long",(14,16),15,-70,3,8), ("EURUSD","Short",(13,15),14,-30,None,10),
    ("EURCAD","Long",(0,4),3,-70,None,8), ("USDCAD","Long",(15,17),16,-70,None,8),
    ("EURAUD","Long",(18,20),19,-70,None,8), ("NZDJPY","Long",(2,4),3,-70,None,8),
    ("NZDCAD","Short",(1,3),2,-40,4,8), ("GBPJPY","Long",(11,13),12,-70,3,8),
    ("GBPCHF","Long",(0,2),1,-70,3,6), ("GBPCHF","Short",(12,14),13,-30,None,10),
    ("EURNZD","Long",(0,4),3,-70,None,6), ("EURJPY","Long",(11,13),12,-70,None,10),
    ("EURGBP","Short",(6,8),7,-30,1,8),
    ("EURCHF","Long",(18,20),19,-60,None,6), ("EURCHF","Short",(18,20),19,-30,None,6),
    ("CHFJPY","Long",(3,5),4,-70,3,4), ("CADCHF","Long",(1,5),4,-70,4,8),
    ("CADCHF","Short",(1,3),2,-30,None,6), ("AUDUSD","Long",(6,8),7,-60,None,10),
    ("AUDUSD","Short",(9,11),10,-30,0,8), ("AUDJPY","Long",(15,17),16,-70,None,6),
]

# ------------------------------------------------------------------
# TANG 2 - H4 theo Thu trong tuan (16 leg)
# ------------------------------------------------------------------
TANG2_H4_DOW = [
    # pair, direction, dow(0=T2..6=CN), threshold, atr_mult
    ("AUDCAD","Long",5,-70,4), ("AUDCHF","Long",5,-70,4), ("AUDUSD","Long",5,-55,6),
    ("BTCUSD","Long",4,-85,6), ("CADCHF","Short",2,-15,4), ("EURGBP","Long",1,-85,4),
    ("EURGBP","Short",2,-15,6), ("EURJPY","Long",2,-85,4), ("EURUSD","Long",5,-55,6),
    ("EURUSD","Short",3,-15,6), ("GBPCHF","Long",5,-65,6), ("GBPJPY","Short",1,-15,6),
    ("NZDCAD","Long",5,-75,4), ("NZDCAD","Short",5,-25,4), ("USDCAD","Long",3,-85,4),
    ("USDCHF","Short",2,-40,6),
]

# ------------------------------------------------------------------
# TANG 3 - H4 theo Ngay trong thang (20 leg)
# ------------------------------------------------------------------
TANG3_H4_DOM = [
    # pair, direction, day_of_month, threshold, atr_mult
    ("AUDCHF","Short",10,-15,4), ("AUDJPY","Long",11,-85,4), ("AUDUSD","Long",8,-85,4),
    ("AUDUSD","Short",29,-15,4), ("BTCUSD","Short",26,-15,6), ("CADCHF","Short",17,-15,4),
    ("EURAUD","Long",10,-85,4), ("EURAUD","Short",10,-15,4), ("EURGBP","Long",21,-85,4),
    ("EURGBP","Short",26,-15,4), ("EURJPY","Long",29,-85,4), ("EURUSD","Long",31,-85,4),
    ("GBPAUD","Long",14,-85,4), ("GBPAUD","Short",1,-15,4), ("NZDCAD","Long",7,-85,4),
    ("NZDJPY","Long",11,-85,6), ("USDCAD","Short",30,-15,4), ("USDCHF","Long",2,-85,4),
    ("USDCHF","Short",31,-15,4), ("USDJPY","Long",2,-85,4),
]

SPREAD_PCT_M15 = {
    "XAUUSD":0.0005,"USDJPY":0.0060,"GBPUSD":0.0091,"AUDCHF":0.0392,"EURUSD":0.0043,
    "EURCAD":0.0178,"USDCAD":0.0115,"EURAUD":0.0198,"NZDJPY":0.0210,"NZDCAD":0.0396,
    "GBPJPY":0.0161,"GBPCHF":0.0267,"EURNZD":0.0253,"EURJPY":0.0102,"EURGBP":0.0144,
    "EURCHF":0.0175,"CHFJPY":0.0211,"CADCHF":0.0383,"AUDUSD":0.0189,"AUDJPY":0.0139,
}
SPREAD_PCT_H4 = {
    "AUDCAD":0.0275,"AUDCHF":0.0324,"AUDJPY":0.0132,"AUDUSD":0.0150,"BTCUSD":0.6153,
    "CADCHF":0.0364,"CADJPY":0.0164,"EURAUD":0.0159,"EURGBP":0.0131,"EURJPY":0.0083,
    "EURUSD":0.0038,"GBPAUD":0.0209,"GBPCHF":0.0214,"GBPJPY":0.0137,"GBPUSD":0.0085,
    "NZDCAD":0.0399,"NZDJPY":0.0240,"USDCAD":0.0110,"USDCHF":0.0142,"USDJPY":0.0054,
}

STATE_FILE = "data/positions_state.json"
LOG_FILE = "data/trading_log.csv"
