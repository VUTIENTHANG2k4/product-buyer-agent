"""QA M7: biên và hồi quy cho products/lists/alerts/compare/CORS (không sửa code ứng dụng).

Quy ước: mọi đầu vào xấu phải ra lỗi chuẩn `{"error": {code, message, details}}` (4xx), không 500,
không lộ stack trace. Test đỏ do lỗi ứng dụng giữ bằng `xfail(strict=True)` mã `BUG-M7-n`.
"""

import json
import unicodedata
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import get_settings
from app.main import FRONTEND_ORIGIN
from tests.service_support import add_offer, add_product

INT4_OVER = 2**31
INT8_OVER = 2**63
JSON = {"Content-Type": "application/json"}
BAD_BODIES = [b'{"name": "' + bytes([0xFF, 0xFE]) + b'"}', b'{"name": 1' + b"9" * 5000 + b"}"]


def assert_clean_error(response: Any, status: int | None = None) -> dict[str, Any]:
    """Phản hồi lỗi đúng định dạng chuẩn, không lộ vết ngăn xếp."""
    assert response.status_code >= 400, response.text
    assert response.status_code < 500, f"{response.status_code}: {response.text[:300]}"
    if status is not None:
        assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert isinstance(error["details"], dict)
    text = response.text
    for marker in ("Traceback", 'File "', "psycopg", "sqlalchemy", "SELECT ", "postgresql"):
        assert marker not in text
    return dict(error)


def raw(client: TestClient, method: str, url: str, body: bytes | str, **headers: str) -> Any:
    return client.request(method, url, content=body, headers={**JSON, **headers})


# ---------------------------------------------------------------- id ngoài miền / sai kiểu
BAD_IDS = ["0", "-1", str(INT4_OVER), str(INT8_OVER), str(2**64), "abc", "1.5", "%00", "1e3"]


@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize(
    "method,template",
    [
        ("GET", "/api/products/{}"),
        ("GET", "/api/products/{}/price-history"),
        ("GET", "/api/lists/{}"),
        ("PATCH", "/api/lists/{}"),
        ("DELETE", "/api/lists/{}"),
        ("POST", "/api/lists/{}/items"),
        ("PATCH", "/api/lists/{}/items/1"),
        ("PATCH", "/api/lists/1/items/{}"),
        ("DELETE", "/api/lists/1/items/{}"),
        ("PATCH", "/api/alerts/{}"),
        ("DELETE", "/api/alerts/{}"),
        ("POST", "/api/alerts/{}/test"),
        ("GET", "/api/admin/scrape-runs/{}"),
        ("GET", "/api/admin/scrape-runs/{}/challenge"),
        ("POST", "/api/admin/scrape-runs/{}/challenge"),
        ("GET", "/api/conversations/{}/messages"),
    ],
)
def test_bad_path_ids_never_reach_500(
    client: TestClient, method: str, template: str, bad: str
) -> None:
    body = json.dumps({"name": "x", "product_id": 1, "answer": "1", "quantity": 1})
    response = client.request(method, template.format(bad), content=body, headers=JSON)

    assert_clean_error(response)
    assert response.status_code in (404, 422)


@pytest.mark.parametrize("value", [0, -1, INT4_OVER, INT8_OVER, 2**70, 1.5, "1", "abc", None, [1]])
@pytest.mark.parametrize("field", ["product_id", "preferred_offer_id"])
def test_bad_ids_in_item_body(client: TestClient, value: Any, field: str) -> None:
    created = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]
    payload: dict[str, Any] = {"product_id": 1}
    payload[field] = value
    response = client.post(f"/api/lists/{created}/items", json=payload)

    # `preferred_offer_id: null` là hợp lệ về cú pháp (sản phẩm 1 lại không tồn tại → 404)
    assert_clean_error(response)


@pytest.mark.parametrize(
    "ids", [[1, INT4_OVER], [INT8_OVER, 2**70], [0, -1], [1, "a"], [1], [1, 2, 3, 4, 5, 6], "ab"]
)
def test_compare_bad_ids(client: TestClient, ids: Any) -> None:
    response = client.post("/api/compare", json={"product_ids": ids})

    assert_clean_error(response)


