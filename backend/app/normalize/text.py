"""Chuẩn hóa văn bản dùng chung cho các bộ nhận diện (hãng, thông số, mã model, ghép mẫu)."""

import unicodedata


def fold(text: str) -> str:
    """Chữ thường, NFKD (kể cả chữ toàn chiều rộng), bỏ dấu và ký tự định dạng vô hình.

    Nhờ đó "Ａｃｅｒ", "A​cer" và "Chuột" (có dấu hay không) đều so khớp được; `đ` thành `d`.
    """
    nfkd = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    kept = (c for c in nfkd if not unicodedata.combining(c) and unicodedata.category(c) != "Cf")
    return "".join(kept).strip()
