# -*- coding: utf-8 -*-
"""
FX_RANK_BOT.PY - bot bao lenh chien luoc "xep hang luc tien te" (danh hoi ve theo tuan), gui Telegram. CHI DUNG THU VIEN CO SAN.

Cong thuc (da kiem tra 2011-2026 tren 28 cap, tinh theo R, da tru spread, chua tinh swap):
  1. Luc 8 dong (USD EUR GBP JPY CHF CAD AUD NZD) tu gia ngay cua 7 cap voi USD, tong luc = 0.
     Diem = thay doi luc trong 120 phien.
  2. Moi thu Sau sau khi dong nen ngay: MUA 2 dong yeu nhat (khong mua JPY), BAN 2 dong manh nhat -> 4 cap.
  3. BO QUA TUAN neu do phan tan luc (do lech chuan diem cua 8 dong) thap hon muc phan vi 25% cua cac tuan truoc.
  4. TAM DUNG dong tien neu tong R cac lenh co dong do dong trong 13 tuan gan nhat <= -6R.
  5. Vao o gia mo cua thu Hai. SL = 1 ATR ngay (14). TP = 3 sigma (do lech chuan loi nhuan ngay 60 phien).
     Khoi luong = (von x % rui ro) / khoang cach SL.  1R = so tien mat khi cham SL.
  6. Thu Sau sau: cap van duoc chon thi giu nguyen (khong doi SL/TP); cap roi khoi danh sach -> dong o gia mo thu Hai.

Lich chay: moi ngay thu Ba -> thu Bay luc ~00:30 UTC (07:30 VN). Thu Bay: tinh tin hieu tuan moi.
Bien moi truong (GitHub Secrets):
  TWELVE_DATA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (bat buoc)
  ACCOUNT_EQUITY   von tai khoan FX bang USD (de tinh lot), mac dinh 10000
  RISK_PCT         % rui ro moi lenh, mac dinh 0.5
  STATE_FILE       mac dinh data/fx_rank_state.json
Chay tay:  python fx_rank_bot.py [--khong-gui] [--tuan]   (--tuan: ep tinh tin hieu tuan ngay ca khi khong phai thu Bay)
"""
import json, math, os, sys, time, urllib.request, urllib.parse, urllib.error, datetime as dt

# ============================== CAU HINH ==============================
TD_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "")
ACCOUNT_EQUITY = float(os.environ.get("ACCOUNT_EQUITY", "10000") or 10000)
RISK_PCT = float(os.environ.get("RISK_PCT", "0.5") or 0.5)
STATE_FILE = os.environ.get("STATE_FILE", "data/fx_rank_state.json")
CCYS = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"]
USD_PAIRS = ["EUR/USD", "GBP/USD", "AUD/USD", "NZD/USD", "USD/JPY", "USD/CHF", "USD/CAD"]
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]          # quy uoc ten cap tren thi truong
LOOKBACK, N_SIDE, NO_BUY = 120, 2, {"JPY"}
SIGMA_WIN, TP_SIGMA, SL_ATR, ATR_N = 60, 3.0, 1.0, 14
DISP_Q, PAUSE_WEEKS, PAUSE_R = 0.25, 13, -6.0
HISTORY_DAYS = 1500
# ======================================================================

_credits = []                                                   # thoi diem cac luot goi (goi free: 8 luot/phut)


def td_series(symbols, outputsize):
    """Nen NGAY (UTC) da dong cua nhieu cap: {sym: [(ngay, o, h, l, c), ...] tang dan}."""
    if not symbols:
        return {}
    now = time.time()
    while _credits and now - _credits[0] > 61:
        _credits.pop(0)
    if len(_credits) + len(symbols) > 8:
        time.sleep(max(1, 62 - (now - _credits[0])))
        _credits.clear()
    q = urllib.parse.urlencode({"symbol": ",".join(symbols), "interval": "1day", "outputsize": outputsize,
                                "timezone": "UTC", "apikey": TD_KEY})
    raw = None
    for k in range(3):
        try:
            with urllib.request.urlopen("https://api.twelvedata.com/time_series?" + q, timeout=60) as r:
                raw = json.loads(r.read().decode()); break
        except Exception:
            time.sleep(5 + 5 * k)
    _credits.extend([time.time()] * len(symbols))
    if raw is None:
        raise RuntimeError("Khong goi duoc Twelve Data")
    if len(symbols) == 1:
        raw = {symbols[0]: raw}
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    out = {}
    for s in symbols:
        d = raw.get(s, {})
        if d.get("status") == "error" or "values" not in d:
            raise RuntimeError("Twelve Data loi voi %s: %s" % (s, d.get("message", d)))
        rows = []
        for v in d["values"]:
            day = v["datetime"][:10]
            if day >= today or dt.date.fromisoformat(day).weekday() >= 5:
                continue                                         # bo nen chua dong va nen cuoi tuan
            rows.append((day, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])))
        out[s] = sorted(rows)
    return out


