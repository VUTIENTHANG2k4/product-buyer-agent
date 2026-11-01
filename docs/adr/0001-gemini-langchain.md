# ADR-0001: Dùng LangChain với Gemini làm LLM mặc định, đổi được provider

- Trạng thái: Chấp nhận
- Ngày: 2026-10-16

## Bối cảnh
Đề bài gợi ý LLM (OpenAI/Google) và LangChain. Đồ án sinh viên cần chi phí thấp; test phải chạy offline.

## Quyết định
- Dùng LangChain cho tool calling và structured output.
- LLM mặc định: Gemini (gói `langchain-google-genai`), model cấu hình qua `GEMINI_MODEL`.
- Một hàm factory `get_chat_model(role)` chọn provider theo `LLM_PROVIDER` (`gemini` | `openai` | `fake`).
- Phiên bản LangChain khóa trong `pyproject.toml`; tra tài liệu hiện hành qua Context7 trước khi viết code agent.

## Hệ quả
- Đổi sang OpenAI chỉ cần đổi biến môi trường và chạy lại `make eval`.
- Phụ thuộc vào API LangChain hay thay đổi: cô lập toàn bộ code LangChain trong `app/agent/` để dễ nâng cấp.
- Test dùng model giả, không tốn phí.

## Phương án đã cân nhắc
- Gọi SDK Gemini trực tiếp, tự viết vòng lặp tool: ít phụ thuộc hơn nhưng lệch gợi ý đề bài và tốn công.
- LangGraph: mạnh cho luồng nhiều nhánh; chưa cần ở quy mô này, có thể chuyển sau.
