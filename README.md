# Bot danh mục v5 — Telegram + app điện thoại

Bot chạy trên GitHub Actions, lấy giá H1 từ Twelve Data. Mỗi lần chạy, bot **chạy lại đúng engine backtest**
(`portfolio_backtest.py`) trên các nến đã đóng, so với lần trước, cho tín hiệu mới **qua cổng kiểm soát**
(trần rủi ro + ngắt mạch), rồi gửi Telegram: **VÀO**, **DỜI SL**, **THOÁT**, **ĐÃ CHỐT**, **NGẮT MẠCH**.
Trạng thái được lưu cho app React trên Netlify.

**Bot không đặt lệnh.** Bạn tự vào lệnh theo tin nhắn. **Mọi lệnh đều có SL** — đặt trên sàn ngay khi vào.
B, C, BB, AQB: dời SL khi bot báo. A, D: SL cố định (2 / 10 ATR ngày), bot báo khi nào cần đóng.

## Các thành phần và trọng số (W1)

| | Thành phần | Thị trường | Khung | Rủi ro/lệnh |
|---|---|---|---|---|
| A | Mua sau bán tháo (thứ Hai, giữ 8 ngày), SL 2 ATR | 18 cặp forex không JPY | Ngày + H1 | 0.25% vốn / 1 ATR ngày* (lỗ tối đa ≈ 0.5%) |
| B | Xu hướng yen yếu (Supertrend) | 7 cặp JPY | 4H | 0.35% |
| D | Đảo chiều sức mạnh đồng tiền (z 120 ngày), SL 10 ATR, vào 10:00 VN (03:00 UTC) | 25 cặp forex | Ngày | 0.15% vốn / 1 ATR ngày* (lỗ tối đa ≈ 1.5%) |
| E | Lớp phụ 4H → 1H, RR 2–4, **chỉ vào 8–16h giờ New York** (19–03h VN mùa hè, 20–04h VN mùa đông) | 25 cặp forex | 4H + H1 | 0.15% |
| AQB vàng | Band phân vị thích ứng, vượt q99 | XAUUSD | H1 | 0.75% |
| BB | Squeeze Bollinger | BTC, ETH, SOL | H1 | 0.25% |
| AQB crypto | Band phân vị thích ứng, vượt q95 | BTC, ETH, SOL, DOGE | H1 | 0.25% |
| C | CUSUM short JPY (tùy chọn, mặc định tắt) | 7 cặp JPY | 4H | 0.10% |

\* Khoảng tính khối lượng = max(ATR ngày, 0.4% giá) — chặn trường hợp ATR bị nén giả tạo (kiểu EURCHF trước SNB 2015).

### Giới hạn
- **SL tối thiểu 10 pip** (cặp JPY 0,10) cho B, C, E: nếu đường Supertrend gần hơn, SL được nới ra 10 pip và khối lượng
  tính theo khoảng đã nới. Crypto, vàng (BB, AQB) bỏ lệnh nếu phí > 25% khoảng SL.
- **A:** tối đa 2 lệnh đang mở chung một đồng tiền (ưu tiên cặp quá bán sâu nhất).
- **D:** tối đa 2 lệnh mỗi đồng tiền, tổng 4 lệnh.
- **Crypto (BB + AQB):** tối đa 6 lệnh mở cùng lúc.
- **Toàn danh mục:** tổng rủi ro các lệnh đang mở ≤ **4% vốn**. Vượt trần → tín hiệu mới bị bỏ qua (không đóng lệnh cũ).

### Ngắt mạch
| Tầng | Điều kiện | Hành động |
|---|---|---|
| Phần FX (B, D, E) | Lỗ trong tháng của phần này ≥ **1%** vốn | Dừng vào lệnh mới của B, D, E đến hết tháng |
| Phần A | Lỗ trong tháng của A ≥ **3%** vốn | Dừng vào lệnh A đến hết tháng |
| Khẩn cấp | Lỗ thả nổi toàn danh mục ≥ **3%** (kiểm tra mỗi giờ) | Bot báo đóng tất cả lệnh, nghỉ đến hết ngày |
| Hệ thống | Sụt giảm từ đỉnh ≥ **20%** | Dừng báo tín hiệu, đánh giá lại chiến lược |

Crypto và vàng không có ngắt mạch riêng (kiểm thử cho thấy làm kết quả kém đi); đã có trần 6 lệnh và trần 4%.
Sau khi đánh giá lại, muốn chạy tiếp sau tầng "Hệ thống": đặt biến `RESET_DD` = `1` cho một lần chạy rồi xóa.

Các ngưỡng nằm trong `portfolio_backtest.py` (`MAX_OPEN_RISK`, `CRYPTO_MAX_OPEN`, `BREAK_*`) — dùng chung cho
backtest và bot.

## Hai tài khoản TK1 / TK2

Bot tự theo dõi Equity của TK1 (vốn đã chốt + thả nổi của các lệnh bot đã báo, % vốn) và kiểm tra **mỗi ngày lúc 07:02 giờ VN**.

