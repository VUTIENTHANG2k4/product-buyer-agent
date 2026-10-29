from datetime import UTC

from app.db import models
from app.domain.clock import utc_now


def test_utc_now_is_timezone_aware_utc() -> None:
    assert utc_now().tzinfo is UTC


def test_db_models_use_the_domain_clock() -> None:
    assert models.utc_now is utc_now