def gui(text, send=True):
    print(text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")); print("-" * 40)
    if not send or not TG_TOKEN or not TG_CHAT:
        return
    data = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"}).encode()
    for _ in range(3):
        try:
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN, data=data, timeout=30); return
        except Exception:
            time.sleep(3)


# ------------------------------------------------------------------ tien ich cap tien
def ten_cap(a, b):
    """Ten cap tren thi truong cho (mua a / ban b) va chieu lenh tren cap do."""
    if ORDER.index(a) < ORDER.index(b):
        return "%s/%s" % (a, b), 1
    return "%s/%s" % (b, a), -1


def pip(sym):
    return 0.01 if sym.endswith("JPY") else 0.0001


def usd_per(ccy, last_usd):
    """1 don vi ccy = ? USD, tu gia dong cua gan nhat cua cac cap voi USD."""
    if ccy == "USD":
        return 1.0
    if ccy + "/USD" in last_usd:
        return last_usd[ccy + "/USD"]
    return 1.0 / last_usd["USD/" + ccy]


def atr_sigma(bars):
    trs, prev = [], None
    for _, o, h, l, c in bars:
        trs.append(h - l if prev is None else max(h - l, abs(h - prev), abs(l - prev))); prev = c
    a = trs[0]
    for x in trs[1:]:
        a += (x - a) / ATR_N                                     # ATR kieu Wilder
    lr = [100 * math.log(bars[i][4] / bars[i - 1][4]) for i in range(1, len(bars))][-SIGMA_WIN:]
    m = sum(lr) / len(lr)
    sd = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1))
    return a, sd


# ------------------------------------------------------------------ luc tien te
def tinh_luc(usd):
    """Tra ve (ngay[], diem[ngay][8]) voi diem = thay doi luc 120 phien (tong luc = 0)."""
    days = sorted(set.intersection(*[set(d for d, *_ in usd[s]) for s in USD_PAIRS]))
    px = {s: {d: c for d, o, h, l, c in usd[s]} for s in USD_PAIRS}
    S = []
    for d in days:
        v = []
        for c in CCYS:
            if c == "USD":
                v.append(0.0)
            elif c + "/USD" in px:
                v.append(math.log(px[c + "/USD"][d]))
            else:
                v.append(-math.log(px["USD/" + c][d]))
        m = sum(v) / 8
        S.append([100 * (x - m) for x in v])
    sig = [[S[i][k] - S[i - LOOKBACK][k] for k in range(8)] if i >= LOOKBACK else None for i in range(len(days))]
    return days, sig


def phan_tan(x):
    m = sum(x) / len(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def phan_vi(xs, q):
    s = sorted(xs); k = (len(s) - 1) * q; f = int(k)
    return s[f] + (s[min(f + 1, len(s) - 1)] - s[f]) * (k - f)


# ------------------------------------------------------------------ trang thai
def doc():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"positions": [], "closed": [], "last_signal": None, "last_bar": ""}


def luu(st):
    st["closed"] = st["closed"][-400:]
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def fmt(x, sym):
    return ("%.3f" if sym.endswith("JPY") else "%.5f") % x


def lot(sl_dist, sym, last_usd):
    risk_usd = ACCOUNT_EQUITY * RISK_PCT / 100
    usd_per_pip_lot = 100000 * pip(sym) * usd_per(sym[4:], last_usd)
    return risk_usd / (sl_dist / pip(sym) * usd_per_pip_lot), risk_usd


