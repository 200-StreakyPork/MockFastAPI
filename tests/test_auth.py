"""OAuth flows against the isolated MySQL and Redis fixtures."""

import os
import subprocess
import sys

import httpx
import pytest

from mockfastapi.app import create_app


def test_openapi_describes_oauth_forms_and_authentication() -> None:
    schema = create_app().openapi()
    schemes = schema["components"]["securitySchemes"]
    assert schemes["OAuthClientBasic"] == {"type": "http", "scheme": "basic"}
    assert schemes["AccessTokenBearer"] == {"type": "http", "scheme": "bearer"}

    paths = schema["paths"]
    for path in ("/oauth/token", "/oauth/revoke", "/oauth/introspect"):
        operation = paths[path]["post"]
        assert operation["security"] == [{"OAuthClientBasic": []}]
        form = operation["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]
        assert form
    token_form = paths["/oauth/token"]["post"]["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]
    grants = token_form["oneOf"]
    assert {grant["properties"]["grant_type"]["const"] for grant in grants} == {
        "password", "refresh_token",
    }
    assert {tuple(grant["required"]) for grant in grants} == {
        ("grant_type", "username", "password"), ("grant_type", "refresh_token"),
    }
    assert paths["/oauth/revoke"]["post"]["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]["required"] == ["token"]
    assert paths["/oauth/introspect"]["post"]["requestBody"]["content"]["application/x-www-form-urlencoded"]["schema"]["required"] == ["token"]
    for path in ("/auth/me", "/auth/logout", "/people", "/people/{person_id}",
                 "/leaves", "/leaves/{leave_id}", "/leaves/{leave_id}/decision",
                 "/leaves/{leave_id}/withdraw"):
        for operation in paths[path].values():
            assert operation["security"] == [{"AccessTokenBearer": []}]
    token_response = paths["/oauth/token"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert token_response["$ref"] == "#/components/schemas/TokenResponse"


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
        assert login.headers["Cache-Control"] == "no-store"
        assert login.headers["Pragma"] == "no-cache"
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
        assert refreshed.headers["Cache-Control"] == "no-store"
        assert refreshed.headers["Pragma"] == "no-cache"
        second = refreshed.json()
        assert second["access_token"] != first["access_token"]
        assert second["refresh_token"] != first["refresh_token"]
        replay = await client.post("/oauth/token", auth=auth, data={
            "grant_type": "refresh_token", "refresh_token": first["refresh_token"],
        })
        assert replay.status_code == 400
        assert replay.json()["code"] == "invalid_grant"
        assert replay.json()["error"] == "invalid_grant"
        assert replay.json()["error_description"] == replay.json()["message"]
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
        assert revoked.status_code == 200
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
        assert bad_client.json()["error"] == "invalid_client"
        assert bad_client.json()["error_description"] == bad_client.json()["message"]
        assert bad_client.headers["WWW-Authenticate"] == 'Basic realm="mockfastapi"'
        bad_user = await client.post("/oauth/token", auth=("test-client", "test-secret"),
                                     data={**grant, "password": "wrong"})
        assert bad_user.status_code == 400
        assert bad_user.json()["code"] == "invalid_grant"
        assert bad_user.json()["error"] == "invalid_grant"
        assert bad_user.json()["error_description"] == bad_user.json()["message"]
