# ADR-0011: Điện thoại (X1) dùng FPT Shop + Nguyễn Kim; bỏ Viettel Store

- Trạng thái: Chấp nhận — Thay thế một phần ADR-0010 (về Nguyễn Kim, chỉ cho nhóm điện thoại tầng 1) và dòng điện thoại trong 02 §1
- Ngày: 2026-11-07

## Bối cảnh
Nhóm điện thoại (X1) thuộc tầng 1 chỉ khi có ít nhất 2 trang lõi ([02 §1](../02-scope-and-sources.md)). Trong ba nguồn lõi hiện có, chỉ FPT Shop bán điện thoại. ADR-0010 bỏ Viettel Store và Nguyễn Kim khỏi **tầng 2** vì trang **tìm kiếm** cần JavaScript; chưa ai kiểm trang **danh mục/chi tiết** của chúng. Người dùng chọn khảo sát lại hai trang này cho tầng 1 (2026-11-07, task X1.1, qua `Fetcher`, `--allow-online`, ~14 request).

Kết quả khảo sát:
- **FPT Shop**: sitemap `/products/sitemap-dien-thoai.xml` (221 URL `/dien-thoai/<slug>`), trang chi tiết có JSON-LD `Product` như các nhóm khác. Mỗi URL là một sản phẩm "gốc" với biến thể dung lượng chọn bằng JavaScript; HTML chỉ chứa biến thể mặc định (h1 "iPhone 16 128GB").
- **Nguyễn Kim**: trang danh mục `/dien-thoai.c` được dựng ở máy chủ, `__NEXT_DATA__.pageProps.pageDetail` chứa 25 máy/trang với giá (211 máy, 9 trang, `?page=N`); trang chi tiết có JSON-LD `Product` và `properties`. Khác với tìm kiếm (`data` rỗng). Mỗi dung lượng/màu là một SKU và URL riêng.
- **Viettel Store**: sitemap có 155 URL `/dien-thoai/<tên>-pid<id>.html` (mỗi biến thể một URL), nhưng trang chi tiết đầu tiên trả challenge `captcha` (bộ phát hiện chung); `fetch_page` dừng, không lưu và **không thử lại**.

## Quyết định
- Điện thoại thuộc tầng 1 với hai trang lõi: **FPT Shop** (sitemap + trang chi tiết, như laptop) và **Nguyễn Kim** (danh mục `/dien-thoai.c?page=N` đọc `__NEXT_DATA__` + chi tiết JSON-LD).
- **Viettel Store không dùng**: gặp challenge captcha thì dừng (02 §3 mục 7). Không viết code né challenge; `SiteKey.viettelstore` vẫn nằm trong enum. Nếu người dùng xác nhận bằng trình duyệt rằng đó là cảnh báo nhầm, mở lại bằng ADR mới.
- Nguyễn Kim vẫn **không** dùng cho tầng 2 (tìm kiếm cần JS, ADR-0010 giữ nguyên); chỉ nhóm điện thoại tầng 1.
- Điều khoản Nguyễn Kim và FPT Shop (không nêu bot/scraping; chỉ cấm sao chép "bất hợp pháp" và nghĩa vụ của thành viên/thương nhân) được người dùng đối chiếu và xác nhận lại ngày 2026-11-07 cho phạm vi danh mục + chi tiết, học tập phi thương mại; dữ liệu thật không đăng công khai (ADR-0008).
- Đọc `__NEXT_DATA__` là dữ liệu có sẵn trong HTML, không phải gọi API nội bộ. Không gọi `/_next/data/…`, không dùng tham số bị robots chặn.

## Hệ quả
- Cần `NguyenKimScraper` (danh sách từ `__NEXT_DATA__`, phân trang `?page=N`, 9 trang × ≥ 5 s ≈ 1 phút/lượt) và mở rộng `FptShopScraper` cho `phone` (task X1.3, X1.4).
- Biến thể dung lượng: Nguyễn Kim cho đủ biến thể và màu; FPT Shop chỉ biến thể mặc định mỗi URL. Ghép sản phẩm theo tên + `storage_gb`/`ram_gb` (X1.2), màu không phải khác biệt.
- Cùng một sản phẩm có thể có nhiều offer của Nguyễn Kim (mỗi màu một URL); khi so sánh giá chỉ lấy giá thấp nhất mỗi trang (xem lại ở X1.4 nếu bảng hiện trùng).
- Fixture mới: `fptshop/` (sitemap + 2 chi tiết), `nguyenkim/` (2 trang danh mục + 1 chi tiết), có test `test_nguyenkim_fixtures.py`.

## Phương án đã cân nhắc
- Dừng X1 vì Viettel Store bị chặn: bỏ phí Nguyễn Kim dùng được.
- Thử lại Viettel Store nhiều lần hoặc đổi cách gọi: trái quy tắc "captcha → dừng" của dự án.
- Chỉ FPT Shop: không có so sánh giá giữa các trang.
