---
name: ui-screen
description: Dựng hoặc chỉnh một màn hình frontend theo wireframe và token trong docs/08-ui-ux.md, ảnh tham khảo trong docs/ui/, với dữ liệu giả MSW, đủ trạng thái, test và ảnh chụp kiểm tra. Dùng cho các task M8 và mọi yêu cầu sửa giao diện.
argument-hint: "<tên màn hình: home | results | compare | product | lists | alerts | admin>"
---

# Dựng màn hình: $ARGUMENTS

## Đầu vào cần đọc
1. `docs/08-ui-ux.md`: mục wireframe của màn hình, §4 trạng thái, §5 token, §6 responsive/tiếp cận.
2. Ảnh trong `docs/ui/` trùng tên màn hình (ví dụ `docs/ui/results.png`) và các `ref-*.png` có ghi chú. Ảnh có ưu tiên cao hơn wireframe ASCII khi khác nhau; nếu mâu thuẫn với yêu cầu chức năng, hỏi người dùng.
3. Endpoint liên quan trong `docs/07-api-spec.md` và kiểu trong `src/api/types.gen.ts`.

## Cách làm
1. Liệt kê component cần có; dùng shadcn/ui có sẵn trước (Table, Sheet, Dialog, Badge, Skeleton, Tabs, DropdownMenu, Tooltip…). Thêm component shadcn bằng CLI.
2. Dựng với dữ liệu giả qua MSW handler trong `src/mocks/` (dùng dữ liệu hư cấu, tên có chữ "Mock").
3. Làm đủ trạng thái: tải (Skeleton), rỗng, lỗi, dữ liệu cũ; với bảng: sắp xếp, chọn, responsive dạng thẻ dưới 640 px.
4. Chỉ dùng token (biến CSS / lớp Tailwind theo theme), không mã màu cứng. Chữ hiển thị đưa vào `src/lib/strings.ts`.
5. Test Vitest: hiển thị dữ liệu, mỗi trạng thái, tương tác chính (sắp xếp, chọn, mở hộp thoại), truy vấn theo vai trò/nhãn.
6. Chạy `npm run dev`, dùng Playwright MCP chụp màn hình 4 biến thể: sáng/tối × 1280 px/375 px. Lưu vào `docs/ui/screens/<màn hình>-<theme>-<width>.png`.
7. So với ảnh tham khảo/wireframe; liệt kê khác biệt còn lại và lý do. Trình ảnh cho người dùng duyệt.
8. Nối API thật (bỏ MSW cho runtime, giữ cho test) khi endpoint đã có.

## Kiểm tra tiếp cận nhanh
- Tab qua mọi phần tử tương tác theo thứ tự hợp lý, focus nhìn thấy.
- Nút chỉ có biểu tượng có `aria-label`.
- Tương phản chữ đạt AA ở cả hai theme.
