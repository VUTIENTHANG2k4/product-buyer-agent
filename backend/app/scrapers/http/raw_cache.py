"""Lưu HTML đã tải để debug và tạo fixture: `data/raw/<site>/<yyyymmdd>/<hash>.html` (docs/06 §3).

Đây là nhật ký debug, không phải bộ nhớ đệm đọc lại: Fetcher không bao giờ trả HTML từ đây.
"""

import hashlib
import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RETENTION = timedelta(days=7)
_DATE_DIR = re.compile(r"^\d{8}$")
_UNSAFE = re.compile(r"[^a-z0-9.-]+")


class RawCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, host: str, url: str, text: str, *, now: datetime) -> Path:
        """Ghi `text` (UTF-8) và xóa thư mục ngày cũ hơn 7 ngày; trả đường dẫn file.

        `now` là thời gian UTC. Cùng URL trong cùng ngày ghi đè cùng một file.
        """
        site = _UNSAFE.sub("_", host.lower()).strip("_") or "unknown"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        directory = self._root / site / now.strftime("%Y%m%d")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.html"
        path.write_text(text, encoding="utf-8")
        self._prune(now)
        return path

    def _prune(self, now: datetime) -> None:
        cutoff = (now - RETENTION).strftime("%Y%m%d")
        for site_dir in self._root.iterdir():
            if not site_dir.is_dir():
                continue
            for day_dir in site_dir.iterdir():
                if day_dir.is_dir() and _DATE_DIR.match(day_dir.name) and day_dir.name < cutoff:
                    shutil.rmtree(day_dir, ignore_errors=True)
                    logger.debug("Đã xóa raw cache cũ: %s", day_dir)
