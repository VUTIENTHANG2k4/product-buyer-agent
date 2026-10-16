---
paths:
  - "frontend/**"
---

# Quy tắc frontend

- TypeScript strict; không dùng `any` (dùng `unknown` + thu hẹp kiểu). Kiểu API lấy từ `src/api/types.gen.ts` (sinh bằng `npm run gen:api`), không tự viết lại.
- `VITE_API_BASE_URL` là gốc máy chủ (không gồm `/api`); `src/api/client.ts` tự thêm `/api`. `vite.config.ts` đặt `envDir: '..'` để đọc `.env` ở thư mục gốc.
- Gọi API qua TanStack Query (`useQuery`/`useMutation`) trong `src/features/<feature>/api.ts`; component không gọi `fetch` trực tiếp.
- SSE agent: hook `useAgentRun(runId)` trong `src/features/chat/`, tự kết nối lại 3 lần rồi fallback `GET /chat/{run_id}`.
- Component UI nền dùng shadcn/ui (`src/components/ui/`), thêm bằng CLI của shadcn; tra Context7 cho cú pháp hiện hành.
- Màu, font, bo góc chỉ qua token trong `docs/08-ui-ux.md` §5 (biến CSS + Tailwind theme). Không viết mã màu hex trong component.
- Mọi màn hình có đủ trạng thái: đang tải, rỗng, lỗi, dữ liệu cũ (`docs/08-ui-ux.md` §4).
- Định dạng tiền bằng hàm chung `formatVnd(27490000) → "27.490.000 ₫"`; ngày giờ hiển thị theo `Asia/Ho_Chi_Minh`.
- Chữ hiển thị bằng tiếng Việt, gom trong `src/lib/strings.ts` để dễ sửa.
- Tiếp cận: nút có nhãn, focus thấy rõ, `aria-live` cho tiến trình agent, không chỉ dùng màu để truyền nghĩa.
- Test: Vitest + Testing Library cho logic và trạng thái; MSW mock API; không snapshot cả trang.
- Sau khi dựng/sửa một màn hình: chụp màn hình bằng Playwright MCP (sáng/tối, 1280 px và 375 px) và so với `docs/ui/` hoặc wireframe.
