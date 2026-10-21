"""QA M6: CatalogService / AlertService / ShoppingListService với dữ liệu biên (PostgreSQL thật)."""

import unicodedata
from datetime import timedelta

import pytest
from sqlmodel import Session

from app.domain.catalog import AlertCreate, CatalogFilters
from app.domain.enums import AlertChannel, AlertStatus, Category, PriceType, SiteKey, StockStatus
from app.domain.errors import AlertNotFound, DuplicateAlert, ListNotFound, ValidationFailed
from app.services.alert_service import AlertService
from app.services.catalog_service import CatalogService
from app.services.conversation_service import MAX_MESSAGE_CHARS, ConversationService
from app.services.shopping_list_service import ShoppingListService
from app.services.views import key_specs
from tests.factories import make_price_history
from tests.service_support import NOW, add_offer, add_product, clock, make_settings

NUL = chr(0)
ZWSP = chr(0x200B)


def catalog(session: Session) -> CatalogService:
    return CatalogService(session, now=clock)


def alerts(session: Session, **settings: object) -> AlertService:
    return AlertService(session, make_settings(**settings), now=clock)


def lists(session: Session) -> ShoppingListService:
    return ShoppingListService(session, now=clock)


# ---- CatalogService ----
def test_vietnamese_query_matches_whatever_unicode_form_it_is_typed_in(db_session: Session) -> None:
    """BUG-M6-10: 'Chuột' gõ ở dạng tổ hợp (NFD) không khớp tên đã lưu ở dạng NFC."""
    product = add_product(db_session, canonical_name="Chuột Logitech G102 Mock")
    add_offer(db_session, product)

    for form in ("NFC", "NFD", "NFKC", "NFKD"):
        query = unicodedata.normalize(form, "chuột LOGITECH")
        assert catalog(db_session).search(CatalogFilters(q=query)).total == 1, form


def test_brand_filter_is_unicode_form_insensitive(db_session: Session) -> None:
    product = add_product(db_session, brand="Điện Quang")
    add_offer(db_session, product)
    brand = unicodedata.normalize("NFD", "điện quang")
    assert catalog(db_session).search(CatalogFilters(brands=[brand])).total == 1


@pytest.mark.parametrize("field", ["q", "brand"])
def test_nul_character_in_a_search_text_is_ignored_not_a_database_error(
    db_session: Session, field: str
) -> None:
    """BUG-M6-8: NUL làm PostgreSQL ném DataError (HTTP 500 / TOOL_ERROR)."""
    add_offer(db_session, add_product(db_session, brand="Mock"))
    filters = (
        CatalogFilters(q="Mock" + NUL + "x")
        if field == "q"
        else CatalogFilters(brands=["Mock" + NUL])
    )

    result = catalog(db_session).search(filters)

    assert result.total in (0, 1)


def test_price_range_with_min_above_max_is_empty_not_an_error(db_session: Session) -> None:
    add_offer(db_session, add_product(db_session), price=20_000_000)

    result = catalog(db_session).search(CatalogFilters(price_min=30_000_000, price_max=10_000_000))

    assert (result.total, result.items, result.stale, result.data_as_of) == (0, [], False, None)


def test_offset_past_the_end_keeps_total_and_gives_no_items(db_session: Session) -> None:
    for _ in range(3):
        add_offer(db_session, add_product(db_session))

    result = catalog(db_session).search(CatalogFilters(limit=10, offset=50))

    assert (result.total, result.items, result.stale, result.data_as_of) == (3, [], False, None)


def test_product_whose_offers_are_all_inactive_is_not_listed(db_session: Session) -> None:
    add_offer(db_session, add_product(db_session), is_active=False)
    assert catalog(db_session).search(CatalogFilters()).total == 0


def test_price_zero_filter_is_reported_as_applied(db_session: Session) -> None:
    applied = catalog(db_session).search(CatalogFilters(price_max=0)).applied_filters
    assert applied["price_max"] == 0 and "offset" not in applied


def test_pages_with_equal_prices_neither_repeat_nor_skip_products(db_session: Session) -> None:
    created = {
        add_offer(db_session, add_product(db_session), price=9_000_000).product_id
        for _ in range(25)
    }

    seen: list[int] = []
    for offset in (0, 10, 20):
        page = catalog(db_session).search(
            CatalogFilters(limit=10, offset=offset, sort="price_desc")
        )
        seen += [item.product_id for item in page.items]

    assert sorted(seen) == sorted(created)