@pytest.mark.parametrize("value", [INT4_OVER, INT8_OVER, 0, -3])
def test_alert_create_bad_product_id(client: TestClient, value: int) -> None:
    response = client.post("/api/alerts", json={"product_id": value, "target_price": 1_000_000})

    assert_clean_error(response)


# ---------------------------------------------------------------- thân yêu cầu hỏng
@pytest.mark.parametrize(
    "url,method",
    [
        ("/api/lists", "POST"),
        ("/api/compare", "POST"),
        ("/api/alerts", "POST"),
        ("/api/chat", "POST"),
        ("/api/admin/scrape-runs", "POST"),
    ],
)
@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"null",
        b"[]",
        b"123",
        b'"str"',
        b'{"name": NaN}',
        b'{"target_price": Infinity, "product_id": 1}',
        b"{" + b'"a":' * 3000 + b"1}",
    ],
)
def test_malformed_json_bodies_give_422(
    client: TestClient, url: str, method: str, body: bytes
) -> None:
    response = raw(client, method, url, body)

    assert_clean_error(response, 422)


@pytest.mark.parametrize("url", ["/api/lists", "/api/compare", "/api/alerts", "/api/chat"])
def test_wrong_content_type_is_rejected_not_500(client: TestClient, url: str) -> None:
    response = client.post(url, content='{"name": "x"}', headers={"Content-Type": "text/plain"})

    assert_clean_error(response)


@pytest.mark.parametrize("body", BAD_BODIES)
def test_undecodable_body_uses_the_standard_validation_error(
    client: TestClient, body: bytes
) -> None:
    response = raw(client, "POST", "/api/lists", body)

    assert_clean_error(response, 422)
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_huge_integer_literal_in_json_is_a_clean_4xx(client: TestClient) -> None:
    digits = "9" * 5000  # vượt giới hạn đổi chuỗi → số nguyên của Python
    response = raw(client, "POST", "/api/alerts", f'{{"product_id": 1, "target_price": {digits}}}')

    assert_clean_error(response)