# ------------------------------------------------------------------ xu ly hang ngay
def cap_nhat_lenh(st, bars, tin):
    """Gan gia vao (mo cua thu Hai), kiem tra SL/TP theo nen ngay, dong lenh cho dong."""
    for p in list(st["positions"]):
        b = [x for x in bars.get(p["pair"], []) if x[0] > p["signal_date"]]
        if not b:
            continue
        if p["status"] == "cho_dong":                           # dong o gia mo phien dau tuan
            px = b[0][1]; r = p["side"] * (px - p["entry"]) / p["sl_dist"]
            st["closed"].append(dict(pair=p["pair"], side=p["side"], ccys=p["ccys"], entry_date=p["entry_date"], exit_date=b[0][0], R=round(r, 2), ly_do="het tuan"))
            st["positions"].remove(p)
            tin.append("⚪ <b>ĐÃ ĐÓNG %s</b> (rời danh sách tuần) ở giá mở %s · %+.2fR" % (p["pair"], fmt(px, p["pair"]), r)); continue
        if p["status"] == "cho_vao":
            e = b[0][1]; p["entry"], p["entry_date"], p["status"] = e, b[0][0], "mo"
            p["sl"] = e - p["side"] * p["sl_dist"]; p["tp"] = e * math.exp(p["side"] * p["tp_sigma"] / 100)
            tin.append("📌 <b>%s %s</b> đã vào ở giá mở %s (%s) · SL %s · TP %s\n<i>Nếu giá khớp thực tế khác, giữ nguyên khoảng cách SL %d pip, TP %d pip.</i>" % (
                "MUA" if p["side"] == 1 else "BÁN", p["pair"], fmt(e, p["pair"]), b[0][0], fmt(p["sl"], p["pair"]), fmt(p["tp"], p["pair"]),
                round(p["sl_dist"] / pip(p["pair"])), round(abs(p["tp"] - e) / pip(p["pair"]))))
        for day, o, h, l, c in [x for x in b if x[0] >= p["entry_date"] and x[0] > p.get("checked", "")]:
            hit_sl = (p["side"] == 1 and l <= p["sl"]) or (p["side"] == -1 and h >= p["sl"])
            hit_tp = (p["side"] == 1 and h >= p["tp"]) or (p["side"] == -1 and l <= p["tp"])
            if hit_sl or hit_tp:                                    # cung ngay ca hai -> tinh SL (than trong)
                px = p["sl"] if hit_sl else p["tp"]; r = p["side"] * (px - p["entry"]) / p["sl_dist"]
                st["closed"].append(dict(pair=p["pair"], side=p["side"], ccys=p["ccys"], entry_date=p["entry_date"], exit_date=day, R=round(r, 2), ly_do="SL" if hit_sl else "TP"))
                st["positions"].remove(p)
                tin.append("%s <b>%s %s chạm %s</b> ngày %s · %+.2fR" % ("🔴" if hit_sl else "🟢", "MUA" if p["side"] == 1 else "BÁN", p["pair"], "SL" if hit_sl else "TP", day, r))
                break
            p["checked"] = day


