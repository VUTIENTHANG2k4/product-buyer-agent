---
name: eval
description: Chạy đánh giá agent với LLM thật trên docs/eval/queries.yaml, phân tích ca sai và đề xuất sửa prompt/tool. Dùng cuối M6, sau khi sửa prompt, trước demo.
disable-model-invocation: true
argument-hint: "[case-id ...]"
allowed-tools: Bash(make eval *) Bash(make eval) Bash(make seed *) Bash(uv run *) Read Edit Grep Glob
---

# /eval — đánh giá agent

Ca chỉ định (tùy chọn): $ARGUMENTS

1. Kiểm tra điều kiện: DB đã seed `eval` (`make seed FIXTURE=eval`), có `GOOGLE_API_KEY` (hỏi người dùng nếu lệnh báo thiếu; **không đọc `.env`**).
2. Chạy `make eval` (hoặc `make eval CASES="L01 C02"` nếu có đối số). Báo cáo ghi ra `reports/eval-<ngày>.md`.
3. Đọc báo cáo, so với ngưỡng ở `docs/05-agent-design.md` §7: intent ≥ 90%, constraint ≥ 95%, hallucination = 0, clarification 100%, tool correctness ≥ 90%.
4. Với mỗi ca sai, phân loại nguyên nhân: planner hiểu sai · tool trả thiếu/sai · executor chọn tool sai · tổng hợp sai · dữ liệu seed thiếu · kỳ vọng trong yaml sai.
5. Đề xuất sửa cụ thể theo nhóm nguyên nhân (đoạn prompt nào, tool nào, seed nào). **Không sửa kỳ vọng trong `queries.yaml` để cho đạt** trừ khi kỳ vọng sai rõ ràng, khi đó giải thích.
6. Sau khi người dùng đồng ý và sửa xong, chạy lại chỉ các ca sai, rồi chạy toàn bộ để tránh hồi quy.
7. Cập nhật bảng "Kết quả đo mới nhất" trong `docs/PROGRESS.md`.
