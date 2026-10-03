# Bot theo dõi danh mục v4 — Telegram + app điện thoại

Bot chạy trên GitHub Actions, lấy giá H1 từ Twelve Data. Mỗi lần chạy, bot **chạy lại đúng engine backtest**
(`portfolio_backtest.py`) trên các nến đã đóng, so với lần chạy trước, rồi gửi Telegram khi có lệnh **VÀO**,
**DỜI SL**, **THOÁT** hoặc **ĐÃ CHỐT**. Trạng thái được lưu cho app React trên Netlify.

**Bot không đặt lệnh.** Bạn tự vào lệnh theo tin nhắn. Với B, C, E, BB: đặt SL trên sàn ngay khi vào, và dời SL
khi bot báo. Với A, D: hệ thống không có SL, bot báo khi nào cần đóng.

## Các thành phần

| | Thành phần | Khung | Vào lệnh | Thoát | Rủi ro/lệnh |
|---|---|---|---|---|---|
| A | Mua sau bán tháo (18 cặp không JPY) | Ngày + H1 | Thứ Hai 00:00 UTC | Giá đóng cửa ngày giao dịch thứ 8 | 0.25% vốn / 1 ATR ngày |
| B | Xu hướng yen yếu (7 cặp JPY) | 4H | Supertrend 4H đảo lên | SL kéo theo Supertrend | 0.25% |
| BB | Squeeze Bollinger BTC, ETH | H1 | Phá band sau squeeze | SL kéo theo band, tối đa 10 ngày | 0.5% |
| D | Đảo chiều sức mạnh đồng tiền (25 cặp) | Ngày | z tử ≥ 2 và z mẫu ≤ −2 (hoặc ngược lại) | Độ lệch về < 1 hoặc 60 ngày | 0.15% vốn / 1 ATR ngày |
| E | Lớp phụ 4H → 1H (25 cặp) | 4H + H1 | Supertrend 1H theo hướng về mean, RR 2–4 | SL / TP cố định | 0.10% |
| C | CUSUM short JPY (tùy chọn) | 4H | CUSUM báo giảm | SL 3 ATR kéo theo | 0.10% |

Mặc định bot theo dõi A, B, BB, D, E. Tham số chiến lược nằm trong `portfolio_backtest.py` — **dùng chung với
backtest**, đừng sửa nếu chưa backtest lại.

## Lịch lấy mẫu

Bot được gọi mỗi giờ (phút :02), nhưng chỉ lấy dữ liệu cần cho thành phần đến hạn:

| Giờ UTC | Giờ VN | Lấy dữ liệu | Tính |
|---|---|---|---|
| Mỗi giờ | Mỗi giờ | BTC, ETH + cặp forex đang trong bối cảnh E (thường 0–4 cặp) hoặc có lệnh E mở | BB, E |
| 00, 04, 08, 12, 16, 20 | 07, 11, 15, 19, 23, 03 | Cả 25 cặp forex (nến 4H vừa đóng) | B, E, C, A, D |
| 00:02 | 07:02 | (cùng lần 4H ở trên) | A, D chấm nến ngày hôm qua + tóm tắt buổi sáng |
| Thứ Sáu 22:02 | Thứ Bảy 05:02 | 25 cặp forex (nến cuối tuần) | Chốt tín hiệu A, D, B cho thứ Hai |
| Thứ Bảy, Chủ nhật | | Chỉ BTC, ETH | BB |

- **Hạn mức Twelve Data:** khoảng 190 lượt/ngày khi mô phỏng 19 ngày (gói free 800/ngày, 8/phút). Lần khởi
  động đầu tiên tốn 54 lượt (2 trang × 5000 nến mỗi mã). Lần 4H tốn 27 lượt, lần hằng giờ 2–6 lượt.
- **Thời gian chạy:** lần 4H khoảng 4–5 phút (27 mã × 7.8 giây giãn cách), lần hằng giờ khoảng 1 phút.
  Tổng khoảng 1.500 phút GitHub Actions/tháng: repo public miễn phí không giới hạn, repo private gói free có
  2.000 phút/tháng.
- **Bộ nhớ đệm nến H1** (`data/cache/`) lưu bằng GitHub Actions cache, không commit vào repo. Nếu cache mất
  (không dùng quá 7 ngày), bot tự tải lại.

## Cài đặt

### 1. Telegram
1. Nhắn `@BotFather` → `/newbot` → đặt tên → nhận **token**.
2. Nhắn 1 tin bất kỳ cho bot vừa tạo.
3. Mở `https://api.telegram.org/bot<TOKEN>/getUpdates` → tìm `"chat":{"id": ...}` → đó là **chat ID**.

### 2. GitHub
1. Đẩy toàn bộ thư mục này lên repo (thay bản cũ).
2. Settings → Secrets and variables → Actions → **Secrets**: `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`.
3. (Tùy chọn) tab **Variables**:
   - `PARTS` — thành phần theo dõi, mặc định `A,B,BB,D,E`. Thêm C: `A,B,BB,C,D,E`.
   - `NOTIFY_ONLY_PARTS` — chỉ nhắn Telegram cho các thành phần này, vd `B,D,BB`. Dashboard vẫn hiện đủ.
   - `B_FILTER` = `1` — B chỉ vào lệnh khi cú đảo chiều do JPY tự yếu.
4. Actions → **Live bot (moi gio)** → **Run workflow** để chạy thử. Lần đầu bot tải dữ liệu (~7 phút), dựng lại
   các lệnh đang mở và gửi tin "Bot danh mục v4 đã chạy".

Chuyển từ bản cũ: không cần làm gì thêm. Bot nhận ra `data/live_state.json` của chiến lược cũ và tự khởi động lại.