def tin_hieu_tuan(st, tin, last_usd_cache):
    usd = td_series(USD_PAIRS, HISTORY_DAYS)
    last_usd = {s: usd[s][-1][4] for s in USD_PAIRS}; last_usd_cache.update(last_usd)
    days, sig = tinh_luc(usd)
    fri = [i for i, d in enumerate(days) if dt.date.fromisoformat(d).weekday() == 4 and sig[i] is not None]
    i = fri[-1]; d0 = days[i]; s = sig[i]
    disp = phan_tan(s); hist = [phan_tan(sig[j]) for j in fri[:-1]]
    thr = phan_vi(hist, DISP_Q) if len(hist) >= 52 else None
    order = sorted(range(8), key=lambda k: s[k])                  # diem thap = yeu = mua
    buys = [k for k in order if CCYS[k] not in NO_BUY][:N_SIDE]
    sells = [k for k in reversed(order) if k not in buys][:N_SIDE]
    cutoff = (dt.date.fromisoformat(d0) - dt.timedelta(weeks=PAUSE_WEEKS)).isoformat()
    paused = {c for c in CCYS if sum(x["R"] for x in st["closed"] if x["exit_date"] > cutoff and c in x["ccys"]) <= PAUSE_R}
    bo_tuan = thr is not None and disp < thr
    plan = []
    if not bo_tuan:
        for x in buys:
            for y in sells:
                a, b = CCYS[x], CCYS[y]
                if a in paused or b in paused:
                    continue
                sym, side = ten_cap(a, b); plan.append((sym, side, [a, b]))
    keep = {(p["pair"], p["side"]) for p in st["positions"] if p["status"] in ("mo", "cho_vao")}
    want = {(sym, side) for sym, side, _ in plan}
    for p in st["positions"]:
        if p["status"] in ("mo", "cho_vao") and (p["pair"], p["side"]) not in want:
            if p["status"] == "cho_vao":
                p["status"] = "huy"
            else:
                p["status"], p["signal_date"] = "cho_dong", d0
    st["positions"] = [p for p in st["positions"] if p["status"] != "huy"]
    new = [(sym, side, cc) for sym, side, cc in plan if (sym, side) not in keep]
    pb = td_series([sym for sym, _, _ in new], 100) if new else {}
    lines = []
    for sym, side, cc in new:
        a, sd = atr_sigma(pb[sym][-80:]); slp = SL_ATR * a; ref = pb[sym][-1][4]
        lots, risk_usd = lot(slp, sym, last_usd)
        st["positions"].append(dict(pair=sym, side=side, ccys=cc, signal_date=d0, status="cho_vao", sl_dist=slp, tp_sigma=TP_SIGMA * sd,
                                    entry=None, entry_date="", sl=None, tp=None, lots=round(lots, 2)))
        tpd = ref * (math.exp(TP_SIGMA * sd / 100) - 1)
        lines.append("%s <b>%s %s</b> · %.2f lot\n   SL %d pip (1 ATR ngày) · TP %d pip (3σ) · RR 1:%.1f\n   <i>Tham khảo theo giá đóng cửa thứ Sáu %s: SL %s · TP %s</i>" % (
            "🟢" if side == 1 else "🔴", "MUA" if side == 1 else "BÁN", sym, lots, round(slp / pip(sym)), round(tpd / pip(sym)), tpd / slp,
            fmt(ref, sym), fmt(ref - side * slp, sym), fmt(ref + side * tpd, sym)))
    giu = [p["pair"] + (" MUA" if p["side"] == 1 else " BÁN") for p in st["positions"] if p["status"] in ("mo", "cho_vao") and (p["pair"], p["side"]) in keep]
    dong = [p["pair"] for p in st["positions"] if p["status"] == "cho_dong"]
    rank = "  ".join("%s %+.1f" % (CCYS[k], s[k]) for k in order)
    head = "📅 <b>TÍN HIỆU TUẦN</b> (dữ liệu đến thứ Sáu %s)\nLực 120 phiên (yếu → mạnh): %s\nĐộ phân tán %.2f%s" % (
        d0, rank, disp, (" · ngưỡng %.2f" % thr) if thr is not None else "")
    if bo_tuan:
        head += "\n⏸ <b>BỎ TUẦN NÀY</b>: tín hiệu yếu (độ phân tán thấp hơn ngưỡng). Không vào lệnh mới."
    if paused:
        head += "\n⏸ Tạm dừng đồng: <b>%s</b> (13 tuần gần nhất ≤ %gR)" % (", ".join(sorted(paused)), PAUSE_R)
    body = "\n\n<b>VÀO LỆNH khi thị trường mở (thứ Hai)</b> — rủi ro %.2g%% = %s USD/lệnh:\n%s" % (RISK_PCT, format(round(ACCOUNT_EQUITY * RISK_PCT / 100), ","), "\n".join(lines)) if lines else ""
    if giu:
        body += "\n\n<b>Giữ nguyên</b> (vẫn trong danh sách, không đổi SL/TP): " + ", ".join(giu)
    if dong:
        body += "\n\n<b>ĐÓNG khi thị trường mở (thứ Hai)</b>: " + ", ".join(dong)
    if not lines and not giu and not dong:
        body += "\n\nKhông có lệnh tuần này."
    tin.append(head + body)
    st["last_signal"] = dict(ngay=d0, xep_hang={CCYS[k]: round(s[k], 2) for k in range(8)}, phan_tan=round(disp, 3),
                             nguong=round(thr, 3) if thr is not None else None, bo_tuan=bo_tuan, tam_dung=sorted(paused),
                             mua=[CCYS[k] for k in buys], ban=[CCYS[k] for k in sells])


def chay(send=True, ep_tuan=False):
    st = doc(); tin = []
    today = dt.datetime.now(dt.timezone.utc).date()
    need = sorted({p["pair"] for p in st["positions"]})
    bars = td_series(need, 15) if need else {}
    cap_nhat_lenh(st, bars, tin)
    last_usd = {}
    if today.weekday() == 5 or ep_tuan:
        tin_hieu_tuan(st, tin, last_usd)
    # tom tat
    op = [p for p in st["positions"] if p["status"] == "mo"]
    if op or today.weekday() == 5 or tin:
        cut = (today - dt.timedelta(weeks=PAUSE_WEEKS)).isoformat()
        r13 = sum(x["R"] for x in st["closed"] if x["exit_date"] > cut)
        dong = []
        for p in op:
            b = bars.get(p["pair"])
            now = (" · tạm tính %+.2fR" % (p["side"] * (b[-1][4] - p["entry"]) / p["sl_dist"])) if b else ""
            dong.append("• %s %s từ %s%s" % ("MUA" if p["side"] == 1 else "BÁN", p["pair"], p["entry_date"], now))
        tin.append("📋 <b>FX tóm tắt %s</b>\nĐang mở %d lệnh%s\n%s\nKết quả 13 tuần gần nhất: %+.1fR · rủi ro mỗi lệnh %.2g%% vốn" % (
            today.isoformat(), len(op), ":" if op else "", "\n".join(dong) or "(không có)", r13, RISK_PCT))
    st["last_run"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    luu(st)
    for t in tin:
        gui(t, send)


if __name__ == "__main__":
    try:
        chay(send="--khong-gui" not in sys.argv, ep_tuan="--tuan" in sys.argv)
    except Exception as e:
        gui("⚠️ <b>Bot FX lỗi</b>: %s" % e, "--khong-gui" not in sys.argv)
        raise