def test_rows_keep_input_order_skip_unknown_ids_and_cap_offers(db_session: Session) -> None:
    rich = add_product(db_session)
    for index in range(7):
        add_offer(db_session, rich, price=20_000_000 + index * 100_000)
    plain = add_product(db_session)
    add_offer(db_session, plain, price=10_000_000)

    rows = catalog(db_session).rows([plain.id or 0, 987_654, rich.id or 0])

    assert [row.product_id for row in rows] == [plain.id, rich.id]
    assert [o.price for o in rows[1].offers] == [20_000_000 + i * 100_000 for i in range(5)]
    assert rows[1].min_price == 20_000_000


def test_rows_use_the_effective_price_and_hide_unbuyable_offers(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(
        db_session,
        product,
        site=SiteKey.gearvn,
        price=22_000_000,
        list_price=26_000_000,
        price_type=PriceType.member,
    )
    add_offer(db_session, product, site=SiteKey.fptshop, price=25_000_000)
    add_offer(db_session, product, price=1_000_000, stock_status=StockStatus.out_of_stock)
    add_offer(db_session, product, price=2_000_000, is_active=False)

    (row,) = catalog(db_session).rows([product.id or 0])

    assert [(o.site, o.price) for o in row.offers] == [
        (SiteKey.fptshop, 25_000_000),  # giá thành viên so bằng giá niêm yết 26 triệu
        (SiteKey.gearvn, 26_000_000),
    ]
    assert row.min_price == 25_000_000


def test_rows_of_nothing_is_empty(db_session: Session) -> None:
    assert catalog(db_session).rows([]) == []


def test_price_history_window_is_inclusive_and_covers_inactive_offers(db_session: Session) -> None:
    product = add_product(db_session)
    retired = add_offer(db_session, product, site=SiteKey.gearvn, is_active=False)
    assert retired.id
    for price, age in (
        (31_000_000, timedelta(days=30, seconds=1)),
        (30_000_000, timedelta(days=30)),
    ):
        db_session.add(make_price_history(retired.id, price=price, scraped_at=NOW - age))
    db_session.flush()

    result = catalog(db_session).price_history(product.id or 0, days=30)

    assert [p.price for s in result.series for p in s.points] == [30_000_000]
    assert (result.min_price, result.max_price) == (30_000_000, 30_000_000)


def test_key_specs_keep_false_and_zero_but_drop_missing_values() -> None:
    specs = {"connection": "wireless", "rgb": False, "buttons": 0, "sensor": None, "dpi_max": []}
    shown = key_specs(Category.mouse, specs)
    assert shown == {"connection": "wireless", "buttons": 0, "rgb": False}


def test_key_specs_of_a_category_without_a_layout_keep_stored_order_up_to_six() -> None:
    specs = {f"k{i}": i for i in range(10)}
    assert list(key_specs(Category.other, specs)) == [f"k{i}" for i in range(6)]


# ---- AlertService ----
def _two_alerts_one_paused(db_session: Session) -> tuple[AlertService, int, int, int]:
    product = add_product(db_session)
    add_offer(db_session, product, price=27_000_000)
    service = alerts(db_session)
    request = AlertCreate(product_id=product.id or 0, target_price=20_000_000)
    first = service.create(request)
    service.update(first.alert_id, status=AlertStatus.paused)
    second = service.create(request)  # hợp lệ vì cái đầu đang tạm dừng
    return service, product.id or 0, first.alert_id, second.alert_id


def test_resuming_a_paused_alert_cannot_duplicate_a_live_one(db_session: Session) -> None:
    """BUG-M6-3: bật lại cảnh báo tạm dừng làm hai cảnh báo giống hệt cùng hoạt động."""
    service, _, paused_id, live_id = _two_alerts_one_paused(db_session)

    with pytest.raises(DuplicateAlert) as raised:
        service.update(paused_id, status=AlertStatus.active)

    assert raised.value.details == {"alert_id": live_id}
    assert service.get(paused_id).status is AlertStatus.paused
    assert [a.status for a in service.list_alerts(AlertStatus.active)] == [AlertStatus.active]


def test_resuming_works_when_no_identical_live_alert_exists(db_session: Session) -> None:
    service, _, paused_id, live_id = _two_alerts_one_paused(db_session)
    service.update(live_id, target_price=19_000_000)

    assert service.update(paused_id, status=AlertStatus.active).status is AlertStatus.active


def test_changing_the_threshold_of_a_paused_alert_to_a_live_one_is_still_a_duplicate(
    db_session: Session,
) -> None:
    service, _, paused_id, live_id = _two_alerts_one_paused(db_session)
    service.update(live_id, target_price=19_000_000)

    with pytest.raises(DuplicateAlert):
        service.update(paused_id, target_price=19_000_000)


def test_update_with_the_current_values_is_a_no_op_not_a_duplicate(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    service = alerts(db_session)
    alert = service.create(AlertCreate(product_id=product.id or 0, target_price=20_000_000))

    same = service.update(alert.alert_id, target_price=20_000_000, status=AlertStatus.active)
    nothing = service.update(alert.alert_id)

    assert same == nothing == alert


def test_a_triggered_alert_can_be_rearmed(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product)
    service = alerts(db_session)
    alert = service.create(AlertCreate(product_id=product.id or 0, target_price=20_000_000))
    triggered = service._alerts.get(alert.alert_id)
    assert triggered is not None
    service._alerts.set_status(triggered, AlertStatus.triggered)

    assert service.update(alert.alert_id, status=AlertStatus.active).status is AlertStatus.active


@pytest.mark.parametrize(
    "destination",
    [
        "victim@example.com\nBcc: evil@example.com",
        "victim@example.com\r\nBcc: evil@example.com",
        "victim@example.com,evil@example.com",
        "victim@example.com evil@example.com",
        "vic\ttim@example.com",
    ],
)
def test_email_destination_cannot_smuggle_headers_or_second_recipients(
    db_session: Session, destination: str
) -> None:
    product = add_product(db_session)
    request = AlertCreate(
        product_id=product.id or 0,
        target_price=1_000,
        channel=AlertChannel.email,
        destination=destination,
    )
    with pytest.raises(ValidationFailed):
        alerts(db_session).create(request)


def test_destination_length_limit_is_exact(db_session: Session) -> None:
    product = add_product(db_session)
    service = alerts(db_session)

    def create(chat: str) -> object:
        return service.create(
            AlertCreate(
                product_id=product.id or 0,
                target_price=1_000,
                channel=AlertChannel.telegram,
                destination=chat,
            )
        )

    assert create("1" * 320)
    with pytest.raises(ValidationFailed):
        create("1" * 321)


def test_nul_in_the_destination_is_a_validation_error_not_a_database_error(
    db_session: Session,
) -> None:
    """BUG-M6-8."""
    product = add_product(db_session)
    request = AlertCreate(
        product_id=product.id or 0,
        target_price=1_000,
        channel=AlertChannel.telegram,
        destination="12" + NUL + "3",
    )
    with pytest.raises(ValidationFailed):
        alerts(db_session).create(request)


def test_deleting_an_alert_twice_reports_not_found_the_second_time(db_session: Session) -> None:
    product = add_product(db_session)
    service = alerts(db_session)
    alert = service.create(AlertCreate(product_id=product.id or 0, target_price=5_000_000))

    service.delete(alert.alert_id)

    with pytest.raises(AlertNotFound):
        service.delete(alert.alert_id)
    assert service.create(AlertCreate(product_id=product.id or 0, target_price=5_000_000))


# ---- ShoppingListService ----
def test_list_name_is_measured_after_nfc_so_decomposed_vietnamese_fits(db_session: Session) -> None:
    decomposed = unicodedata.normalize("NFD", "ệ" * 100)
    assert len(decomposed) > 100
    assert lists(db_session).create_list(decomposed).name == "ệ" * 100
    with pytest.raises(ValidationFailed):
        lists(db_session).create_list(decomposed + "ệ")


@pytest.mark.parametrize("name", [ZWSP, ZWSP * 3, " " + ZWSP + " ", "⁠‍"])
def test_list_name_made_only_of_invisible_characters_is_rejected(
    db_session: Session, name: str
) -> None:
    """BUG-M6-9: tên chỉ gồm ký tự vô hình tạo ra danh sách không có tên nhìn thấy."""
    with pytest.raises(ValidationFailed):
        lists(db_session).create_list(name)


def test_nul_in_a_list_name_or_note_is_a_validation_error(db_session: Session) -> None:
    """BUG-M6-8."""
    product = add_product(db_session)
    service = lists(db_session)
    with pytest.raises(ValidationFailed):
        service.create_list("Mua" + NUL + "sau")
    created = service.create_list("Mock")
    with pytest.raises(ValidationFailed):
        service.add_item(created.list_id, product.id or 0, note="a" + NUL)
    assert service.get_list(created.list_id).items == []


def test_product_without_any_offer_can_be_listed_and_priced_later(db_session: Session) -> None:
    product = add_product(db_session)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(created.list_id, product.id or 0)
    assert (item.price_at_add, item.current_price, item.price_delta) == (None, None, None)

    add_offer(db_session, product, price=12_000_000)
    detail = service.get_list(created.list_id)

    (listed,) = detail.items
    assert (listed.price_at_add, listed.current_price, listed.price_delta) == (
        None,
        12_000_000,
        None,
    )
    assert detail.total_price == 12_000_000


def test_price_drop_after_adding_shows_a_negative_delta_and_updates_the_total(
    db_session: Session,
) -> None:
    product = add_product(db_session)
    offer = add_offer(db_session, product, price=25_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")
    service.add_item(created.list_id, product.id or 0, quantity=2)

    offer.price = 22_000_000
    db_session.flush()
    detail = service.get_list(created.list_id)

    (item,) = detail.items
    assert (item.price_at_add, item.current_price, item.price_delta) == (
        25_000_000,
        22_000_000,
        -3_000_000,
    )
    assert detail.total_price == 44_000_000


def test_items_of_a_deleted_list_or_removed_item_report_not_found(db_session: Session) -> None:
    product = add_product(db_session)
    service = lists(db_session)
    created = service.create_list("Mock")
    item = service.add_item(created.list_id, product.id or 0)
    service.remove_item(created.list_id, item.item_id)

    with pytest.raises(ListNotFound):
        service.remove_item(created.list_id, item.item_id)
    with pytest.raises(ListNotFound):
        service.update_item(created.list_id, item.item_id, quantity=2)
    service.delete_list(created.list_id)
    with pytest.raises(ListNotFound):
        service.add_item(created.list_id, product.id or 0)


@pytest.mark.xfail(
    strict=True,
    reason="BUG-M6-16: giá lớn x số lượng lớn làm total_price vượt BIGINT → ValidationError (500)",
)
def test_extreme_price_times_quantity_never_breaks_the_list_view(db_session: Session) -> None:
    product = add_product(db_session)
    add_offer(db_session, product, price=5_000_000_000)
    service = lists(db_session)
    created = service.create_list("Mock")

    try:
        service.add_item(created.list_id, product.id or 0, quantity=2_147_483_647)
    except ValidationFailed:
        return  # từ chối ngay khi thêm cũng được
    assert service.get_list(created.list_id).total_price >= 0


# ---- ConversationService ----
def test_message_length_limit_is_counted_after_trimming(db_session: Session) -> None:
    service = ConversationService(db_session, now=clock)
    padded = "  " + "x" * MAX_MESSAGE_CHARS + chr(10) + chr(9)

    started = service.start_run(padded)

    assert started.snapshot.messages == []
    with pytest.raises(ValidationFailed):
        service.start_run("x" * (MAX_MESSAGE_CHARS + 1))


@pytest.mark.parametrize("message", ["xin" + NUL + "chào", NUL])
def test_nul_in_a_user_message_is_a_validation_error(db_session: Session, message: str) -> None:
    """BUG-M6-8: NUL làm PostgreSQL ném DataError khi ghi tin nhắn."""
    with pytest.raises(ValidationFailed):
        ConversationService(db_session, now=clock).start_run(message)


def test_vietnamese_decomposed_message_is_stored_as_typed(db_session: Session) -> None:
    typed = unicodedata.normalize("NFD", "tìm chuột không dây")
    service = ConversationService(db_session, now=clock)

    first = service.start_run(typed)
    second = service.start_run("tiếp", first.conversation_id)

    assert second.snapshot.messages[0][1] == typed
