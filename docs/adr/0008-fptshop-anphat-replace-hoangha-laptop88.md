# ADR-0008: FPT Shop và An Phát thay Hoàng Hà và Laptop88 làm trang lõi

- Trạng thái: Chấp nhận — Thay thế một phần ADR-0005 (danh sách trang lõi của tầng 1)
- Ngày: 2026-10-19

## Bối cảnh
ADR-0005 chọn GearVN, Laptop88 và Hoàng Hà Mobile làm trang lõi. Kết quả khảo sát T0.4 (xem `docs/sources/`) để cả hai trang này ở trạng thái "Cần hỏi giảng viên":
- **Hoàng Hà Mobile:** quy chế chỉ cấm khai thác cho mục đích thương mại khi không có văn bản cho phép; không cấm mục đích phi thương mại, nhưng cần người có thẩm quyền xác nhận.
- **Laptop88:** robots.txt chặn `ClaudeBot`, `ChatGPT-User` và nhiều bot AI khác, cho bot chung 2 s và bot tìm kiếm AI 10 s; chưa tìm được trang quy chế hay điều khoản sử dụng riêng. Trang này cũng không dùng được cho tìm kiếm trực tiếp (tầng 2).

M4 vì thế bị chặn từ T0.4. Đồ án là đồ án cá nhân phi thương mại, dùng làm bài trình bày xin việc; người dùng không muốn phụ thuộc vào phản hồi của giảng viên.

## Quyết định
- **Bỏ** Hoàng Hà Mobile và Laptop88 khỏi danh sách trang lõi. Không viết scraper cho hai trang này. File `docs/sources/hoangha.md` và `laptop88.md` giữ nguyên nội dung khảo sát, đánh dấu "không dùng".
- **Thêm FPT Shop (`fptshop`) và An Phát Computer (`anphat`)** làm trang lõi cùng GearVN. Theo khảo sát sơ bộ ngày 2026-10-19 (bằng công cụ đọc trang tóm tắt, chưa phải T0.4 đầy đủ):
  - FPT Shop và An Phát không chặn `ClaudeBot` hay `ChatGPT-User` trong robots.txt; quy chế của FPT Shop không nói về bot; An Phát khai báo `Crawl-delay: 5` và không có trang điều khoản sử dụng riêng.
  - Kết luận chính thức "được dùng" của từng trang chỉ có hiệu lực sau khi T4.1 (FPT Shop) và T4.3 (An Phát) điền `docs/sources/<site>.md` mục 1–2 và **người dùng duyệt** bằng cách tự mở các link đối chiếu.
- Quy tắc tầng 1 không đổi: một nhóm thuộc tầng 1 khi có ít nhất 2 trang lõi cung cấp. Ma trận trang × nhóm thật được chốt ở T4.1 và T4.3.
- Dữ liệu thật của các trang chỉ phục vụ phát triển và chạy cục bộ. Bản trình diễn công khai (ví dụ đính kèm CV) chỉ dùng dữ liệu seed hư cấu, không đăng dữ liệu đã thu thập của các trang.
- Giá trị `hoangha`, `laptop88` **vẫn nằm trong `SiteKey`** (và trong CHECK của CSDL) vì dữ liệu seed và nhiều test đang dùng. Migration `0002` thêm `fptshop`, `anphat`. Việc đổi seed/test sang trang mới và gỡ giá trị cũ là task riêng (T4.6).
- Tầng 2 và pha mở rộng điện thoại (X1) đang ghi Hoàng Hà: bỏ Hoàng Hà khỏi danh sách đó; trang cho điện thoại sẽ chọn lại khi làm X1.

## Hệ quả
- M4 đổi thành "FPT Shop + An Phát"; T4.0 cập nhật docs/enum/migration, T4.1–T4.5 khảo sát, viết scraper, chạy thật.
- Quy tắc riêng cho trang chặn agent AI (không dùng Playwright MCP/WebFetch, chỉ lấy trang qua `fetch_page.py`) vẫn áp dụng nếu một trang trong tương lai chặn `ClaudeBot`/`ChatGPT-User`; không còn trang nào hiện hữu thuộc diện này.
- Nếu FPT Shop hoặc An Phát không đạt khi khảo sát (dựng bằng JavaScript không có dữ liệu trong HTML tĩnh, điều khoản cấm, chặn bot), dừng và quyết định lại với người dùng; Phong Vũ là phương án dự phòng.
- Cần ADR mới (hoặc cập nhật ADR này bằng ADR kế tiếp) nếu thay đổi nguồn lần nữa.

## Phương án đã cân nhắc
- Hỏi giảng viên về Hoàng Hà và Laptop88: giữ nguyên kế hoạch cũ nhưng M4 bị chặn không rõ thời hạn.
- **CellphoneS:** robots.txt chặn mọi URL có `?`, kể cả phân trang, nên không duyệt được toàn bộ danh mục.
- **HACOM:** chặn trang chi tiết và `ClaudeBot`.
- **Phong Vũ:** điều khoản chỉ cấm dùng cho mục đích thương mại; chưa biết có cần JavaScript để hiển thị sản phẩm. Giữ làm phương án dự phòng.
- Chỉ dùng GearVN: không có trang thứ hai nên mất so sánh giá giữa các trang, là điểm chính của đề tài.
