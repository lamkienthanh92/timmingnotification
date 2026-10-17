# Hệ thống báo lệnh bản 6: FX xếp hạng lực tiền tệ + Crypto Spot

Hai bot độc lập, chạy tự động trên GitHub Actions, gửi tin Telegram. Không cần cài thư viện Python nào.

## 1. Bot FX — xếp hạng lực tiền tệ (`fx_rank_bot.py`)

| | Quy tắc |
|---|---|
| Lực tiền tệ | 8 đồng (USD EUR GBP JPY CHF CAD AUD NZD) từ giá ngày của 7 cặp với USD; điểm = thay đổi lực 120 phiên |
| Chọn lệnh | Mỗi thứ Sáu: **mua 2 đồng yếu nhất** (không mua JPY), **bán 2 đồng mạnh nhất** → 4 cặp |
| Khuyến cáo bỏ tuần | Độ phân tán lực thấp hơn mức 25% của các tuần trước → vẫn gửi tín hiệu nhưng gắn nhãn ⚠️ **KHUYẾN CÁO BỎ** (backtest: lệnh các tuần này TB −0,04R so với +0,14R). Bot theo dõi riêng kết quả các lệnh này |
| Tạm dừng | Đồng tiền có tổng R 13 tuần gần nhất (chỉ tính tuần bình thường) ≤ −6R → bỏ các cặp có đồng đó |
| Vào / thoát | Vào giá mở thứ Hai · **SL 1 ATR ngày** · **TP 3σ** · cặp rời danh sách thì đóng giá mở thứ Hai |
| Khối lượng | (vốn × % rủi ro) ÷ khoảng cách SL; bot tính sẵn số lot |

Lịch: thứ Ba → thứ Bảy lúc 07:30 giờ VN. Thứ Bảy gửi **tín hiệu tuần**; các ngày khác ghi nhận giá vào và báo khi chạm SL/TP.
Mỗi ngày chỉ dùng khoảng 4–15 lượt Twelve Data (gói miễn phí có 800 lượt/ngày).

Backtest 2011–2026 (đã trừ spread, **chưa tính swap**): khoảng +0,14R/lệnh, khoảng 100 lệnh/năm, thắng 45%, RR khoảng 1:1,9.

## 2. Bot Crypto Spot (`crypto_ma_bot.py`)

| | Quy tắc |
|---|---|
| Danh mục | Top 10 coin theo giá trị giao dịch 60 ngày trên Binance (bỏ stablecoin), chọn lại đầu tháng |
| Mua | Đóng cửa ngày **cắt lên MA10** (và trên MA30) → mua 1/10 tổng tài sản |
| Bán | Đóng cửa ngày **dưới MA30** |

Lịch: mỗi ngày lúc 07:07 giờ VN. Dữ liệu từ `data-api.binance.vision` (không cần tài khoản).

## 3. Cài đặt

### GitHub Secrets (Settings → Secrets and variables → Actions)
| Tên | Bắt buộc | Ghi chú |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | có | đã có từ bản cũ |
| `TWELVE_DATA_API_KEY` | có (FX) | đã có từ bản cũ |
| `ACCOUNT_EQUITY` | nên có | vốn tài khoản FX bằng USD, ví dụ `10000` |
| `RISK_PCT` | tuỳ chọn | % rủi ro mỗi lệnh FX, mặc định `0.5` |
| `TONG_TAI_SAN` | tuỳ chọn | tổng tài sản crypto (VND), ví dụ `100000000` |
| `LOAI_TRU` | tuỳ chọn | mã crypto muốn bỏ qua, ví dụ `SNDKB` |

### Chạy lần đầu
Tab **Actions** → chọn workflow → **Run workflow**.
- FX: tích **tuan = true** để có tín hiệu tuần ngay (nếu không, bot chờ đến sáng thứ Bảy).
- Crypto: chạy bình thường, nhận top 10 tháng này.

### Telegram hỏi đáp (Netlify)
Biến môi trường Netlify: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TG_WEBHOOK_SECRET`, `GITHUB_REPO`, `GITHUB_TOKEN_READ` (nếu repo private), tuỳ chọn `TWELVE_DATA_API_KEY`, `ACCOUNT_EQUITY`, `RISK_PCT`.
Đăng ký webhook (mở 1 lần trên trình duyệt):
`https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<site>.netlify.app/.netlify/functions/telegram&secret_token=<TG_WEBHOOK_SECRET>`

Lệnh: **fx**, **crypto**, **lệnh** (cả hai), **giúp**.

## 4. Chuyển từ bản 5 (bỏ hệ thống cũ)
1. Xoá các file cũ: `live_bot.py`, `config.py`, `portfolio_backtest.py`, `simulate_live.py`, `tk2_backtest.py`, `tk2_signal.py`, `twelvedata_client.py`, `requirements.txt`, `.github/workflows/live-bot.yml`, thư mục `dashboard/src`, `dashboard/package.json`, `dashboard/vite.config.js`, `dashboard/index.html`, `dashboard/public/data`.
2. Tải lên các file mới của bản này (giữ nguyên đường dẫn thư mục).
3. **cron-job.org**: tắt hoặc xoá job gọi `live-bot.yml` (workflow cũ không còn). Hai bot mới tự chạy theo lịch GitHub, không cần cron-job.
4. File `data/live_state.json` cũ có thể xoá.

*Phân tích dữ liệu quá khứ, không phải lời khuyên đầu tư.*