### 3. Hẹn giờ chính xác bằng cron-job.org
GitHub tự hẹn giờ hay trễ 5–20 phút, không hợp với lệnh H1. Dùng cron-job.org gọi GitHub đúng phút :02.
1. GitHub → Settings (tài khoản) → Developer settings → Fine-grained tokens → Generate: chỉ chọn repo này,
   quyền **Actions: Read and write**.
2. cron-job.org → Create cronjob:
   - URL: `https://api.github.com/repos/<user>/<repo>/actions/workflows/live-bot.yml/dispatches`
   - Schedule: mỗi giờ, phút **2**
   - Request method **POST**, headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`,
     `Content-Type: application/json`, body `{"ref":"main"}` → GitHub trả về **204** là thành công.

Workflow còn lịch dự phòng mỗi 2 giờ. Chạy trùng không sao: bot nhớ đã xử lý nến 4H và lần chốt tuần nào.

### 4. App trên Netlify
1. Netlify → Add new site → Import repo (có sẵn `netlify.toml`).
2. Environment variables: `GITHUB_REPO` = `user/repo`, `GITHUB_TOKEN_READ` = fine-grained token quyền
   **Contents: Read-only** (bắt buộc nếu repo private), `GITHUB_BRANCH` nếu khác `main`.
3. Deploy. Trên điện thoại: mở trang → Chia sẻ → **Thêm vào Màn hình chính**.

## Tin nhắn nhận được

```
🟢 VÀO · CHFJPY LONG · B · xu hướng JPY
Vào: giá mở 15:00 T5 01/10
SL ban đầu 188.491 · dời theo Supertrend 4H (bot báo)
Khối lượng: 0.25% vốn ứng với khoảng SL ≈ 1.402 (140 pip) (theo giá hiện tại)

↕️ DỜI SL · CHFJPY LONG · B · xu hướng JPY
188.491 → 189.102 · tạm tính +0.45R

🔴 VÀO · GBPCHF SHORT · D · đảo chiều sức mạnh
Vào: giá mở 07:00 T2 05/10 · không SL
Thoát khi bot báo (độ lệch z về dưới 1, tối đa 60 ngày giao dịch)
Khối lượng: 0.15% vốn ứng với 1 ATR ngày = 0.00590 (59 pip)

✅ ĐÃ CHỐT · AUDUSD LONG · E · lớp phụ 4H→1H
+2.64R (≈ +0.26% vốn) · chạm TP
```
Kèm tóm tắt mỗi sáng (07:00 VN): lệnh đang mở, R tạm tính, tín hiệu chờ, cặp E đang theo dõi, chỉ báo chế độ B,
số lượt API đã dùng.

## Kiểm chứng trước khi dùng

`simulate_live.py` phát lại dữ liệu CSV MT5 từng giờ một đúng như bot chạy thật (thay Twelve Data bằng nguồn giả
lập), in toàn bộ tin nhắn và đối chiếu với lệnh backtest:

```
python simulate_live.py --data ./mt5_csv --start "2026-09-14 00:02" --end "2026-10-02 14:02"
```

Kết quả mô phỏng 14/09 → 02/10/2026 (446 lần chạy, 25 cặp forex + BTC, ETH):
- **25/25 lệnh khớp chính xác với backtest** (cùng giờ vào, giá vào, giá ra, R), gồm 7 lệnh còn mở cuối kỳ.
- Mọi tin VÀO đến lúc :02 của đúng giờ vào lệnh; không có tin báo muộn, không báo trùng.
- Tin DỜI SL của BB được giới hạn: dịch ≥ 0.5R và cách lần báo trước ≥ 4 giờ (`SL_MOVE_MIN_R`,
  `SL_MOVE_MIN_HOURS` trong `config.py`). Nếu bạn để SL BB lỏng hơn giữa 2 lần báo, kết quả thật sẽ hơi khác backtest.

## Lưu ý quan trọng
- **Giá Twelve Data khác giá sàn của bạn một chút.** Tín hiệu sát ngưỡng (Supertrend, z = 2, RR 2–4) có thể lệch
  so với chart sàn. Nên so vài tuần đầu.
- **Spread:** Twelve Data không có spread, bot dùng spread điển hình 2025–2026 lấy từ dữ liệu MT5 đã backtest
  (`SPREAD_PCT` trong `config.py`). Sàn khác nhiều thì sửa bảng này.
- **Giờ vào lệnh:** tín hiệu báo sau khi nến đóng ~2–5 phút, bạn vào ở giá thị trường lúc đó (backtest dùng giá mở
  nến kế tiếp).
- **A và D không có SL** — đó là thiết kế của hệ thống (đã backtest). Khối lượng tính theo 1 ATR ngày.
- **Chỉ báo chế độ B** (tổng R 12 tháng của lệnh "JPY tự yếu") hiện trong tóm tắt sáng; âm kéo dài thì cân nhắc
  giảm khối lượng B.
- Muốn khởi động lại từ đầu: xóa `data/live_state.json` trong repo.

## Cấu trúc
| File | Vai trò |
|---|---|
| `live_bot.py` | Bot chính: lịch lấy mẫu, bộ nhớ đệm, chạy engine, so sánh, Telegram |
| `portfolio_backtest.py` | Engine chiến lược v4 — dùng chung cho backtest và bot |
| `config.py` | API, danh sách 27 mã, lịch lấy mẫu, spread, ngưỡng báo dời SL |
| `twelvedata_client.py` | Lấy dữ liệu Twelve Data (giãn cách 7.8 giây, phân trang khi khởi động) |
| `simulate_live.py` | Mô phỏng bot trên dữ liệu lịch sử để kiểm chứng |
| `.github/workflows/live-bot.yml` | Lịch chạy, cache nến H1, lưu trạng thái |
| `dashboard/` | App React + Netlify Function `state` |
