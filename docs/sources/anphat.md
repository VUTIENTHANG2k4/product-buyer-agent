# Nguồn: An Phát Computer (`anphat`)

> Khảo sát ngày: chưa (T4.3) · Người khảo sát: Claude Code + người dùng · Task: T4.3
> Khảo sát sơ bộ 2026-10-19 (công cụ đọc trang tóm tắt, chưa phải kết luận chính thức): robots.txt không chặn `ClaudeBot`/`ChatGPT-User`, khai báo `Crawl-delay: 5`; không thấy trang điều khoản sử dụng riêng. **Cần người dùng mở link đối chiếu và duyệt ở T4.3 trước khi lưu fixture.** Lý do chọn: [ADR-0008](../adr/0008-fptshop-anphat-replace-hoangha-laptop88.md).

## 1. robots.txt
- Ngày đọc: 2026-10-19 (`https://www.anphatpc.com.vn/robots.txt` và `https://anphat.com.vn/robots.txt` cho nội dung giống nhau), bằng WebFetch (công cụ tóm tắt, **không phải toàn văn**; bản gốc sẽ lưu vào `backend/tests/fixtures/anphat/robots.txt` bằng Fetcher ở bước sau khi bạn duyệt).
- Quy tắc áp dụng cho `*` (có **hai** nhóm `User-agent: *` trong file; RFC 9309 gộp chúng, `RobotsCache` của dự án cần được test với đúng bản gốc):
  - Nhóm 1: `Disallow: /admin/`, `/ajax/`, `/cart`, `/cart/*`; `Crawl-delay: 5`.
  - Nhóm 2 (nằm cuối file): `Disallow: /tim` → chặn mọi đường dẫn bắt đầu bằng `/tim` (gồm `/tim-kiem…`), nên **không dùng tìm kiếm trực tiếp (tầng 2)**.
  - Không có `Allow`; không có mẫu chứa tham số truy vấn (`page=`, `sort=`, `filter=` không bị chặn).
  - Các nhóm chặn hoàn toàn (`Disallow: /`): `OAI-SearchBot`, `CCBot`, `Google-Extended`, `Bytespider`, `PerplexityBot`, `AhrefsBot`, `SemrushBot`, `MJ12bot`, `DotBot`, `DataForSeoBot`, `Amazonbot`, `Applebot-Extended`.
  - `ClaudeBot`, `Claude-User`, `ChatGPT-User`, `GPTBot` không có nhóm riêng nên rơi vào `*`. Tuy nhiên trang chặn nhiều bot AI khác; nên xử lý thận trọng: chỉ thu thập định kỳ, chậm, không dùng cho tầng 2.
  - `Sitemap: https://www.anphatpc.com.vn/sitemap.xml`.
- **Hai tên miền:** nội dung robots.txt giống nhau ở `www.anphatpc.com.vn` và `anphat.com.vn`; menu trang chủ `www.anphatpc.com.vn` lại trỏ tới URL `anphat.com.vn/...`. Cần chốt tên miền chính (theo chuyển hướng thật khi lưu fixture bằng Fetcher) trước khi viết `base_url` ở T4.4; `SiteConfig` yêu cầu mọi URL danh mục cùng máy chủ với `base_url`.
- Crawl-delay: 5 s (nhóm 1).
- Độ trễ cấu hình (`min_delay`): 5 s (= `Crawl-delay`, bằng mặc định toàn cục).

## 2. Điều khoản sử dụng
- Link (footer mục "Chính sách chung"; không có "Quy chế hoạt động", "Điều khoản sử dụng" hay "Điều khoản mua bán"):
  - Chính sách bán hàng: https://www.anphatpc.com.vn/chinh-sach-ban-hang.html
  - Bảo mật thông tin khách hàng: https://www.anphatpc.com.vn/chinh-sach-bao-mat.html
  - Chính sách vận chuyển: https://www.anphatpc.com.vn/giao-hang.html
  - Chính sách bảo hành: https://www.anphatpc.com.vn/trung-tam-bao-hanh.html
  - Chính sách kiểm hàng: https://www.anphatpc.com.vn/chinh-sach-kiem-hang.html
  - Chính sách cho doanh nghiệp: https://www.anphatpc.com.vn/phong-du-an-va-khach-hang-doanh-nghiep.html
- Có điều khoản về thu thập tự động không? **Không tìm thấy** trong hai trang đã đọc (Chính sách bán hàng, Bảo mật thông tin khách hàng). **Hạn chế:** công cụ chỉ đọc được ~100.000 ký tự đầu của mỗi trang, phần lớn là menu điều hướng; nội dung chính sách có thể nằm ở phần cuối chưa đọc. Bốn chính sách còn lại chưa đọc (không liên quan đến sử dụng nội dung website). Bạn nên mở hai link đầu để kiểm tra bằng mắt.
- Kết luận (đề xuất, **chưa duyệt**): **Được dùng**, theo 02 §3 (robots.txt, `Crawl-delay: 5`, không chạm `/admin/`, `/ajax/`, `/cart`, `/tim`). Rủi ro: trang chặn nhiều bot AI khác, nên chỉ thu thập định kỳ, chậm, khối lượng nhỏ, không dùng cho tầng 2.

## 3. Danh mục theo nhóm
URL lấy từ menu trang chủ (WebFetch, 2026-10-19), **chưa mở lại để xác minh**. Menu có hai URL mỗi nhóm (danh mục tổng và danh mục "chơi game"); chọn danh mục tổng, tập con để lại.

| Nhóm | URL danh mục (chưa xác minh) | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| laptop | `https://anphat.com.vn/may-tinh-xach-tay-laptop.html` (tập con: `/laptop-gaming-do-hoa.html`) | Chưa biết | Chưa biết |
| mouse | `https://anphat.com.vn/chuot-may-tinh_dm1291.html` (tập con: `/chuot-choi-game.html`) | Chưa biết | Chưa biết |
| keyboard | `https://anphat.com.vn/ban-phim-may-tinh_dm1027.html` (tập con: `/ban-phim-co-choi-game.html`) | Chưa biết | Chưa biết |
| headset | `https://anphat.com.vn/tai-nghe_dm1180.html` (tập con: `/tai-nghe-choi-game.html`) | Chưa biết | Chưa biết |

## 4. Cấu trúc dữ liệu

## 5. Loại giá hiển thị

## 6. Fixtures đã lưu
- `backend/tests/fixtures/anphat/` (chưa lưu)

## 7. Vấn đề và lưu ý