@pytest.mark.parametrize("bad_float", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_numbers_are_rejected_for_money_fields(
    client: TestClient, bad_float: str
) -> None:
    response = raw(
        client, "POST", "/api/alerts", f'{{"product_id": 1, "target_price": {bad_float}}}'
    )

    assert_clean_error(response, 422)


@pytest.mark.parametrize("text", ["\ud800", "a\ud800b", "\udfff"])
@pytest.mark.parametrize("url,field", [("/api/lists", "name"), ("/api/chat", "message")])
def test_lone_surrogate_escape_in_json_is_422_not_500(
    client: TestClient, url: str, field: str, text: str
) -> None:
    """`{"name": "\\ud800"}` là JSON hợp lệ nhưng không mã hóa được UTF-8 để ghi CSDL."""
    body = json.dumps({field: "X"}).replace("X", text.encode("unicode_escape").decode())
    response = raw(client, "POST", url, body)

    assert_clean_error(response)


# ---------------------------------------------------------------- bool/float lọt vào trường id
@pytest.mark.parametrize("kind", ["bool", "float", "str"])
def test_item_product_id_must_be_a_strict_int(
    client: TestClient, db_session: Session, kind: str
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    assert product.id is not None
    value: Any = {"bool": True, "float": float(product.id), "str": str(product.id)}[kind]
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]

    response = client.post(f"/api/lists/{list_id}/items", json={"product_id": value})

    assert response.status_code == 422, response.text


# ---------------------------------------------------------------- products: query biên
@pytest.mark.parametrize(
    "query",
    [
        "q=%00",
        "q=" + "a" * 201,
        "q=%F0%9F%92%A9",
        "q=%ED%A0%80",  # surrogate đơn trong UTF-8 (không hợp lệ)
        "q=%FF%FE",
        "q=%25",
        "q=_",
        "q=%5C",
        "price_min=-1",
        "price_min=nan",
        "price_min=inf",
        "price_min=1e3",
        "price_min=" + str(INT8_OVER),
        "price_max=" + str(2**200),
        "price_min=5&price_max=1",
        "brand=%00",
        "brand=" + "b" * 101,
        "page=0",
        "page=-1",
        "page=10001",
        "page=abc",
        "page_size=0",
        "page_size=101",
        "page_size=nan",
        "page=10000&page_size=100",
        "sort=bogus",
        "site=bogus",
        "category=bogus",
        "category=laptop&category=mouse",
        "spec.x=1",
        "spec.ram_gb__gte=1",
        "category=laptop&spec.=1",
        "category=laptop&spec.__gte=1",
        "category=laptop&spec.ram_gb__=1",
        "category=laptop&spec.ram_gb__gte__x=1",
        "category=laptop&spec.ram_gb__gte=nan",
        "category=laptop&spec.ram_gb__gte=inf",
        "category=laptop&spec.ram_gb__gte=1e5",
        "category=laptop&spec.ram_gb__gte=" + "9" * 40,
        "category=laptop&spec.ram_gb__gte=-" + "9" * 18,
        "category=laptop&spec.ram_gb__gte=%D9%A1%D9%A6",  # chữ số Ả Rập
        "category=laptop&spec.ram_gb__gte=%EF%BC%91%EF%BC%96",  # chữ số toàn chiều rộng
        "category=laptop&spec.ram_gb__gte=%00",
        "category=laptop&spec.ram_gb__gte=%0A16",
        "category=laptop&spec.ram_gb__gte=16%20",
        "category=laptop&spec.gpu_rank__gte=-5",
        "category=laptop&spec.gpu_rank__eq=0",
        "category=laptop&spec.touchscreen__eq=TRUE",
        "category=laptop&spec.touchscreen__eq=yes",
        "category=laptop&spec.touchscreen__gte=1",
        "category=laptop&spec.brand__in=",
        "category=laptop&spec.brand__in=,,,",
        "category=laptop&spec.brand__in=" + ",".join(["a"] * 51),
        "category=laptop&spec.cpu__eq=" + "z" * 5000,
        "category=laptop&spec.cpu__eq=%00",
        "category=laptop&spec.%E1%BA%A0__eq=1",
        "category=other&spec.ram_gb__gte=1",
        "category=mouse&spec.connection__contains=Wireless",
        "category=mouse&spec.connection__contains_any=wireless,,bluetooth",
        "category=mouse&spec.connection__contains_any=" + "%00",
        "category=mouse&spec.connection__eq=wireless",
    ],
)
def test_product_search_edge_queries_never_500(client: TestClient, query: str) -> None:
    response = client.get(f"/api/products?{query}")

    if response.status_code == 200:
        body = response.json()
        assert {"items", "total", "page", "page_size", "stale", "data_as_of"} <= set(body)
        assert body["total"] >= 0
        assert len(body["items"]) <= body["page_size"]
    else:
        assert_clean_error(response, 422)


def test_search_wildcards_are_literal(client: TestClient, db_session: Session) -> None:
    add_offer(db_session, add_product(db_session, canonical_name="Mock Alpha 15"))

    for needle in ("%", "_", "\\", "%lph%"):
        body = client.get("/api/products", params={"q": needle}).json()
        assert body["total"] == 0, needle


def test_last_page_and_far_offset_are_empty_not_errors(
    client: TestClient, db_session: Session
) -> None:
    for index in range(3):
        add_offer(db_session, add_product(db_session, canonical_name=f"Mock {index}"))
    last = client.get("/api/products", params={"page": 2, "page_size": 2}).json()
    far = client.get("/api/products", params={"page": 10_000, "page_size": 100}).json()

    assert (last["total"], len(last["items"])) == (3, 1)
    assert (far["total"], far["items"]) == (3, [])


def test_empty_catalog_has_null_data_as_of(client: TestClient) -> None:
    body = client.get("/api/products").json()

    assert body["total"] == 0 and body["items"] == []
    assert body["data_as_of"] is None


@pytest.mark.xfail(
    strict=True,
    reason="BUG-M7-3: `q` không bỏ dấu nên 'chuot' không tìm thấy 'Chuột' (gõ không dấu)",
)
def test_unaccented_query_finds_accented_product(client: TestClient, db_session: Session) -> None:
    add_offer(db_session, add_product(db_session, canonical_name="Chuột không dây Mock"))

    assert client.get("/api/products", params={"q": "chuot khong day"}).json()["total"] == 1


def test_unicode_query_matches_regardless_of_normalization(
    client: TestClient, db_session: Session
) -> None:
    name = "Chuột không dây Mock"
    add_offer(db_session, add_product(db_session, canonical_name=name, category="mouse"))
    totals = {}
    for label, text in {
        "nfc": unicodedata.normalize("NFC", "chuột"),
        "nfd": unicodedata.normalize("NFD", "chuột"),
        "upper": "CHUỘT",
    }.items():
        totals[label] = client.get("/api/products", params={"q": text}).json()["total"]

    assert totals == {"nfc": 1, "nfd": 1, "upper": 1}


def test_repeated_spec_param_is_not_silently_dropped(
    client: TestClient, db_session: Session
) -> None:
    low = add_product(db_session, canonical_name="Mock Low", specs={"ram_gb": 8})
    add_offer(db_session, low)
    high = add_product(db_session, canonical_name="Mock High", specs={"ram_gb": 32})
    add_offer(db_session, high)

    response = client.get("/api/products?category=laptop&spec.ram_gb__gte=32&spec.ram_gb__gte=8")

    if response.status_code == 200:
        found = [p["product_id"] for p in response.json()["items"]]
        assert low.id not in found  # ram 8 không thỏa ràng buộc ram >= 32
    else:
        assert response.status_code == 422


@pytest.mark.parametrize("days", ["0", "-1", "99999", "abc", "nan", "1.5"])
def test_price_history_days_edges(client: TestClient, db_session: Session, days: str) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    response = client.get(f"/api/products/{product.id}/price-history?days={days}")

    assert_clean_error(response, 422)


# ---------------------------------------------------------------- lists
@pytest.mark.parametrize(
    "name",
    ["​", "​​", "  ", "　", " ", "﻿", "‮", "\t\n"],
)
def test_list_name_that_is_visually_blank_is_rejected(client: TestClient, name: str) -> None:
    response = client.post("/api/lists", json={"name": name})

    assert response.status_code == 422, response.text


def test_list_name_boundaries_and_unicode(client: TestClient) -> None:
    emoji = "😀" * 100
    nfd = unicodedata.normalize("NFD", "ế" * 100)
    ok_emoji = client.post("/api/lists", json={"name": emoji})
    ok_nfd = client.post("/api/lists", json={"name": nfd})
    too_long = client.post("/api/lists", json={"name": "😀" * 101})

    assert ok_emoji.status_code == 201 and ok_emoji.json()["name"] == emoji
    assert ok_nfd.status_code == 201  # 100 ký tự sau khi ghép dấu
    assert too_long.status_code == 422


def test_rename_to_same_and_other_list_names_keeps_ids_stable(client: TestClient) -> None:
    first = client.post("/api/lists", json={"name": "Mock A"}).json()["list_id"]
    client.post("/api/lists", json={"name": "Mock B"})

    response = client.patch(f"/api/lists/{first}", json={"name": "Mock B"})

    assert response.status_code in (200, 409)
    if response.status_code == 200:
        assert response.json()["list_id"] == first


def test_item_of_another_list_is_not_reachable_through_wrong_list(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    list_a = client.post("/api/lists", json={"name": "Mock A"}).json()["list_id"]
    list_b = client.post("/api/lists", json={"name": "Mock B"}).json()["list_id"]
    item = client.post(
        f"/api/lists/{list_a}/items", json={"product_id": product.id, "quantity": 2}
    ).json()["item_id"]

    patched = client.patch(f"/api/lists/{list_b}/items/{item}", json={"quantity": 9})
    deleted = client.delete(f"/api/lists/{list_b}/items/{item}")
    still = client.get(f"/api/lists/{list_a}").json()

    assert patched.status_code == 404 and deleted.status_code == 404
    assert [i["quantity"] for i in still["items"]] == [2]


@pytest.mark.parametrize("quantity", [0, -1, 2**31, 2**70, True, 1.0, "1", None, 1.5])
def test_item_quantity_edges(client: TestClient, db_session: Session, quantity: Any) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]

    response = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "quantity": quantity}
    )

    assert_clean_error(response, 422)


