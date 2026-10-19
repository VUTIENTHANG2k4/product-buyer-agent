"""RawCache (app/scrapers/http/raw_cache.py)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.scrapers.http.raw_cache import RETENTION, RawCache

NOW = datetime(2026, 10, 19, 8, 30, tzinfo=UTC)


def test_saves_html_under_site_and_date(tmp_path: Path) -> None:
    path = RawCache(tmp_path).save(
        "Shop.Example", "https://shop.example/p/1", "<p>Mô tả</p>", now=NOW
    )

    assert path.parent == tmp_path / "shop.example" / "20261019"
    assert path.suffix == ".html"
    assert path.read_text(encoding="utf-8") == "<p>Mô tả</p>"


def test_same_url_same_day_overwrites_and_other_urls_differ(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    a = cache.save("s.example", "https://s.example/a", "1", now=NOW)
    again = cache.save("s.example", "https://s.example/a", "2", now=NOW)
    b = cache.save("s.example", "https://s.example/b", "3", now=NOW)

    assert a == again and a.read_text(encoding="utf-8") == "2"
    assert b != a


def test_host_with_port_or_odd_characters_makes_a_safe_directory_name(tmp_path: Path) -> None:
    path = RawCache(tmp_path).save("localhost:8100", "http://localhost:8100/c", "x", now=NOW)
    assert path.relative_to(tmp_path).parts[0] == "localhost_8100"


def test_prunes_day_directories_older_than_retention(tmp_path: Path) -> None:
    old = tmp_path / "s.example" / (NOW - RETENTION - timedelta(days=1)).strftime("%Y%m%d")
    edge = tmp_path / "s.example" / (NOW - RETENTION).strftime("%Y%m%d")
    old.mkdir(parents=True)
    edge.mkdir(parents=True)
    (old / "x.html").write_text("old", encoding="utf-8")

    RawCache(tmp_path).save("s.example", "https://s.example/a", "new", now=NOW)

    assert not old.exists()
    assert edge.exists()


def test_prune_leaves_unrelated_files_and_directories_alone(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("keep", encoding="utf-8")
    (tmp_path / "s.example" / "backup").mkdir(parents=True)

    RawCache(tmp_path).save("s.example", "https://s.example/a", "x", now=NOW)

    assert (tmp_path / "notes.txt").exists()
    assert (tmp_path / "s.example" / "backup").exists()
