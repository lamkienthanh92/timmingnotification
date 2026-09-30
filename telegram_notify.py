"""
Gui tin nhan Telegram.
Can 2 bien moi truong (dat trong GitHub Secrets):
  TELEGRAM_BOT_TOKEN  - token bot lay tu @BotFather
  TELEGRAM_CHAT_ID    - chat id cua ban (xem README de lay)
Neu chua cau hinh, tin nhan chi duoc in ra log (khong loi).
"""
import os
import requests

MAX_LEN = 3900  # Telegram gioi han 4096 ky tu/tin, chua du phong


def _chunks(text: str):
    lines, buf = text.split("\n"), ""
    for ln in lines:
        if len(buf) + len(ln) + 1 > MAX_LEN and buf:
            yield buf
            buf = ""
        buf += ln + "\n"
    if buf.strip():
        yield buf


def send(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[Telegram chua cau hinh - chi in ra log]\n" + text)
        return False
    ok = True
    for chunk in _chunks(text):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat_id, "text": chunk,
                                    "disable_web_page_preview": True},
                              timeout=15)
            if not r.ok:
                ok = False
                print("Loi gui Telegram:", r.status_code, r.text[:200])
        except requests.RequestException as e:
            ok = False
            print("Loi ket noi Telegram:", e)
    return ok