| | TK1 | TK2 |
|---|---|---|
| Vào lệnh | **Mọi** tín hiệu, liên tục | Chỉ khi TK2 đang BẬT (tin VÀO ghi **TK1 + TK2**) |
| Bật | Luôn bật | WPR(14)+EMA(5) trên Equity TK1 < −80 |
| Lên đạn | Equity TK1 ≥ band trên Bollinger(50; 2,5) | như TK1 |
| Chốt hết | Equity TK1 < đáy 5 ngày trước → đóng mọi lệnh TK1 đang mở, **vào lệnh mới tiếp ngay** | Equity TK1 < đáy 5 ngày trước → đóng mọi lệnh TK2, **TẮT** đến lần bật sau |

Mọi tin nhắn có nhãn tài khoản: 🏦 **TK1**, 🏦 **TK1 + TK2**, hoặc 🏦 **TK2** (lệnh đã đóng ở TK1 nhưng còn ở TK2).
Tin riêng: 🎯 LÊN ĐẠN, 💰 CHỐT HẾT (kèm danh sách lệnh cần đóng), 🟢 TK2 BẬT. Tóm tắt sáng ghi trạng thái hai tài khoản.
Backtest 2011–2026: TK1 có trailing Sharpe ~1,51 (MaxDD −11,4%); TK2 Sharpe ~1,62 (MaxDD −10,6%, có lãi 16/16 năm).
Khi mới khởi động, bot dựng lại lịch sử Equity gần đúng từ các lệnh đã chốt (ghi "lịch sử đầu ước tính" cho đến khi đủ 55 ngày thật).
Tự kiểm tra bằng Equity thật: `python tk2_signal.py --equity tk1_equity.csv`; kiểm chứng: `python tk2_backtest.py --data ./data --trades tk1_trades.csv`.

## Kết quả backtest (09/2011 → 10/2026, có spread, swap, lãi/lỗ thả nổi)

Danh mục thực thi (đã áp trần + ngắt mạch, A và D có SL, E lọc giờ New York): **khoảng 18.4%/năm, Sharpe 1.38,
MaxDD −9.3%, tháng tệ nhất −6.0%**. Đây là kết quả trong mẫu — nhiều lựa chọn (mã crypto, tham số AQB, trọng số, ngưỡng
ngắt, khung giờ E) đã dùng kết quả để quyết định. Kỳ vọng thực tế nên khoảng **10–15%/năm**, drawdown có thể **−15% đến −20%**.
Khoảng 80% rủi ro và lợi nhuận đến từ crypto; forex và vàng làm mượt đường vốn.

Muốn tắt SL của A, D: đặt `A_SL_ATR, D_SL_ATR = 999, 999`; bỏ lọc giờ E: `E_NY_HOURS = (0, 24)` trong `portfolio_backtest.py`.

Chạy lại backtest: `python portfolio_backtest.py --data ./data` (dòng "DANH MỤC THỰC THI" là kết quả có giới hạn).

## Lịch lấy mẫu

| Giờ UTC | Giờ VN | Lấy dữ liệu | Tính |
|---|---|---|---|
| Mỗi giờ | Mỗi giờ | BTC, ETH, SOL, DOGE, vàng + cặp forex đang trong bối cảnh E | BB, AQB, E |
| 00, 04, 08, 12, 16, 20 | 07, 11, 15, 19, 23, 03 | Cả 25 cặp forex + crypto + vàng | B, E, C, A, D |
| 00:02 | 07:02 | (cùng lần 4H) | A, D chấm nến ngày + tóm tắt buổi sáng |
| Thứ Sáu 22:02 | Thứ Bảy 05:02 | Nến cuối tuần | Chốt tín hiệu A, D, B cho thứ Hai |
| Thứ Bảy, Chủ nhật | | Chỉ crypto | BB, AQB crypto |

- **Twelve Data:** khoảng 300 lượt/ngày (gói free 800/ngày, 8/phút). Lần 4H 30 lượt, lần hằng giờ 5–8 lượt.
  Lần khởi động tốn 60 lượt (2 trang × 5000 nến mỗi mã).
- **Thời gian chạy:** lần 4H khoảng 5 phút, lần hằng giờ khoảng 1–2 phút. Repo public miễn phí không giới hạn;
  repo private gói free có 2.000 phút/tháng — có thể không đủ.
- **Bộ nhớ đệm nến H1** (`data/cache/`) lưu bằng GitHub Actions cache, không commit vào repo.

## Cài đặt

### 1. Telegram
1. Nhắn `@BotFather` → `/newbot` → nhận **token**. Nhắn 1 tin cho bot vừa tạo.
2. Mở `https://api.telegram.org/bot<TOKEN>/getUpdates` → `"chat":{"id": ...}` là **chat ID**.

