"""QA small-1: biên của `DELETE /api/admin/scrape-runs/{id}/challenge` (T2.8)."""

import pytest
from sqlmodel import Session

from tests.api.test_admin_api import (
    admin_client,
    captcha_answer,
    error_code,
    settle,
    start_run,
)


@pytest.mark.parametrize("run_id", ["0", "-1", "2147483648", str(2**63), str(10**30)])
def test_run_ids_outside_the_domain_never_reach_the_database_as_a_500(
    db_session: Session, run_id: str
) -> None:
    with admin_client(db_session) as (client, _):
        response = client.delete(f"/api/admin/scrape-runs/{run_id}/challenge")

        assert response.status_code in {404, 422}
        assert set(response.json()) == {"error"}
        assert "Traceback" not in response.text


@pytest.mark.parametrize("run_id", ["abc", "1.5", "%20", "1e3", "NaN"])
def test_non_integer_run_ids_are_a_standard_validation_error(
    db_session: Session, run_id: str
) -> None:
    with admin_client(db_session) as (client, _):
        response = client.delete(f"/api/admin/scrape-runs/{run_id}/challenge")

        assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"
        assert set(response.json()) == {"error"}


def test_unknown_run_is_404_with_the_run_id_in_details_and_no_stack(db_session: Session) -> None:
    with admin_client(db_session) as (client, _):
        response = client.delete("/api/admin/scrape-runs/424242/challenge")

        assert response.status_code == 404 and error_code(response) == "RUN_NOT_FOUND"
        assert response.json()["error"]["details"] == {"run_id": 424242}
        assert "Traceback" not in response.text and 'File "' not in response.text


def test_a_finished_run_reports_its_status_in_the_409_details(db_session: Session) -> None:
    with admin_client(db_session) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)

        response = client.delete(f"/api/admin/scrape-runs/{run_id}/challenge")

        assert response.status_code == 409 and error_code(response) == "CHALLENGE_NOT_PENDING"
        assert response.json()["error"]["details"] == {"run_id": run_id, "status": "SUCCEEDED"}
        run = client.get(f"/api/admin/scrape-runs/{run_id}").json()
        assert run["status"] == "SUCCEEDED" and run["error_message"] is None


def test_after_cancelling_the_answer_endpoint_is_409_and_the_run_stays_failed(
    db_session: Session,
) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)
        answer = captcha_answer(client, run_id)
        assert client.delete(f"/api/admin/scrape-runs/{run_id}/challenge").status_code == 204

        posted = client.post(f"/api/admin/scrape-runs/{run_id}/challenge", json={"answer": answer})
        again = client.delete(f"/api/admin/scrape-runs/{run_id}/challenge")

        assert posted.status_code == 409 and error_code(posted) == "CHALLENGE_NOT_PENDING"
        assert again.status_code == 409 and again.json()["error"]["details"]["status"] == "FAILED"
        settle(client)
        assert client.get(f"/api/admin/scrape-runs/{run_id}").json()["status"] == "FAILED"


def test_cancel_then_start_immediately_creates_a_new_run_each_time(db_session: Session) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        seen: list[int] = []
        for _round in range(3):
            run_id = start_run(client).json()["run_id"]
            settle(client)
            seen.append(run_id)
            assert client.delete(f"/api/admin/scrape-runs/{run_id}/challenge").status_code == 204

        assert len(set(seen)) == 3
        runs = client.get("/api/admin/scrape-runs?status=FAILED").json()
        assert runs["total"] == 3
        assert all("hủy" in run["error_message"] for run in runs["items"])


def test_delete_with_a_body_or_query_string_is_still_a_clean_204(db_session: Session) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)

        response = client.request(
            "DELETE", f"/api/admin/scrape-runs/{run_id}/challenge?x=1", json={"junk": True}
        )

        assert response.status_code == 204 and response.content == b""


def test_other_methods_on_the_challenge_path_are_not_a_cancel(db_session: Session) -> None:
    with admin_client(db_session, captcha_after=1) as (client, _):
        run_id = start_run(client).json()["run_id"]
        settle(client)

        put = client.put(f"/api/admin/scrape-runs/{run_id}/challenge")
        patch = client.patch(f"/api/admin/scrape-runs/{run_id}/challenge")

        assert put.status_code == patch.status_code == 405
        assert client.get(f"/api/admin/scrape-runs/{run_id}").json()["status"] == "NEEDS_HUMAN"
