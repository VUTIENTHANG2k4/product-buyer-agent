# ADR-0009: Chấp nhận `mock-shop` (tên service Compose) làm địa chỉ cục bộ của mock-shop

- Trạng thái: Chấp nhận — Bổ sung cho ADR-0006 (mock-shop) và quy tắc ở `docs/02` §3
- Ngày: 2026-10-23

## Bối cảnh
`MOCK_SHOP_URL` chỉ nhận `localhost`, `127.0.0.1` hoặc `::1` vì mock-shop được **miễn** robots.txt, chế độ ngoại tuyến và độ trễ của trang thật (`Fetcher` coi mọi máy trùng `netloc` với `MOCK_SHOP_URL` là mock). Giới hạn này bảo đảm biến cấu hình không thể bị dùng để vô hiệu hóa các quy tắc thu thập đối với một trang thật.

T9.4 chạy `api`, `worker` và `mock-shop` thành ba container trong Docker Compose. Trong container, `localhost` là chính container đó, nên `api` và `worker` chỉ gọi được mock-shop qua tên service `mock-shop` (`http://mock-shop:8100`).

## Quyết định
Thêm đúng một tên `mock-shop` vào `LOCAL_HOSTS` trong `app/config.py`. Tên này có một nhãn, không chứa dấu chấm nên không thể là tên miền của trang bán lẻ thật; các biến thể (`mock-shop.example`, `mock-shop.local`, `mock-shop-2`) vẫn bị từ chối (có test). Compose đặt `MOCK_SHOP_URL=http://mock-shop:8100` cho ba container backend.

## Hệ quả
- Ngoài Docker, tên `mock-shop` không phân giải được trừ khi người dùng tự khai báo (hosts, search domain). Đó là lựa chọn có chủ ý trong `.env`, cùng loại rủi ro với việc trỏ `MOCK_SHOP_URL` tới một IP cục bộ khác; rủi ro thấp và đã ghi chú trong `config.py` và `.env.example`.
- Các quy tắc `SCRAPER_OFFLINE_ONLY`, robots.txt, độ trễ của trang thật không đổi.

## Phương án đã cân nhắc
- **Chạy cả ba tiến trình trong một container** để dùng `localhost`: mất mô hình mỗi tiến trình một service (docs/10 §4).
- **`network_mode: service:mock-shop` hoặc `extra_hosts` ánh xạ `localhost`:** phức tạp, làm sai nghĩa `localhost` của chính container.
- **Biến cờ riêng (ví dụ `MOCK_SHOP_ALLOW_REMOTE=true`):** thêm một biến cấu hình có thể bật nhầm; tên cố định an toàn hơn.
