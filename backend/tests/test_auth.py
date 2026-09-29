"""Auth flow: register → login → authenticated /me, plus rejection paths."""


async def test_register_login_me_roundtrip(client):
    creds = {
        "email": "ada@example.com",
        "username": "ada",
        "password": "lovelace-1843",
    }

    reg = await client.post("/api/auth/register", json=creds)
    assert reg.status_code == 201, reg.text
    body = reg.json()
    assert body["token"]
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["username"] == "ada"

    login = await client.post(
        "/api/auth/login",
        json={"email": creds["email"], "password": creds["password"]},
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "ada"


async def test_me_requires_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)


async def test_login_wrong_password_rejected(client):
    await client.post(
        "/api/auth/register",
        json={"email": "grace@example.com", "username": "grace", "password": "correct-horse"},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": "grace@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_duplicate_email_conflict(client):
    payload = {"email": "dup@example.com", "username": "first", "password": "passpass12"}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    payload["username"] = "second"
    again = await client.post("/api/auth/register", json=payload)
    assert again.status_code == 409


async def test_token_lifetime_follows_the_setting(client, monkeypatch):
    from datetime import datetime, timezone

    from jose import jwt

    from app.services import auth as auth_service

    monkeypatch.setattr(auth_service.settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 5)
    reg = await client.post(
        "/api/auth/register",
        json={"email": "hedy@example.com", "username": "hedy", "password": "frequency-hop"},
    )
    claims = jwt.get_unverified_claims(reg.json()["token"])
    remaining = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert 4 * 60 < remaining <= 5 * 60


async def test_expired_token_is_rejected(client):
    from datetime import timedelta

    from app.services.auth import create_access_token

    reg = await client.post(
        "/api/auth/register",
        json={"email": "joan@example.com", "username": "joan", "password": "enigma-1942"},
    )
    user_id = reg.json()["user"]["id"]
    expired = create_access_token({"sub": user_id}, expires_delta=timedelta(seconds=-1))

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert me.status_code == 401


async def test_logout_is_a_stateless_acknowledgement(client):
    resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200
    assert resp.json() == {"message": "logged out"}
