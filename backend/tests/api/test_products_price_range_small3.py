"""T7.6: khoảng giá ngược của GET /products là lỗi 422, không phải kết quả rỗng."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(("low", "high"), [(5, 1), (20_000_001, 20_000_000), (1, 0)])
def test_inverted_price_range_is_a_validation_error(
    client: TestClient, low: int, high: int
) -> None:
    response = client.get("/api/products", params={"price_min": low, "price_max": high})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == {"price_min": low, "price_max": high}


@pytest.mark.parametrize(
    "params", [{"price_min": 5, "price_max": 5}, {"price_min": 0, "price_max": 0}, {"price_min": 9}]
)
def test_equal_or_open_ended_price_ranges_are_accepted(
    client: TestClient, params: dict[str, int]
) -> None:
    response = client.get("/api/products", params=params)

    assert response.status_code == 200


def test_repeating_a_spec_parameter_is_still_rejected(client: TestClient) -> None:
    response = client.get("/api/products?category=laptop&spec.ram_gb__gte=8&spec.ram_gb__gte=16")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
