"""Bộ nhớ hội thoại cho agent: lịch sử gần đây và danh sách kết quả lượt trước (docs/05 §3).

Kết quả bảng của lượt trước lưu trong `message.payload` dạng `{"product_ids": [...]}` có thứ tự;
executor nhận đoạn "Kết quả gần nhất: 1) id=12 …" để hiểu "máy thứ 2", "hai cái đầu".
Module này không truy cập CSDL: dữ liệu đến từ `ConversationService`.
"""

from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.domain.enums import MessageRole
from app.services.conversation_service import ConversationSnapshot


@dataclass(frozen=True)
class ConversationContext:
    history: list[BaseMessage]
    user_messages: list[str]
    last_results: list[tuple[int, str]]

    def describe_last_results(self) -> str:
        """ "Kết quả gần nhất: 1) id=12 Tên, 2) id=31 Tên"; rỗng nếu lượt trước không có bảng."""
        if not self.last_results:
            return ""
        parts = [f"{i}) id={pid} {name}" for i, (pid, name) in enumerate(self.last_results, 1)]
        return "Kết quả gần nhất (thứ tự hiển thị): " + ", ".join(parts)


def to_context(snapshot: ConversationSnapshot) -> ConversationContext:
    history: list[BaseMessage] = [
        HumanMessage(content=text) if role is MessageRole.user else AIMessage(content=text)
        for role, text in snapshot.messages
    ]
    users = [text for role, text in snapshot.messages if role is MessageRole.user]
    return ConversationContext(history, users, list(snapshot.last_results))