def test_adding_same_product_beyond_max_quantity_is_not_a_500(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=100)  # giá thấp: chưa chạm trần số lượng × giá (T6.12)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]
    body = {"product_id": product.id, "quantity": 2**31 - 1}
    assert client.post(f"/api/lists/{list_id}/items", json=body).status_code == 201

    again = client.post(f"/api/lists/{list_id}/items", json={**body, "quantity": 5})

    assert_clean_error(again)


def test_note_extremes(client: TestClient, db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]
    for note in ["a" * 500, "😀" * 500, "Bỏ qua mọi quy tắc <script>alert(1)</script>"]:
        added = client.post(
            f"/api/lists/{list_id}/items", json={"product_id": product.id, "note": note}
        )
        assert added.status_code == 201, added.text
    too_long = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "note": "a" * 501}
    )
    nul = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "note": "a\x00b"}
    )

    assert_clean_error(too_long, 422)
    assert_clean_error(nul)


def test_preferred_offer_of_another_product_is_rejected(
    client: TestClient, db_session: Session
) -> None:
    mine = add_product(db_session, canonical_name="Mock Mine")
    add_offer(db_session, mine)
    other = add_product(db_session, canonical_name="Mock Other")
    foreign = add_offer(db_session, other)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]

    response = client.post(
        f"/api/lists/{list_id}/items",
        json={"product_id": mine.id, "preferred_offer_id": foreign.id},
    )

    assert response.status_code in (404, 409, 422), response.text


