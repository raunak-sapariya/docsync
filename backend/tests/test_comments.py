from .test_api import _unique_user


def _shared_doc(client, role):
    """An owner, a second user granted `role` on one document, and the doc."""
    owner_token, _, _ = _unique_user(client, "cowner")
    guest_token, guest, guest_email = _unique_user(client, "cguest")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    guest_headers = {"Authorization": f"Bearer {guest_token}"}

    doc = client.post("/documents", json={"title": "Reviewed"}, headers=owner_headers).json()
    res = client.post(
        f"/documents/{doc['id']}/permissions",
        json={"email": guest_email, "role": role},
        headers=owner_headers,
    )
    assert res.status_code == 201, res.text
    return doc, owner_headers, guest_headers, guest


def _anchor(body="Needs a citation."):
    # The server stores anchors opaquely ,it never decodes them, because
    # resolving one needs the live Y.Doc ,so any non-empty string stands in
    # for an encoded Yjs relative position here.
    return {
        "body": body,
        "anchor_start": "cmVsLXN0YXJ0",
        "anchor_end": "cmVsLWVuZA==",
        "quoted_text": "the quick brown fox",
    }


def test_commenter_can_comment_but_not_edit(client):
    doc, _, guest_headers, _ = _shared_doc(client, "commenter")
    doc_id = doc["id"]

    assert client.get(f"/documents/{doc_id}", headers=guest_headers).json()["my_role"] == "commenter"

    res = client.post(f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers)
    assert res.status_code == 201, res.text
    thread = res.json()
    assert thread["resolved"] is False
    assert thread["quoted_text"] == "the quick brown fox"
    assert [c["body"] for c in thread["comments"]] == ["Needs a citation."]

    # ...but still can't touch the document itself
    assert client.patch(
        f"/documents/{doc_id}", json={"title": "Hijacked"}, headers=guest_headers
    ).status_code == 403
    assert client.delete(f"/documents/{doc_id}", headers=guest_headers).status_code == 403


def test_viewer_can_read_comments_but_not_write(client):
    doc, owner_headers, guest_headers, _ = _shared_doc(client, "viewer")
    doc_id = doc["id"]

    thread = client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=owner_headers
    ).json()
    tid = thread["id"]

    # A viewer sees discussion on text they can already read...
    res = client.get(f"/documents/{doc_id}/comments", headers=guest_headers)
    assert res.status_code == 200
    assert any(t["id"] == tid for t in res.json())

    # ...but can't start a thread, reply to one, or resolve one
    assert client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers
    ).status_code == 403
    assert client.post(
        f"/documents/{doc_id}/comments/{tid}/replies",
        json={"body": "me too"},
        headers=guest_headers,
    ).status_code == 403
    assert client.patch(
        f"/documents/{doc_id}/comments/{tid}",
        json={"resolved": True},
        headers=guest_headers,
    ).status_code == 403


def test_stranger_cannot_see_or_create_comments(client):
    doc, _, _, _ = _shared_doc(client, "viewer")
    doc_id = doc["id"]
    stranger_token, _, _ = _unique_user(client, "stranger")
    stranger_headers = {"Authorization": f"Bearer {stranger_token}"}

    assert client.get(f"/documents/{doc_id}/comments", headers=stranger_headers).status_code == 403
    assert client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=stranger_headers
    ).status_code == 403