### 2. GitHub
1. Đẩy toàn bộ thư mục này lên repo (thay bản cũ).
2. Settings → Secrets and variables → Actions → **Secrets**: `TWELVE_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. (Tùy chọn) **Variables**:
   - `PARTS` — mặc định `A,B,BB,AQB,D,E`. Thêm C: `A,B,BB,AQB,C,D,E`.
   - `NOTIFY_ONLY_PARTS` — chỉ nhắn Telegram cho các phần này (vd `B,D,AQB`). Dashboard vẫn hiện đủ.
   - `NOTIFY_SKIPPED` = `1` — báo cả tín hiệu bị bỏ qua do trần/ngắt mạch (mặc định chỉ ghi vào nhật ký).
   - `B_FILTER` = `1` — B chỉ vào lệnh khi cú đảo chiều do JPY tự yếu.
   - `ACCOUNT_EQUITY` = vốn của bạn (USD, vd `10000`) — tin VÀO hiện thêm số tiền rủi ro mỗi lệnh.
4. Actions → **Live bot (moi gio)** → **Run workflow**. Lần đầu bot tải dữ liệu (~8 phút), dựng lại lệnh đang mở
   và gửi tin "Bot danh mục v5 đã chạy". Bot tự nhận ra trạng thái của bản cũ và khởi động lại.

### 3. Hẹn giờ chính xác bằng cron-job.org
1. GitHub → Developer settings → Fine-grained tokens: chỉ repo này, quyền **Actions: Read and write**.
2. cron-job.org → mỗi giờ phút **2**, **POST**
   `https://api.github.com/repos/<user>/<repo>/actions/workflows/live-bot.yml/dispatches`,
   headers `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, body `{"ref":"main"}` (trả về 204).

### 4. App trên Netlify
Import repo (có sẵn `netlify.toml`), đặt `GITHUB_REPO` = `user/repo`, `GITHUB_TOKEN_READ` (quyền Contents: Read-only),
`GITHUB_BRANCH` nếu khác `main`. Trên điện thoại: mở trang → Thêm vào Màn hình chính.

## Tin nhắn nhận được
- 🟢/🔴 **VÀO** — kế hoạch 5 bước: ① vào lúc nào, ② SL ở giá nào và cách bao xa (hoặc vì sao không có SL),
  ③ TP / cách thoát và ngày đóng muộn nhất, ④ khối lượng (% vốn ÷ khoảng SL hoặc ATR), ⑤ lý do vào lệnh.
- ↕️ **DỜI SL** — B, C (mỗi 4H), BB, AQB (khi dịch ≥ 0.5R, cách lần báo trước ≥ 4 giờ).
- 🔔 **THOÁT** (D), **HÔM NAY ĐÓNG** (A, ngày giữ cuối).
- ✅/❌ **ĐÃ CHỐT** — R và % vốn.
- ⏸ **NGẮT MẠCH PHẦN**, 🚨 **NGẮT MẠCH KHẨN CẤP**, 🛑 **DỪNG HỆ THỐNG**.
- 📋 Tóm tắt 07:00 sáng: lệnh mở, rủi ro mở / 4%, số lệnh crypto / 6, thả nổi, sụt giảm từ đỉnh, trạng thái ngắt mạch.

## Kiểm chứng
`simulate_live.py` phát lại dữ liệu lịch sử từng giờ đúng như bot chạy thật (thay Twelve Data bằng nguồn giả lập),
in toàn bộ tin nhắn và đối chiếu với lệnh backtest (lệnh bị cổng kiểm soát chặn được đếm riêng):
```
python simulate_live.py --data ./du_lieu --start "2026-08-17 00:02" --end "2026-08-21 23:02"
```
Thư mục dữ liệu: file H1 xuất từ MT5 (25 cặp, BTC, ETH, XAUUSD) và file nến 1 giờ Binance (SOLUSDT, DOGEUSDT).

## Lưu ý quan trọng
- **Giá Twelve Data khác giá sàn một chút** — tín hiệu sát ngưỡng có thể lệch so với chart sàn.
- **Spread:** Twelve Data không có spread; bot dùng spread điển hình (`SPREAD_PCT` trong `config.py`). Sàn khác nhiều thì sửa.
- **Lãi/lỗ và ngắt mạch tính theo % vốn** từ R của từng lệnh (không cần khai báo vốn). Lệnh bạn bỏ qua hoặc vào khác
  khối lượng thì số liệu của bot sẽ lệch số dư thật.
- **A đang suy yếu** từ 2019 (đã giới hạn 2 lệnh/đồng tiền). **Chỉ báo chế độ B** trong tóm tắt sáng: âm kéo dài thì cân
  nhắc giảm khối lượng B.
- Muốn khởi động lại từ đầu: xóa `data/live_state.json` trong repo.

## Cấu trúc
| File | Vai trò |
|---|---|
| `live_bot.py` | Bot: lịch lấy mẫu, bộ nhớ đệm, chạy engine, cổng kiểm soát, ngắt mạch, Telegram |
| `portfolio_backtest.py` | Engine chiến lược v5 — dùng chung cho backtest và bot |
| `config.py` | API, danh sách mã, lịch lấy mẫu, spread, ngưỡng báo dời SL |
| `twelvedata_client.py` | Lấy dữ liệu Twelve Data (giãn cách, phân trang khi khởi động) |
| `simulate_live.py` | Mô phỏng bot trên dữ liệu lịch sử |
| `.github/workflows/live-bot.yml` | Lịch chạy, cache nến H1, lưu trạng thái |
| `dashboard/` | App React + Netlify Function `state` |
