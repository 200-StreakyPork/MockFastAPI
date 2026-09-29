"""OAuth flows against the isolated MySQL and Redis fixtures."""

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


@pytest.mark.asyncio
async def test_password_refresh_replay_logout(isolated_settings: None) -> None:
    """A refreshed session replaces its old tokens and logout revokes access."""
    reset_fixtures()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        auth = ("test-client", "test-secret")
        login = await client.post("/oauth/token", auth=auth, data={
            "grant_type": "password", "username": "alice", "password": "TestPass123!",
        })
        assert login.status_code == 200, login.text
        first = login.json()
        assert first["token_type"] == "Bearer"
        assert first["expires_in"] == 1800
        me = await client.get("/auth/me", headers={
            "Authorization": f"Bearer {first['access_token']}"})
        assert me.status_code == 200, me.text
        assert me.json() == {"id": 1, "username": "alice", "role": "employee"}

        refreshed = await client.post("/oauth/token", auth=auth, data={
            "grant_type": "refresh_token", "refresh_token": first["refresh_token"],
        })
        assert refreshed.status_code == 200, refreshed.text
        second = refreshed.json()
        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        replay = await client.post("/oauth/token", auth=auth, data={
            "grant_type": "refresh_token", "refresh_token": first["refresh_token"],
        })
        assert replay.status_code == 400
        assert replay.json()["code"] == "invalid_grant"
        assert (await client.post("/oauth/introspect", auth=auth,
                                  data={"token": first["access_token"]})).json() == {"active": False}
        active = await client.post("/oauth/introspect", auth=auth,
                                   data={"token": second["access_token"]})
        assert active.json()["active"] is True
        logout = await client.post("/auth/logout", headers={
            "Authorization": f"Bearer {second['access_token']}"})
        assert logout.status_code == 204
        gone = await client.get("/auth/me", headers={
            "Authorization": f"Bearer {second['access_token']}"})
        assert gone.status_code == 401
        assert gone.json()["code"] == "invalid_token"

        third_login = await client.post("/oauth/token", auth=auth, data={
            "grant_type": "password", "username": "alice", "password": "TestPass123!",
        })
        third = third_login.json()
        revoked = await client.post("/oauth/revoke", auth=auth,
                                    data={"token": third["refresh_token"]})
        assert revoked.status_code == 204
        assert (await client.get("/auth/me", headers={
            "Authorization": f"Bearer {third['access_token']}"})).status_code == 401


@pytest.mark.asyncio
async def test_client_and_user_credentials(isolated_settings: None) -> None:
    """Only the configured client and a seeded user can obtain tokens."""
    reset_fixtures()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        grant = {"grant_type": "password", "username": "alice", "password": "TestPass123!"}
        bad_client = await client.post("/oauth/token", auth=("test-client", "wrong"), data=grant)
        assert bad_client.status_code == 401
        assert bad_client.json()["code"] == "invalid_client"
        bad_user = await client.post("/oauth/token", auth=("test-client", "test-secret"),
                                     data={**grant, "password": "wrong"})
        assert bad_user.status_code == 400
        assert bad_user.json()["code"] == "invalid_grant"
