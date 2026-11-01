# ADR-0004: Frontend React + Vite + TypeScript + Tailwind + shadcn/ui

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Người dùng muốn tùy biến giao diện theo ý mình (bảng so sánh, ngăn so sánh, tiến trình agent theo thời gian thực).

## Quyết định
- SPA React + Vite + TypeScript strict; Tailwind + shadcn/ui; TanStack Query; React Router; Recharts.
- Kiểu dữ liệu sinh tự động từ OpenAPI của backend (`openapi-typescript`).
- Test: Vitest + Testing Library + MSW; E2E Playwright.

## Hệ quả
- Tùy biến gần như tuyệt đối, giao diện như sản phẩm thật.
- Khối lượng lớn hơn Streamlit; bù lại bằng shadcn/ui và skill `ui-screen`.
- Hai hệ sinh thái (Python + Node) cần quản lý; Makefile gom lệnh.

## Phương án đã cân nhắc
- Streamlit: nhanh nhưng khó tùy biến bố cục và luồng SSE.
- Next.js: thừa tính năng SSR cho ứng dụng cục bộ.
