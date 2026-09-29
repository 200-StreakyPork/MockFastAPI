"""HTTP personnel and leave workflows against isolated fixture services."""

import os
import subprocess
import sys

import httpx
import pytest

from mockfastapi.app import create_app


def reset_fixtures() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mockfastapi.cli", "reset"],
        env=os.environ.copy(), capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def bearer(client: httpx.AsyncClient, username: str) -> dict[str, str]:
    response = await client.post("/oauth/token", auth=("test-client", "test-secret"), json={
        "grant_type": "password", "username": username, "password": "TestPass123!",
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_http_create_update_decide_and_visibility(isolated_settings: None) -> None:
    """Routes preserve applicant ownership, approver ACL and hidden detail semantics."""
    reset_fixtures()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        alice = await bearer(client, "alice")
        bob = await bearer(client, "bob")
        carol = await bearer(client, "carol")
        paths = (await client.get("/openapi.json")).json()["paths"]
        assert set(paths) >= {
            "/people", "/people/{person_id}", "/leaves", "/leaves/{leave_id}",
            "/leaves/{leave_id}/decision", "/leaves/{leave_id}/withdraw",
        }
        assert {"get", "post"} <= set(paths["/leaves"])
        assert {"get", "patch"} <= set(paths["/leaves/{leave_id}"])

        people = await client.get("/people", headers=alice, params={"limit": 2, "offset": 1})
        assert people.status_code == 200, people.text
        assert [person["id"] for person in people.json()] == [2, 3]
        assert (await client.get("/people/2", headers=alice)).json()["username"] == "bob"

        created = await client.post("/leaves", headers=alice, json={
            "days": "1.5", "leave_type": "annual", "start_at": "2026-10-05T09:00:00Z",
            "end_at": "2026-10-07T09:00:00Z", "approver_id": 2, "reason": "Travel",
            "applicant_id": 3,
        })
        assert created.status_code == 201, created.text
        leave = created.json()
        assert leave["applicant_id"] == 1
        assert leave["status"] == "pending"
        assert leave["start_at"].endswith("Z")
        leave_id = leave["id"]

        updated = await client.patch(f"/leaves/{leave_id}", headers=alice,
                                     json={"reason": "Family travel"})
        assert updated.status_code == 200, updated.text
        assert updated.json()["reason"] == "Family travel"
        assert (await client.get("/leaves", headers=alice,
                                 params={"status": "pending", "limit": 10, "offset": 0})).json()[-1]["id"] == leave_id

        invisible = await client.get(f"/leaves/{leave_id}", headers=carol)
        assert invisible.status_code == 404
        assert invisible.json()["code"] == "not_found"
        unauthorized_decision = await client.post(f"/leaves/{leave_id}/decision",
                                                  headers=carol, json={"decision": "approved"})
        assert unauthorized_decision.status_code == 404
        applicant_decision = await client.post(f"/leaves/{leave_id}/decision",
                                               headers=alice, json={"decision": "approved"})
        assert applicant_decision.status_code == 403
        assert applicant_decision.json()["code"] == "forbidden"

        decided = await client.post(f"/leaves/{leave_id}/decision", headers=bob,
                                    json={"decision": "approved"})
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "approved"
        assert decided.json()["decided_at"].endswith("Z")
        assert (await client.get(f"/leaves/{leave_id}", headers=alice)).json()["reason"] == "Family travel"
        conflict = await client.patch(f"/leaves/{leave_id}", headers=alice,
                                      json={"reason": "Too late"})
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "conflict"


@pytest.mark.asyncio
async def test_http_validation_auth_and_withdraw(isolated_settings: None) -> None:
    """Malformed inputs and missing tokens have stable errors; pending leave can be withdrawn."""
    reset_fixtures()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        alice = await bearer(client, "alice")
        missing_token = await client.get("/people")
        assert missing_token.status_code == 401
        assert {"code", "message"} <= missing_token.json().keys()
        invalid_page = await client.get("/people", headers=alice, params={"limit": 0})
        assert invalid_page.status_code == 422
        assert {"code", "message", "details"} <= invalid_page.json().keys()
        missing_person = await client.get("/people/99999", headers=alice)
        assert missing_person.status_code == 404
        assert missing_person.json()["code"] == "not_found"
        invalid_leave = await client.post("/leaves", headers=alice, json={
            "days": "1", "leave_type": "annual", "start_at": "2026-10-05T09:00:00Z",
            "end_at": "2026-10-06T09:00:00Z", "approver_id": 3, "reason": "Travel",
        })
        assert invalid_leave.status_code == 422
        assert invalid_leave.json()["code"] == "invalid_input"
        withdrawn = await client.post("/leaves/1001/withdraw", headers=alice)
        assert withdrawn.status_code == 200, withdrawn.text
        assert withdrawn.json()["status"] == "withdrawn"