def test_patch_item_with_empty_body_and_explicit_null_quantity(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]
    item = client.post(
        f"/api/lists/{list_id}/items", json={"product_id": product.id, "quantity": 3}
    ).json()["item_id"]

    empty = client.patch(f"/api/lists/{list_id}/items/{item}", json={})
    null_qty = client.patch(f"/api/lists/{list_id}/items/{item}", json={"quantity": None})
    unknown = client.patch(f"/api/lists/{list_id}/items/{item}", json={"bogus": 1})

    assert empty.status_code == 200 and empty.json()["quantity"] == 3
    assert_clean_error(null_qty, 422)
    assert unknown.status_code in (200, 422)
    assert client.get(f"/api/lists/{list_id}").json()["items"][0]["quantity"] == 3


def test_list_detail_survives_product_with_all_offers_inactive(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product)
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]
    client.post(f"/api/lists/{list_id}/items", json={"product_id": product.id})
    offer.is_active = False
    db_session.add(offer)
    db_session.flush()

    response = client.get(f"/api/lists/{list_id}")

    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 1


def test_deleting_a_list_twice_gives_404_second_time(client: TestClient) -> None:
    list_id = client.post("/api/lists", json={"name": "Mock"}).json()["list_id"]

    assert client.delete(f"/api/lists/{list_id}").status_code == 204
    again = client.delete(f"/api/lists/{list_id}")

    assert_clean_error(again, 404)


# ---------------------------------------------------------------- alerts
@pytest.mark.parametrize("price", [0, -1, 1, 2**63 - 1, INT8_OVER, True, 1.5, "100000", None])
def test_alert_target_price_edges(client: TestClient, db_session: Session, price: Any) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    response = client.post("/api/alerts", json={"product_id": product.id, "target_price": price})

    if response.status_code != 201:
        assert_clean_error(response, 422)


