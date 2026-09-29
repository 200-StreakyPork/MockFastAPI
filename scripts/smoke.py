"""Exercise the common HTTP and MCP flows against a running, freshly reset server."""

import asyncio
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


BASE_URL = os.getenv("MOCKFASTAPI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CLIENT_ID = os.getenv("OAUTH_CLIENT_ID", "test-client")
CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET", "test-secret")
PASSWORD = os.getenv("MOCKFASTAPI_TEST_PASSWORD", "TestPass123!")


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def checked(response: httpx.Response, status: int) -> dict:
    expect(response.status_code == status,
           f"{response.request.method} {response.request.url}: expected {status}, "
           f"got {response.status_code}: {response.text}")
    return response.json() if response.content else {}


async def login(client: httpx.AsyncClient, username: str) -> dict:
    return checked(await client.post("/oauth/token", auth=(CLIENT_ID, CLIENT_SECRET), json={
        "grant_type": "password", "username": username, "password": PASSWORD,
    }), 200)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        ready = checked(await client.get("/health/ready"), 200)
        expect(ready["status"] == "ready", f"service is not ready: {ready}")

        alice = await login(client, "alice")
        bob = await login(client, "bob")
        alice_headers = {"Authorization": f"Bearer {alice['access_token']}"}
        bob_headers = {"Authorization": f"Bearer {bob['access_token']}"}
        expect(checked(await client.get("/auth/me", headers=alice_headers), 200)["username"]
               == "alice", "Alice login did not identify Alice")

        people = checked(await client.get("/people", headers=alice_headers), 200)
        expect(len(people) == 12 and people[0]["username"] == "alice",
               f"expected 12 reset personnel records: {people}")
        expect(checked(await client.get("/people/2", headers=alice_headers), 200)["username"]
               == "bob", "person 2 should be Bob")

        created = checked(await client.post("/leaves", headers=alice_headers, json={
            "days": "1.5", "leave_type": "annual", "start_at": "2026-10-05T09:00:00Z",
            "end_at": "2026-10-07T09:00:00Z", "approver_id": 2,
            "reason": "Smoke test",
        }), 201)
        leave_id = created["id"]
        expect(created["applicant_id"] == 1 and created["status"] == "pending",
               f"wrong created leave: {created}")
        updated = checked(await client.patch(f"/leaves/{leave_id}", headers=alice_headers,
                                             json={"reason": "Smoke test updated"}), 200)
        expect(updated["reason"] == "Smoke test updated", f"update failed: {updated}")
        decided = checked(await client.post(f"/leaves/{leave_id}/decision", headers=bob_headers,
                                            json={"decision": "approved"}), 200)
        expect(decided["status"] == "approved" and decided["decision"] == "approved",
               f"approval failed: {decided}")
        expect(checked(await client.get(f"/leaves/{leave_id}", headers=alice_headers), 200)
               == decided, "approved leave detail differs")

        withdrawn = checked(await client.post("/leaves/1001/withdraw", headers=alice_headers), 200)
        expect(withdrawn["status"] == "withdrawn", f"withdrawal failed: {withdrawn}")

        refreshed = checked(await client.post("/oauth/token", auth=(CLIENT_ID, CLIENT_SECRET),
                                              json={"grant_type": "refresh_token",
                                                    "refresh_token": alice["refresh_token"]}), 200)
        expect(refreshed["access_token"] != alice["access_token"], "refresh did not rotate access token")
        refreshed_headers = {"Authorization": f"Bearer {refreshed['access_token']}"}
        expect(checked(await client.get("/auth/me", headers=refreshed_headers), 200)["username"]
               == "alice", "refreshed access token failed")
        active = checked(await client.post("/oauth/introspect", auth=(CLIENT_ID, CLIENT_SECRET),
                                           json={"token": refreshed["access_token"]}), 200)
        expect(active["active"] is True, f"refreshed access token is inactive: {active}")

        async with httpx.AsyncClient(headers=refreshed_headers, timeout=10) as mcp_http:
            async with streamable_http_client(f"{BASE_URL}/mcp", http_client=mcp_http) as (
                read, write, _
            ):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool("list_people", {"limit": 2})
                    expect(not result.isError and result.structuredContent is not None,
                           f"MCP list_people failed: {result}")
                    expect([p["username"] for p in result.structuredContent["people"]]
                           == ["alice", "bob"], "MCP personnel result differs")

        checked(await client.post("/auth/logout", headers=refreshed_headers), 204)
        expect((await client.get("/auth/me", headers=refreshed_headers)).status_code == 401,
               "logged-out token still works")
        checked(await client.post("/oauth/revoke", auth=(CLIENT_ID, CLIENT_SECRET),
                                  json={"token": bob["refresh_token"]}), 200)
        expect((await client.get("/auth/me", headers=bob_headers)).status_code == 401,
               "revoked session still works")
        print("PASS: ready, login, people, create/update/approve, withdraw, refresh, "
              "introspect, MCP, logout, revoke")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
