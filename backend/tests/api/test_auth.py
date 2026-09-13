from app.core.config import get_settings
from app.providers.email.base import EmailProvider

settings = get_settings()


class _CapturingEmailProvider(EmailProvider):
    def __init__(self):
        self.sent: list[dict] = []

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


def test_register_returns_access_token_and_sets_refresh_cookie(client, register_payload):
    res = client.post("/api/v1/auth/register", json=register_payload)

    assert res.status_code == 201
    body = res.json()
    assert body["user"]["email"] == register_payload["email"]
    assert body["user"]["role"] == "USER"
    assert "password" not in body["user"]
    assert body["access_token"]
    assert settings.refresh_cookie_name in res.cookies


def test_register_duplicate_email_is_conflict(client, register_payload):
    client.post("/api/v1/auth/register", json=register_payload)
    res = client.post("/api/v1/auth/register", json=register_payload)

    assert res.status_code == 409
    assert res.json()["error"]["code"] == "EMAIL_TAKEN"


def test_register_rejects_weak_password(client, register_payload):
    register_payload["password"] = "short"
    res = client.post("/api/v1/auth/register", json=register_payload)

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_success(client, register_payload):
    client.post("/api/v1/auth/register", json=register_payload)

    res = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )

    assert res.status_code == 200
    assert res.json()["user"]["email"] == register_payload["email"]


def test_login_wrong_password_is_unauthorized(client, register_payload):
    client.post("/api/v1/auth/register", json=register_payload)

    res = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": "totally-wrong-1"},
    )

    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_email_is_unauthorized(client):
    res = client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert res.status_code == 401


def test_refresh_rotates_token_and_invalidates_old_one(client, register_payload):
    client.post("/api/v1/auth/register", json=register_payload)
    stale_refresh_token = client.cookies.get(settings.refresh_cookie_name)

    first_refresh = client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200
    assert first_refresh.json()["access_token"]
    rotated_refresh_token = client.cookies.get(settings.refresh_cookie_name)
    assert rotated_refresh_token != stale_refresh_token

    # The new (rotated) cookie works for a second refresh.
    second_refresh = client.post("/api/v1/auth/refresh")
    assert second_refresh.status_code == 200

    # Re-using the original, now-revoked refresh token must fail.
    client.cookies.set(settings.refresh_cookie_name, stale_refresh_token)
    reused_res = client.post("/api/v1/auth/refresh")
    assert reused_res.status_code == 401
    assert reused_res.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


def test_refresh_without_cookie_is_unauthorized(client):
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "NO_REFRESH_TOKEN"


def test_logout_clears_cookie_and_revokes_session(client, register_payload):
    client.post("/api/v1/auth/register", json=register_payload)

    logout_res = client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 204

    refresh_res = client.post("/api/v1/auth/refresh")
    assert refresh_res.status_code == 401


def test_forgot_password_returns_204_for_unknown_email(client):
    res = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 204


def test_forgot_password_and_reset_password_flow(client, register_payload, monkeypatch):
    client.post("/api/v1/auth/register", json=register_payload)

    fake_email = _CapturingEmailProvider()
    monkeypatch.setattr("app.services.auth_service.get_email_provider", lambda: fake_email)

    res = client.post("/api/v1/auth/forgot-password", json={"email": register_payload["email"]})
    assert res.status_code == 204
    assert len(fake_email.sent) == 1

    reset_link = fake_email.sent[0]["body"]
    raw_token = reset_link.split("token=")[1].split()[0]

    reset_res = client.post(
        "/api/v1/auth/reset-password", json={"token": raw_token, "new_password": "brand-new-9"}
    )
    assert reset_res.status_code == 204

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": "brand-new-9"},
    )
    assert new_login.status_code == 200


def test_reset_password_with_invalid_token_is_rejected(client):
    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": "brand-new-9"},
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_RESET_TOKEN"