@pytest.mark.parametrize(
    "destination",
    [
        "",
        " ",
        "a" * 1000,
        "not-an-email",
        "a@b",
        "x\x00@example.com",
        "x@example.com\r\nBcc: y@z.com",
    ],
)
def test_alert_email_destination_edges(
    client: TestClient, db_session: Session, destination: str
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    response = client.post(
        "/api/alerts",
        json={
            "product_id": product.id,
            "target_price": 1_000_000,
            "channel": "email",
            "destination": destination,
        },
    )

    assert_clean_error(response, 422)


@pytest.mark.parametrize("channel", ["sms", "EMAIL", "", 5, ["email"]])
def test_alert_bad_channel(client: TestClient, db_session: Session, channel: Any) -> None:
    product = add_product(db_session)
    response = client.post(
        "/api/alerts",
        json={"product_id": product.id, "target_price": 1_000_000, "channel": channel},
    )

    assert_clean_error(response, 422)


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "triggered"},
        {"status": "ACTIVE"},
        {"status": ""},
        {"target_price": 0},
        {"target_price": -5},
        {"target_price": INT8_OVER},
        {"target_price": True},
        {"target_price": 1.5},
        {"target_price": "1"},
    ],
)
def test_alert_patch_rejects_bad_values(
    client: TestClient, db_session: Session, patch: dict[str, Any]
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    alert = client.post(
        "/api/alerts", json={"product_id": product.id, "target_price": 5_000_000}
    ).json()

    response = client.patch(f"/api/alerts/{alert['alert_id']}", json=patch)

    assert_clean_error(response, 422)
    after = client.get("/api/alerts").json()["items"][0]
    assert after["target_price"] == 5_000_000


def test_alert_patch_null_values_and_empty_body_do_not_change_state(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    alert = client.post(
        "/api/alerts", json={"product_id": product.id, "target_price": 5_000_000}
    ).json()
    url = f"/api/alerts/{alert['alert_id']}"

    empty = client.patch(url, json={})
    nulls = client.patch(url, json={"status": None, "target_price": None})

    for response in (empty, nulls):
        assert response.status_code in (200, 422), response.text
    item = client.get("/api/alerts").json()["items"][0]
    assert (item["status"], item["target_price"]) == ("active", 5_000_000)


def test_duplicate_alert_and_pause_resume_conflict(client: TestClient, db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    body = {"product_id": product.id, "target_price": 5_000_000}
    first = client.post("/api/alerts", json=body)
    second = client.post("/api/alerts", json=body)

    assert first.status_code == 201
    assert_clean_error(second, 409)
    alert_id = first.json()["alert_id"]
    assert client.patch(f"/api/alerts/{alert_id}", json={"status": "paused"}).status_code == 200
    third = client.post("/api/alerts", json=body)  # tạm dừng rồi tạo mới: có thể 201 hoặc 409
    assert third.status_code in (201, 409)
    if (
        third.status_code == 201
    ):  # nếu cho tạo thì bật lại cái cũ phải bị chặn, không tạo trùng active
        resume = client.patch(f"/api/alerts/{alert_id}", json={"status": "active"})
        assert_clean_error(resume, 409)


def test_alerts_status_filter_edges(client: TestClient) -> None:
    for value in ["bogus", "ACTIVE", "", "%00"]:
        response = client.get("/api/alerts", params={"status": value})
        assert_clean_error(response, 422)
    assert client.get("/api/alerts?status=triggered").json() == {"items": []}


# ---------------------------------------------------------------- CORS / định dạng lỗi
def test_cors_preflight_allows_only_frontend_origin(client: TestClient) -> None:
    good = client.options(
        "/api/lists",
        headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    evil = client.options(
        "/api/lists",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert good.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-credentials" not in good.headers


@pytest.mark.parametrize(
    "method,url,expected",
    [
        ("GET", "/api/nope", 404),
        ("GET", "/api/products/99999999", 404),
        ("DELETE", "/api/products", 405),
        ("PUT", "/api/lists/1", 405),
        ("GET", "/api/products?page=0", 422),
        ("GET", "/api/chat/not-a-uuid", 422),
        ("GET", "/api/chat/00000000-0000-0000-0000-000000000000", 404),
    ],
)
def test_every_error_branch_has_standard_body_and_cors_header(
    client: TestClient, method: str, url: str, expected: int
) -> None:
    response = client.request(method, url, headers={"Origin": FRONTEND_ORIGIN})

    assert_clean_error(response, expected)
    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN


def test_unhandled_exception_in_route_returns_generic_500_with_cors_and_no_secret(
    db_session: Session, settings: Any
) -> None:
    from app.api.deps import get_catalog_service, get_session
    from app.main import create_app

    class Boom:
        def search(self, *_: Any) -> None:
            raise RuntimeError("postgresql://user:SUPERSECRET@db/prod Traceback")

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_catalog_service] = lambda: Boom()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/api/products", headers={"Origin": FRONTEND_ORIGIN})

    assert response.status_code == 500
    assert response.json()["error"]["code"]
    assert "SUPERSECRET" not in response.text and "Traceback" not in response.text
    assert response.headers.get("access-control-allow-origin") == FRONTEND_ORIGIN


def test_openapi_and_sources_do_not_leak_settings_secrets(client: TestClient) -> None:
    text = client.get("/api/openapi.json").text + client.get("/api/health").text
    text += client.get("/api/admin/sources").text

    for secret in ("postgresql+psycopg://u:p@", "api_key", "smtp_password", "bot_token"):
        assert secret not in text


# ---------------------------------------------------------------- quét mọi trường x toán tử
def _sweep_cases() -> list[tuple[str, str, str, str]]:
    from app.domain.enums import Category
    from app.services.spec_filters import spec_fields

    values = {
        "integer": ["9" * 18, "9" * 19],
        "number": ["9" * 18 + ".999999999"],
        "boolean": ["TRUE"],
        "string": ["Đ" * 300, "\\"],
        "list": [",", "a,b"],
    }
    cases = []
    for category in Category:
        for info in spec_fields(category):
            for op in info.ops:
                for value in values[info.kind]:
                    cases.append((category.value, info.name, op, value))
    return cases


@pytest.mark.parametrize("category,field,op,value", _sweep_cases())
def test_every_spec_field_and_operator_survives_extreme_values(
    client: TestClient, category: str, field: str, op: str, value: str
) -> None:
    response = client.get(
        "/api/products", params={"category": category, f"spec.{field}__{op}": value}
    )

    if response.status_code != 200:
        assert_clean_error(response, 422)


def test_compare_with_the_same_product_twice_is_not_a_500(
    client: TestClient, db_session: Session
) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)

    response = client.post("/api/compare", json={"product_ids": [product.id, product.id]})

    if response.status_code != 200:
        assert_clean_error(response)
    else:
        assert len(response.json()["products"]) in (1, 2)


@pytest.mark.parametrize("path", ["/api/products/", "/api/lists/", "/api/alerts/", "/api/health/"])
def test_trailing_slash_redirect_or_not_found_is_never_an_html_or_500(
    client: TestClient, path: str
) -> None:
    response = client.get(path, follow_redirects=False)

    assert response.status_code in (200, 307, 308, 404)
    if response.status_code == 404:
        assert_clean_error(response, 404)


def test_an_unreadable_body_has_a_machine_readable_error_type(client: TestClient) -> None:
    response = raw(client, "POST", "/api/lists", b"\xff\xfe{")

    assert response.status_code == 422
    (error,) = response.json()["error"]["details"]["errors"]
    assert (error["in"], error["type"]) == ("body", "body_unreadable")


def test_other_bad_requests_keep_their_http_400_code(client: TestClient) -> None:
    from fastapi import HTTPException

    from app.main import create_app

    app = create_app()

    @app.get("/boom-400")
    def boom() -> None:
        raise HTTPException(status_code=400, detail="Tự đặt")

    response = TestClient(app).get("/boom-400")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "HTTP_400"
    assert response.json()["error"]["message"] == "Tự đặt"
