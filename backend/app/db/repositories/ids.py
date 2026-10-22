"""Id từ bên ngoài (đường dẫn API, tham số tool) có thể vượt cột INTEGER của khóa chính.

PostgreSQL ném `DataError` ("integer out of range") thay vì không tìm thấy dòng, nên mọi truy vấn
theo khóa chính từ dữ liệu người dùng phải lọc id ngoài miền trước (kết quả là "không tồn tại").
"""

from collections.abc import Iterable

from app.domain.dto import INT4_MAX


def fits_int4(value: int) -> bool:
    """`value` nằm trong miền khóa chính hợp lệ (1..2^31-1)."""
    return 1 <= value <= INT4_MAX


def keep_valid(values: Iterable[int]) -> list[int]:
    """Các id nằm trong miền khóa chính, giữ thứ tự và phần tử trùng."""
    return [value for value in values if fits_int4(value)]