def test_reply_resolve_and_reopen(client):
    doc, owner_headers, guest_headers, guest = _shared_doc(client, "commenter")
    doc_id = doc["id"]

    tid = client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers
    ).json()["id"]

    # Owner replies -- both messages come back in order, with usernames attached
    res = client.post(
        f"/documents/{doc_id}/comments/{tid}/replies",
        json={"body": "Added one."},
        headers=owner_headers,
    )
    assert res.status_code == 201, res.text
    assert [c["body"] for c in res.json()["comments"]] == ["Needs a citation.", "Added one."]
    assert all(c["username"] for c in res.json()["comments"])

    # A commenter -- not only the thread's author -- can resolve
    res = client.patch(
        f"/documents/{doc_id}/comments/{tid}", json={"resolved": True}, headers=guest_headers
    )
    assert res.status_code == 200
    assert res.json()["resolved"] is True
    assert res.json()["resolved_by"] == guest["id"]

    # Resolved threads can be filtered out
    open_only = client.get(
        f"/documents/{doc_id}/comments?include_resolved=false", headers=guest_headers
    ).json()
    assert all(t["id"] != tid for t in open_only)

    # Reopening clears who resolved it
    res = client.patch(
        f"/documents/{doc_id}/comments/{tid}", json={"resolved": False}, headers=owner_headers
    )
    assert res.json()["resolved"] is False
    assert res.json()["resolved_by"] is None


def test_resolving_twice_keeps_the_first_resolver(client):
    doc, owner_headers, guest_headers, guest = _shared_doc(client, "commenter")
    doc_id = doc["id"]
    tid = client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers
    ).json()["id"]

    first = client.patch(
        f"/documents/{doc_id}/comments/{tid}", json={"resolved": True}, headers=guest_headers
    ).json()
    second = client.patch(
        f"/documents/{doc_id}/comments/{tid}", json={"resolved": True}, headers=owner_headers
    ).json()

    assert first["resolved_by"] == guest["id"]
    assert second["resolved_by"] == guest["id"]
    assert second["resolved_at"] == first["resolved_at"]


def test_comment_deletion_rules(client):
    doc, owner_headers, guest_headers, _ = _shared_doc(client, "commenter")
    doc_id = doc["id"]
    other_token, _, other_email = _unique_user(client, "second_commenter")
    other_headers = {"Authorization": f"Bearer {other_token}"}
    client.post(
        f"/documents/{doc_id}/permissions",
        json={"email": other_email, "role": "commenter"},
        headers=owner_headers,
    )

    thread = client.post(
        f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers
    ).json()
    tid = thread["id"]
    opener_id = thread["comments"][0]["id"]
    reply_id = client.post(
        f"/documents/{doc_id}/comments/{tid}/replies",
        json={"body": "second voice"},
        headers=other_headers,
    ).json()["comments"][1]["id"]

    # The opening comment can't go on its own -- that would orphan the replies
    assert client.delete(
        f"/documents/{doc_id}/comments/{tid}/replies/{opener_id}", headers=guest_headers
    ).status_code == 400

    # One commenter can't delete another's reply...
    assert client.delete(
        f"/documents/{doc_id}/comments/{tid}/replies/{reply_id}", headers=guest_headers
    ).status_code == 403
    # ...but its author can
    assert client.delete(
        f"/documents/{doc_id}/comments/{tid}/replies/{reply_id}", headers=other_headers
    ).status_code == 204

    # A commenter can't delete someone else's thread; the document owner can
    assert client.delete(
        f"/documents/{doc_id}/comments/{tid}", headers=other_headers
    ).status_code == 403
    assert client.delete(
        f"/documents/{doc_id}/comments/{tid}", headers=owner_headers
    ).status_code == 204
    assert client.get(f"/documents/{doc_id}/comments", headers=owner_headers).json() == []


def test_deleting_document_removes_its_comments(client):
    doc, owner_headers, guest_headers, _ = _shared_doc(client, "commenter")
    doc_id = doc["id"]
    client.post(f"/documents/{doc_id}/comments", json=_anchor(), headers=guest_headers)

    assert client.delete(f"/documents/{doc_id}", headers=owner_headers).status_code == 204
    # The document is gone, and its threads went with it
    assert client.get(f"/documents/{doc_id}/comments", headers=owner_headers).status_code == 404


def test_empty_comment_body_rejected(client):
    doc, owner_headers, _, _ = _shared_doc(client, "commenter")
    payload = _anchor()
    payload["body"] = ""
    assert client.post(
        f"/documents/{doc['id']}/comments", json=payload, headers=owner_headers
    ).status_code == 422
