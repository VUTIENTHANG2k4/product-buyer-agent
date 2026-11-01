# Nguồn: Laptop88 (`laptop88`)

> **KHÔNG DÙNG từ 2026-10-19** ([ADR-0008](../adr/0008-fptshop-anphat-replace-hoangha-laptop88.md)): chưa tìm được quy chế/điều khoản và robots.txt chặn bot AI; người dùng chọn thay bằng FPT Shop và An Phát. Giữ nội dung khảo sát dưới đây để tham khảo; không viết scraper.

> Khảo sát ngày: 2026-10-17 (mục 1 xong; mục 2 chưa có điều khoản) · Người khảo sát: người dùng tự đọc và dán nội dung; Claude Code không truy cập trang này · Task: T0.4 (mục 1–2), T4.3 (mục 3–7)

> **Lý do Claude Code không đọc trang này:** robots.txt của Laptop88 chặn `ClaudeBot` và `ChatGPT-User`; theo [02 §3.4](../02-scope-and-sources.md#3-chính-sách-tuân-thủ-bắt-buộc-trong-code) và `.claude/rules/scraping.md` mục 12, không dùng WebFetch hay Playwright MCP với trang này.

## 1. robots.txt
- Ngày đọc: 2026-10-17 (`https://laptop88.vn/robots.txt`, **do người dùng tự mở và dán**, Claude Code không truy cập). Giống bảng [02 §2](../02-scope-and-sources.md#2-kết-quả-robotstxt-đọc-ngày-2026-10-16), không có thay đổi.
- Quy tắc áp dụng cho `*` (User-Agent của dự án không khớp nhóm riêng nào nên rơi vào nhóm này): `Allow: /`; `Disallow: /*?specMap=`, `/*?filter=`. Có `Sitemap: https://laptop88.vn/sitemap.xml`.
- Nhóm khác trong file:
  - Chặn hoàn toàn (`Disallow: /`): `ClaudeBot`, `GPTBot`, `ChatGPT-User`, `CCBot`, `Bytespider` (chú thích trong file: "AI Training Bots").
  - Bot tìm kiếm AI (`Claude-SearchBot`, `PerplexityBot`): `Crawl-delay: 10`, cùng 2 `Disallow` như trên.
  - `Googlebot`, `Googlebot-Image`: cho phép. `bingbot`: `Crawl-delay: 2`. `YandexBot`: `Crawl-delay: 5`.
- Crawl-delay áp dụng cho nhóm `*`: 2 s.
- Độ trễ cấu hình (`min_delay`): 10 s (02 §3.4, thận trọng hơn mức 2 s của nhóm `*`).

## 2. Điều khoản sử dụng
- Link: https://laptop88.vn/chinh-sach-bao-mat-thong-tin-khach-hang.html (trang "Chính sách bảo mật"; người dùng tự mở và dán toàn văn ngày 2026-10-17, Claude Code không truy cập). Chưa có trang "Quy chế hoạt động" hay "Điều khoản sử dụng" nào được cung cấp.
- Có điều khoản về thu thập tự động không? **Không tìm thấy trong trang đã đọc.** Trang này chỉ là chính sách bảo mật thông tin khách hàng (thông tin thu thập, mục đích sử dụng, chia sẻ cho bên thứ ba, cập nhật chính sách, liên hệ). Không có đoạn nào về bot, crawler, scraping, sao chép nội dung hay sở hữu trí tuệ. Đoạn gần nhất là điều kiện tiết lộ thông tin khi "các hành động của quý khách trên các trang web của chúng tôi là vi phạm các quy định hướng dẫn sử dụng của chúng tôi", nhưng trang không dẫn tới văn bản "quy định hướng dẫn sử dụng" nào.
- Căn cứ từ robots.txt: nhóm `*` cho phép thu thập (kèm `Crawl-delay: 2`); các agent AI (`ClaudeBot`, `ChatGPT-User`, ...) bị chặn rõ ràng.
- Kết luận: **Cần hỏi giảng viên** (đang áp dụng, 2026-10-17). Lý do: chưa xác nhận được Laptop88 có hay không có trang quy chế/điều khoản riêng, và chính sách bảo mật nhắc tới "quy định hướng dẫn sử dụng" mà không dẫn link.
  - Nâng lên **Được dùng** (kèm điều kiện bên dưới) nếu người dùng kiểm tra footer laptop88.vn và xác nhận không có trang đó, hoặc trang đó không cấm thu thập tự động. Điều kiện theo 02 §3.4: chỉ thu thập định kỳ theo lịch, `min_delay` 10 s, không dùng cho tìm kiếm trực tiếp tầng 2, không tạo URL có `specMap=`/`filter=`, không dùng Playwright MCP/WebFetch.
  - Nếu trang đó cấm: loại Laptop88 (cập nhật 02, viết ADR, cân nhắc X2).
  - Trong lúc chờ, T4.3 và T4.4 (Laptop88) chưa được bắt đầu; M3 và Hoàng Hà không bị ảnh hưởng.

## 3. Danh mục theo nhóm
| Nhóm | URL danh mục | Phân trang (cách tạo URL trang 2, 3) | Số sản phẩm ước tính |
| --- | --- | --- | --- |
| (T4.3) | | | |

## 4. Cấu trúc dữ liệu
(T4.3)

## 5. Loại giá hiển thị
(T4.3)

## 6. Fixtures đã lưu
(T4.3)

## 7. Vấn đề và lưu ý
(T4.3)
