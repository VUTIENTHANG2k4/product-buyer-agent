# ADR-0010: Tầng 2 dùng GearVN và FPT Shop; bỏ Viettel Store và Nguyễn Kim

- Trạng thái: Chấp nhận — Thay thế một phần ADR-0005 (danh sách trang tìm trực tiếp của tầng 2)
- Ngày: 2026-10-23

## Bối cảnh
Tầng 2 ([ADR-0005](0005-tiered-categories.md)) tìm trực tiếp ở GearVN, Viettel Store và Nguyễn Kim. Điều khoản của hai trang sau đã được người dùng duyệt (2026-10-23), nhưng khảo sát T10.1 (qua `Fetcher`, vài trang tìm kiếm mỗi trang) cho thấy **HTML tĩnh của cả hai trang tìm kiếm không có sản phẩm**:
- **Viettel Store** (`/ket-qua-tim-kiem.html?keyword=…`): khung `#div_Danh_Sach_San_Pham` để trống ("Đang tải…"), danh sách nạp bằng `ajax.aspx`.
- **Nguyễn Kim** (`/search?q=…`, Next.js): `__NEXT_DATA__.pageProps.productSearchData.data` rỗng (`total: 0`, kể cả "loa bluetooth"); kết quả chỉ xuất hiện khi trình duyệt chạy JavaScript.

Code chưa hỗ trợ JavaScript, và quy tắc dự án cấm gọi API nội bộ không công khai ([02 §3](../02-scope-and-sources.md)). Người dùng chọn bỏ hai trang này thay vì thêm trình duyệt headless.

FPT Shop (nguồn lõi, điều khoản đã duyệt ở M4) có `/tim-kiem?s=<từ khóa>` dựng sẵn ở máy chủ: trang có "Tìm thấy N kết quả", mỗi thẻ có tên, giá và giá gốc gạch ngang; robots.txt không chặn.

## Quyết định
- Tầng 2 dùng **GearVN** và **FPT Shop** (và mock-shop khi chạy offline). `FptShopScraper` có `supports_live_search=True`, `search_url` và `parse_search`.
- **Không** viết scraper cho Viettel Store và Nguyễn Kim. `docs/sources/viettelstore.md`, `nguyenkim.md` giữ khảo sát, đánh dấu "không dùng cho tầng 2 (cần JavaScript)". `SiteKey.viettelstore`/`nguyenkim` vẫn nằm trong enum (X1 điện thoại có thể dùng lại).
- Nếu sau này muốn thêm hai trang này: cần ADR mới về cách lấy dữ liệu không dùng JavaScript hoặc về trình duyệt headless.

## Hệ quả
- T10.1 thành "tìm kiếm FPT Shop + kiểm GearVN với nhóm ngoài tầng 1"; T10.2–T10.3 không đổi về thiết kế (danh sách trang lấy từ các scraper có `supports_live_search=True`).
- Độ trễ tầng 2 thật giảm: hai trang thật thay vì ba (NFR-01 ≤ 45 s dễ đạt hơn).
- Hai trang thật cùng bán nhiều nhóm đồ công nghệ (loa, SSD, màn hình…) nên kịch bản "loa bluetooth dưới 1 triệu" vẫn có dữ liệu.

## Phương án đã cân nhắc
- Thêm Playwright/trình duyệt headless cho trang cần JS: đổi lớn (Fetcher, robots, độ trễ, phụ thuộc, test), kéo dài M10.
- Gọi API nội bộ (`ajax.aspx`, API của Next.js): trái quy tắc dự án.
- Chỉ GearVN: ít nguồn hơn mà FPT Shop tìm kiếm được ngay.
