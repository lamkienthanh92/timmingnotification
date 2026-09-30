# Bot theo dõi lệnh WPR(14)+EMA(5) — Telegram + app điện thoại

Bot chạy mỗi giờ trên GitHub Actions, lấy giá từ Twelve Data, phát hiện vào/thoát lệnh của cả 60 leg,
tính ngắt mạch (floating < -4% → nghỉ 45 ngày), gửi Telegram và lưu trạng thái cho app React trên Netlify.

**Bot không đặt lệnh.** Khi nhận tin "VÀO", bạn tự vào lệnh và **đặt SL trên sàn ngay**. Bot chỉ báo thoát
theo WPR và hết giờ — bot có trễ hay lỗi thì lệnh vẫn được SL bảo vệ.

## Đã kiểm chứng

Phát lại dữ liệu lịch sử từng giờ một như bot chạy thật, so với backtest:
- 197/197 lệnh khớp, giá vào và giá thoát trùng khớp tuyệt đối
- Floating cuối ngày khớp backtest (sai lệch tối đa 0.0005%); ngắt mạch kích hoạt đúng ngày 01/07/2024 (-5.06%)
- Chạy trùng 2 lần trong 1 giờ không báo lặp; hết hạn mức API thì báo 1 lần và tự chạy lại khi có hạn mức
- Trung bình ~210 lần gọi Twelve Data/ngày (chỉ lấy cặp cần thiết từng giờ)

## Cài đặt (làm 1 lần)

### 1. Telegram
1. Nhắn `@BotFather` → `/newbot` → đặt tên → nhận **token**.
2. Nhắn 1 tin bất kỳ cho bot vừa tạo.
3. Mở `https://api.telegram.org/bot<TOKEN>/getUpdates` → tìm `"chat":{"id": ...}` → đó là **chat ID**.

### 2. GitHub
1. Đẩy toàn bộ thư mục này lên 1 repo.
2. Repo → Settings → Secrets and variables → Actions → **Secrets**, thêm:
   - `TWELVE_DATA_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
3. (Tùy chọn) tab **Variables**: `NOTIFY_ONLY_LEGS` = danh sách leg bạn thực sự trade, cách nhau dấu phẩy,
   vd `H1_XAUUSD_Long,H4DOM_EURUSD_Long`. Bot vẫn theo dõi đủ 60 leg để tính ngắt mạch, chỉ lọc tin nhắn.
4. Tab Actions → **Live bot (moi gio)** → **Run workflow** để chạy thử. Lần đầu bot "khởi động": tải ~10 ngày
   gần nhất để biết lệnh nào đang mở (~6 phút), rồi gửi tin "Bot đã khởi động".

### 3. Hẹn giờ chính xác bằng cron-job.org
GitHub tự hẹn giờ hay trễ 5–20 phút, không hợp lệnh H1. Dùng cron-job.org gọi GitHub đúng phút :02.

1. GitHub → Settings (tài khoản) → Developer settings → Fine-grained tokens → Generate:
   chỉ chọn repo này, quyền **Actions: Read and write**.
2. cron-job.org → Create cronjob:
   - URL: `https://api.github.com/repos/<user>/<repo>/actions/workflows/live-bot.yml/dispatches`
   - Schedule: mỗi giờ, phút **2** (múi giờ bất kỳ, chỉ cần phút 2)
   - Advanced → Request method **POST**, headers:
     `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
   - Request body: `{"ref":"main"}`
   - GitHub trả về **204** là thành công.

Workflow còn lịch dự phòng mỗi 2 giờ phòng khi cron-job.org lỗi; chạy trùng không sao.

### 4. App trên Netlify
1. Netlify → Add new site → Import repo (đã có sẵn `netlify.toml`).
2. Site configuration → Environment variables:
   - `GITHUB_REPO` = `user/repo`
   - `GITHUB_TOKEN_READ` = fine-grained token chỉ quyền **Contents: Read-only** (bắt buộc nếu repo private)
   - `GITHUB_BRANCH` = `main` (nếu khác)
3. Deploy. Trên điện thoại: mở trang → Chia sẻ → **Thêm vào Màn hình chính**.

Bot commit trạng thái kèm `[skip netlify]` nên web không build lại mỗi giờ; app đọc trạng thái mới nhất qua
Netlify Function, tự tải lại mỗi phút.

## Tin nhắn nhận được

```
🟢 VÀO LONG · H1 · USDJPY
Giá: 150.335 | SL: 147.866 (1.64%)
Thoát khi WPR > -20 hoặc sau 96 nến H1

✅ THOÁT SHORT · 4H-Thứ · EURGBP
Lý do: WPR | Giá: 0.8412
Kết quả: +0.45% giá (+0.36R) | Vào 26/06 07:00

⛔ NGẮT MẠCH: floating ngày 01/07 = -5.06% (< -4.0%)
Không vào lệnh mới đến hết 15/08/2024. Lệnh đang mở vẫn giữ theo quy tắc thoát.
```
Kèm 1 tin tóm tắt mỗi sáng sau 5h: trạng thái ngắt mạch, lệnh đang mở, lịch H1 và 4H trong ngày.

## Thời điểm
- Tín hiệu H1 báo **khi nến giờ vào đóng** (vd leg giờ vào 3h → tin đến ~4h02).
- 4H: kiểm tra sau mỗi nến 4H đóng, trong đúng Thứ/Ngày quy định.
- Ngắt mạch: chấm floating ngày hôm trước lúc ~4h sáng (sau khi nến 4H cuối ngày đóng) — đúng cách backtest tính.

## Lưu ý quan trọng
- **Nến 4H của Twelve Data có thể bắt đầu ở mốc giờ khác dữ liệu đã dùng backtest** (tùy nguồn). Nếu lệch mốc,
  tín hiệu 4H sẽ không khớp 100% backtest. Nên so vài tuần đầu với chart sàn bạn giao dịch.
- Mốc giờ VN giả định dữ liệu trả về đúng UTC (`timezone=UTC`). Kiểm tra vài tin nhắn đầu với chart thật.
- Hạn mức: gói free Twelve Data thường 8 lần/phút, ~800/ngày — bot dùng ~210/ngày. Kiểm tra lại gói của bạn.
- GitHub Actions: repo public miễn phí không giới hạn; repo private có hạn mức phút/tháng — mỗi lần chạy ~1–2 phút,
  khoảng 36 lần/ngày, nên theo dõi mục Billing tháng đầu.
- Muốn khởi động lại từ đầu: xóa `data/live_state.json` trong repo, lần chạy sau bot tự tái dựng.

## Cấu trúc
| File | Vai trò |
|---|---|
| `live_bot.py` | Bot chính (chạy mỗi giờ) |
| `telegram_notify.py` | Gửi Telegram |
| `config.py` | Tham số 60 leg, risk, ngắt mạch — giống hệt backtest |
| `indicators.py`, `twelvedata_client.py` | Chỉ báo và lấy dữ liệu (tôn trọng giới hạn 8 lần/phút) |
| `.github/workflows/live-bot.yml` | Lịch chạy và lưu trạng thái |
| `dashboard/` | App React + Netlify Function `state` |
| `daily_check.py`, `simulate_full_system.py`, `main.py`… | Bản cũ, giữ để tham khảo, không cần dùng nữa |
