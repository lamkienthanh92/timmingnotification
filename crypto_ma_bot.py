# -*- coding: utf-8 -*-
"""
CRYPTO_MA_BOT.PY - bot bao lenh chien luoc crypto Spot "Top 10 + MA10/MA30", gui Telegram. CHI DUNG THU VIEN CO SAN.

Chien luoc (da kiem tra tren du lieu day du 2020-2026, ke ca coin da chet):
  - Danh muc: top 10 coin theo gia tri giao dich TB 60 ngay tren Binance (cap USDT, bo stablecoin), chon lai dau moi thang.
  - MUA : gia dong cua ngay CAT LEN MA10 (va dang tren MA30), coin nam trong top 10 thang nay -> mua 1/10 tong tai san.
  - BAN : gia dong cua ngay DUOI MA30 -> ban.  Coin roi khoi top 10 van giu den khi co tin hieu ban.
  Nen ngay dong luc 00:00 UTC (07:00 VN). Chay bot moi ngay sau gio do.

Cau hinh bang bien moi truong (GitHub Secrets) hoac sua truc tiep ben duoi:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   - bat buoc de gui tin (khong co thi chi in ra man hinh)
  TONG_TAI_SAN                           - tuy chon, tong tai san (VND) de bot tinh so tien moi lenh
  STATE_FILE                             - tuy chon, noi luu trang thai (mac dinh crypto_ma_state.json canh file nay)
  LOAI_TRU                               - tuy chon, cac ma muon bo qua, vd "SNDKB,TSLAB" (token co phieu...)
Chay:  python crypto_ma_bot.py           (them --khong-gui de chi in, khong gui Telegram)
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error, datetime as dt

# ============================ CAU HINH ============================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TONG_TAI_SAN = float(os.environ.get("TONG_TAI_SAN", "0") or 0)       # VND; 0 = khong tinh so tien
TOPN = 10
MA_VAO, MA_RA = 10, 30
SO_NGAY_THANH_KHOAN = 60
SO_CAP_SO_LOAI = 40                       # lay 40 cap co gia tri giao dich 24h lon nhat roi moi tinh TB 60 ngay
# Ma muon loai them (vd token co phieu, coin ban khong muon giao dich), phan cach bang dau phay. Vd: LOAI_TRU="SNDKB,TSLAB"
LOAI_TRU = {x.strip().upper() for x in os.environ.get("LOAI_TRU", "").split(",") if x.strip()}
try:
    GOC = os.path.dirname(os.path.abspath(__file__))
except NameError:
    GOC = os.getcwd()
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(GOC, "crypto_ma_state.json"))
API = ["https://data-api.binance.vision", "https://api.binance.com", "https://api1.binance.com", "https://api3.binance.com"]
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "DAI", "USDP", "PAX", "USDS", "USDSB", "SUSD", "UST", "USTC", "EUR", "GBP", "AUD",
          "BRL", "TRY", "RUB", "IDRT", "BIDR", "NGN", "UAH", "ZAR", "BKRW", "BVND", "AEUR", "EURI", "XUSD", "USD1", "RLUSD",
          "PYUSD", "USDE", "PAXG", "XAUT", "WBTC", "BETH", "WBETH", "BFUSD", "USDD", "FRAX", "GYEN", "VAI", "JPY", "ARS",
          "COP", "MXN", "PLN", "RON", "CZK", "BNSOL", "USDQ", "XAUM"}
# ==================================================================


def http_json(path, params=None, tries=3):
    """Goi API du lieu thi truong cong khai cua Binance, thu lan luot cac dia chi du phong."""
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    loi = ""
    for base in API:
        for k in range(tries):
            try:
                req = urllib.request.Request(base + path + q, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                loi = "%s HTTP %s" % (base, e.code)
                if e.code in (400, 404, 451, 403):
                    break                                         # bi chan / sai ma -> thu dia chi khac
                time.sleep(2 + k)
            except Exception as e:
                loi = "%s %s" % (base, e); time.sleep(2 + k)
    raise RuntimeError("Khong lay duoc du lieu Binance: " + loi)


def gui_telegram(text, gui=True):
    print(text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")); print("-" * 40)
    if not gui or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    for k in range(3):
        try:
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % TELEGRAM_BOT_TOKEN, data=data, timeout=30)
            return
        except Exception:
            time.sleep(3)


def nen_ngay(symbol, limit=120):
    """Tra ve list (ngay, open, high, low, close, gia tri giao dich USDT) cua cac nen NGAY DA DONG."""
    raw = http_json("/api/v3/klines", {"symbol": symbol, "interval": "1d", "limit": limit + 1})
    now_ms = int(time.time() * 1000)
    out = []
    for k in raw:
        if int(k[6]) >= now_ms:                                   # nen chua dong -> bo
            continue
        d = dt.datetime.fromtimestamp(int(k[0]) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        out.append((d, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[7])))
    return out[-limit:]


def ma(xs, n, lui=0):
    v = xs[len(xs) - n - lui:len(xs) - lui] if lui else xs[-n:]
    return sum(v) / n if len(v) == n else None


def la_coin_hop_le(sym):
    if not sym.endswith("USDT"):
        return False
    base = sym[:-4]
    if base in STABLE or base in LOAI_TRU:
        return False
    for suf in ("UP", "DOWN", "BULL", "BEAR"):
        if base.endswith(suf) and len(base) > len(suf) + 1:
            return False
    return True


def chon_top10():
    """Top 10 theo gia tri giao dich TB 60 ngay (chi tinh nen da dong)."""
    info = http_json("/api/v3/exchangeInfo", {"permissions": "SPOT"})
    dang_gd = {s["symbol"] for s in info["symbols"] if s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"}
    tick = http_json("/api/v3/ticker/24hr")
    ung = sorted((t for t in tick if t["symbol"] in dang_gd and la_coin_hop_le(t["symbol"])),
                 key=lambda t: -float(t["quoteVolume"]))[:SO_CAP_SO_LOAI]
    diem = []
    for t in ung:
        k = nen_ngay(t["symbol"], SO_NGAY_THANH_KHOAN)
        if len(k) >= 30:
            diem.append((sum(x[5] for x in k) / len(k), t["symbol"][:-4]))
    diem.sort(reverse=True)
    return [c for _, c in diem[:TOPN]], {c: v for v, c in diem[:TOPN]}


def doc_trang_thai():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"thang": "", "top10": [], "dang_giu": {}, "lich_su": [], "ngay_xu_ly": ""}


def luu_trang_thai(st):
    st["lich_su"] = st["lich_su"][-500:]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def fmt_gia(x):
    return ("%.2f" % x) if x >= 100 else ("%.4f" % x) if x >= 1 else ("%.6g" % x)


def tien(v):
    return format(int(round(v, -3)), ",").replace(",", ".") + " đ"


def chay(gui=True):
    st = doc_trang_thai()
    hom_nay = dt.datetime.now(dt.timezone.utc).date()
    ngay_nen = (hom_nay - dt.timedelta(days=1)).isoformat()            # nen ngay vua dong
    if st.get("ngay_xu_ly") == ngay_nen:
        print("Da xu ly nen ngay", ngay_nen, "- bo qua."); return
    thang = hom_nay.strftime("%Y-%m")
    tin = []
    # ---- 1. Dau thang: chon lai top 10
    if st.get("thang") != thang or not st.get("top10"):
        top, gtgd = chon_top10()
        cu = set(st.get("top10", []))
        st["thang"], st["top10"] = thang, top
        dong = "\n".join("%2d. <b>%s</b> · %s triệu USD/ngày%s" % (i + 1, c, format(int(gtgd[c] / 1e6), ","),
                         "" if not cu or c in cu else " · <i>mới</i>") for i, c in enumerate(top))
        roi = [c for c in cu if c not in top]
        tin.append("📅 <b>TOP 10 THÁNG %s</b> (giá trị giao dịch TB 60 ngày)\n%s%s" % (
            hom_nay.strftime("%m/%Y"), dong, ("\n<i>Rời top 10: %s — không mua mới, lệnh đang giữ vẫn theo tín hiệu bán.</i>" % ", ".join(roi)) if roi else ""))
    # ---- 2. Tin hieu tung coin
    can_xet = list(dict.fromkeys(st["top10"] + list(st["dang_giu"].keys())))
    gia = {}
    for c in can_xet:
        try:
            k = nen_ngay(c + "USDT", MA_RA + 5)
        except RuntimeError:
            k = []
        if len(k) < MA_RA + 1 or k[-1][0] != ngay_nen:
            if c in st["dang_giu"]:
                tin.append("⚠️ <b>%s</b>: không lấy được nến ngày %s (có thể ngừng giao dịch). Kiểm tra trên sàn." % (c, ngay_nen))
            continue
        cl = [x[4] for x in k]
        gia[c] = dict(close=cl[-1], ma_vao=ma(cl, MA_VAO), ma_ra=ma(cl, MA_RA), ma_vao_truoc=ma(cl, MA_VAO, 1), close_truoc=cl[-2])
    mua, ban = [], []
    for c, g in gia.items():
        if c in st["dang_giu"]:
            if g["close"] < g["ma_ra"]:
                ban.append(c)
        elif c in st["top10"]:
            if g["close"] > g["ma_vao"] and g["close_truoc"] <= g["ma_vao_truoc"] and g["close"] >= g["ma_ra"]:
                mua.append(c)
    for c in ban:
        p = st["dang_giu"].pop(c); g = gia[c]; lai = g["close"] / p["gia_vao"] - 1
        st["lich_su"].append({"coin": c, "vao": p["ngay_vao"], "ra": ngay_nen, "gia_vao": p["gia_vao"], "gia_ra": g["close"], "lai_pct": round(lai * 100, 2)})
        tin.append("🔴 <b>BÁN %s</b> (Spot)\nGiá đóng cửa %s < MA30 %s\nBán giá thị trường sáng nay. Tạm tính %+.1f%% (mua %s ngày %s)." % (
            c, fmt_gia(g["close"]), fmt_gia(g["ma_ra"]), lai * 100, fmt_gia(p["gia_vao"]), p["ngay_vao"]))
    so_cho = TOPN - len(st["dang_giu"])
    for c in mua:
        g = gia[c]
        if so_cho <= 0:
            tin.append("⚪ <b>%s</b> có tín hiệu MUA nhưng đã đủ %d lệnh — bỏ qua." % (c, TOPN)); continue
        st["dang_giu"][c] = {"ngay_vao": hom_nay.isoformat(), "gia_vao": g["close"]}; so_cho -= 1
        so_tien = ("\nSố tiền: <b>%s</b> (1/10 tổng tài sản %s)" % (tien(TONG_TAI_SAN / TOPN), tien(TONG_TAI_SAN))) if TONG_TAI_SAN else \
                  "\nSố tiền: <b>1/10 tổng tài sản</b> (khai báo TONG_TAI_SAN để bot tính sẵn)"
        tin.append("🟢 <b>MUA %s</b> (Spot)\nGiá đóng cửa %s vừa cắt lên MA10 %s, trên MA30 %s\nMua giá thị trường sáng nay.%s\nThoát khi giá đóng cửa ngày xuống dưới MA30." % (
            c, fmt_gia(g["close"]), fmt_gia(g["ma_vao"]), fmt_gia(g["ma_ra"]), so_tien))
    # ---- 3. Tom tat
    dong = []
    for c, p in sorted(st["dang_giu"].items()):
        g = gia.get(c)
        if g:
            dong.append("• <b>%s</b> %+.1f%% · cách MA30 %+.1f%% · từ %s" % (c, (g["close"] / p["gia_vao"] - 1) * 100,
                        (g["close"] / g["ma_ra"] - 1) * 100, p["ngay_vao"]))
        else:
            dong.append("• <b>%s</b> (chưa có giá) · từ %s" % (c, p["ngay_vao"]))
    gan = sorted(((g["close"] / g["ma_vao"] - 1) * 100, c) for c, g in gia.items() if c in st["top10"] and c not in st["dang_giu"])
    tin.append("📋 <b>Tóm tắt nến ngày %s</b>\nĐang giữ %d/%d lệnh%s\n%s\nTop 10 tháng này: %s%s" % (
        ngay_nen, len(st["dang_giu"]), TOPN, ":" if dong else "", "\n".join(dong) or "(không có lệnh)",
        ", ".join(st["top10"]),
        ("\nGần tín hiệu mua (giá so với MA10): " + ", ".join("%s %+.1f%%" % (c, x) for x, c in gan[:4])) if gan else ""))
    st["ngay_xu_ly"] = ngay_nen
    luu_trang_thai(st)
    for t in tin:
        gui_telegram(t, gui)


if __name__ == "__main__":
    try:
        chay(gui="--khong-gui" not in sys.argv)
    except Exception as e:
        gui_telegram("⚠️ <b>Bot crypto lỗi</b>: %s" % e, "--khong-gui" not in sys.argv)
        raise
