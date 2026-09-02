import uuid


def _unique_user(client, role_hint="user"):
    suffix = uuid.uuid4().hex[:8]
    payload = {
        "username": f"{role_hint}_{suffix}",
        "email": f"{role_hint}_{suffix}@test.com",
        "password": "hunter2pass",
    }
    res = client.post("/auth/register", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    return body["access_token"], body["user"], payload["email"]


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_register_and_me(client):
    token, user, _ = _unique_user(client)
    res = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["id"] == user["id"]


def test_duplicate_registration_rejected(client):
    _, _, email = _unique_user(client)
    res = client.post(
        "/auth/register",
        json={"username": "someoneelse", "email": email, "password": "hunter2pass"},
    )
    assert res.status_code == 409


def test_wrong_password_rejected(client):
    _, _, email = _unique_user(client)
    res = client.post("/auth/login", json={"email": email, "password": "definitely-wrong"})
    assert res.status_code == 401


def test_create_and_list_document(client):
    token, _, _ = _unique_user(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post("/documents", json={"title": "My Doc"}, headers=headers)
    assert res.status_code == 201
    doc = res.json()
    assert doc["my_role"] == "owner"

    res = client.get("/documents", headers=headers)
    assert res.status_code == 200
    assert any(d["id"] == doc["id"] for d in res.json())


def test_permission_enforcement_and_sharing(client):
    owner_token, _, _ = _unique_user(client, "owner")
    other_token, _, other_email = _unique_user(client, "other")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    other_headers = {"Authorization": f"Bearer {other_token}"}

    doc = client.post("/documents", json={"title": "Shared"}, headers=owner_headers).json()

    # No access yet
    res = client.get(f"/documents/{doc['id']}", headers=other_headers)
    assert res.status_code == 403

    # Share as editor
    res = client.post(
        f"/documents/{doc['id']}/permissions",
        json={"email": other_email, "role": "editor"},
        headers=owner_headers,
    )
    assert res.status_code == 201

    # Now has access
    res = client.get(f"/documents/{doc['id']}", headers=other_headers)
    assert res.status_code == 200
    assert res.json()["my_role"] == "editor"

    # Non-owner can't manage sharing
    res = client.get(f"/documents/{doc['id']}/permissions", headers=other_headers)
    assert res.status_code == 403

    # Non-owner can't delete
    res = client.delete(f"/documents/{doc['id']}", headers=other_headers)
    assert res.status_code == 403


def test_unauthenticated_request_rejected(client):
    res = client.get("/documents")
    assert res.status_code == 401


def test_logout_revokes_token(client):
    token, _, _ = _unique_user(client)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/auth/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 204
    # same token should no longer work
    assert client.get("/auth/me", headers=headers).status_code == 401
