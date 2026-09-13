def test_get_me_requires_authentication(client):
    res = client.get("/api/v1/users/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_get_me_returns_current_user(client, auth_headers, register_payload):
    res = client.get("/api/v1/users/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["email"] == register_payload["email"]


def test_update_profile_changes_full_name(client, auth_headers):
    res = client.patch("/api/v1/users/me", json={"full_name": "Jane R. Doe"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["full_name"] == "Jane R. Doe"


def test_change_password_then_login_with_new_password(client, auth_headers, register_payload):
    res = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": register_payload["password"], "new_password": "another-new-9"},
        headers=auth_headers,
    )
    assert res.status_code == 204

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": register_payload["password"]},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": register_payload["email"], "password": "another-new-9"},
    )
    assert new_login.status_code == 200


def test_change_password_rejects_wrong_current_password(client, auth_headers):
    res = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "totally-wrong-1", "new_password": "another-new-9"},
        headers=auth_headers,
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_delete_account_requires_correct_password(client, auth_headers):
    res = client.request(
        "DELETE", "/api/v1/users/me", json={"password": "totally-wrong-1"}, headers=auth_headers
    )
    assert res.status_code == 401


def test_delete_account_removes_user_and_invalidates_session(
    client, auth_headers, register_payload
):
    res = client.request(
        "DELETE",
        "/api/v1/users/me",
        json={"password": register_payload["password"]},
        headers=auth_headers,
    )
    assert res.status_code == 204

    me_res = client.get("/api/v1/users/me", headers=auth_headers)
    assert me_res.status_code == 401
