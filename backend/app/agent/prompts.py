"""Nạp prompt từ `app/agent/prompts/*.md` (không viết chuỗi prompt dài trong code)."""

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache
def load_prompt(name: str) -> str:
    """Nội dung `prompts/<name>.md` (UTF-8), bỏ khoảng trắng đầu/cuối."""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
