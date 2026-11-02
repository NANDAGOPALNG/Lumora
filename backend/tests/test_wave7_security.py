"""Wave 7 authentication/authorization and hardening regression tests.

Runs the real FastAPI app with real JWT authentication over an
in-memory SQLite database; only external systems are faked (see
tests/_support.py).
"""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

import main
from app.config.settings import Settings

SECRET = os.environ["SECRET_KEY"]


def _protected_operations():
    spec = main.app.openapi()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            if operation.get("security"):
                yield method.upper(), path


def _fill(path):
    return path.replace("{conversation_id}", str(uuid.uuid4())).replace(
        "{document_id}", str(uuid.uuid4())
    ).replace("{workspace_id}", str(uuid.uuid4())).replace(
        "{connector_id}", str(uuid.uuid4())
    )


def test_every_protected_route_rejects_missing_and_invalid_tokens(harness):
    operations = list(_protected_operations())
    assert len(operations) >= 20  # guards against the discovery itself silently breaking
    for method, path in operations:
        url = "/api/v1" + _fill(path).split("/api/v1", 1)[-1] if path.startswith("/api/v1") else _fill(path)
        for headers in ({}, {"Authorization": "Bearer not-a-jwt"}):
            response = harness.client.request(method, url, headers=headers)
            assert response.status_code == 401, (method, path, headers)
            assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "claims,secret",
    [
        ({"type": "access", "exp": -5}, SECRET),            # expired
        ({"type": "refresh", "exp": 5}, SECRET),            # wrong token type
        ({"exp": 5}, SECRET),                               # missing type
        ({"type": "access", "exp": 5}, "some-other-secret"),  # wrong signature
    ],
)
def test_invalid_jwts_are_rejected(harness, claims, secret):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(harness.user_a.id),
        "type": claims.get("type"),
        "exp": now + timedelta(minutes=claims["exp"]),
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    token = jwt.encode(payload, secret, algorithm="HS256")
    response = harness.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_token_for_unknown_user_or_non_uuid_subject_is_rejected(harness):
    ghost = harness.token_manager.create_access_token(uuid.uuid4())
    response = harness.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {ghost}"})
    assert response.status_code == 401

    bad_sub = jwt.encode(
        {"sub": "not-a-uuid", "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        SECRET,
        algorithm="HS256",
    )
    response = harness.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad_sub}"})
    assert response.status_code == 401


def test_cross_user_access_is_not_found_everywhere(harness):
    a, b = harness.user_a, harness.user_b
    ws_a = harness.workspace_a.id
    client = harness.client

    upload = client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(ws_a)},
        files={"file": ("a.txt", b"alpha content", "text/plain")},
        headers=harness.headers(a),
    )
    assert upload.status_code == 201
    doc_id = upload.json()["id"]
    hb = harness.headers(b)

    attempts = [
        ("PATCH", f"/api/v1/workspaces/{ws_a}", {"json": {"name": "hijack"}}),
        ("DELETE", f"/api/v1/workspaces/{ws_a}", {}),
        ("GET", f"/api/v1/documents?workspace_id={ws_a}", {}),
        ("POST", "/api/v1/documents/upload",
         {"data": {"workspace_id": str(ws_a)}, "files": {"file": ("b.txt", b"x", "text/plain")}}),
        ("GET", f"/api/v1/documents/{doc_id}", {}),
        ("DELETE", f"/api/v1/documents/{doc_id}", {}),
        ("POST", f"/api/v1/documents/{doc_id}/reindex", {}),
        ("POST", "/api/v1/search", {"json": {"query": "alpha", "workspace_id": str(ws_a)}}),
        ("POST", "/api/v1/chat", {"json": {"query": "alpha", "workspace_id": str(ws_a)}}),
        ("GET", f"/api/v1/connectors?workspace_id={ws_a}", {}),
        ("POST", "/api/v1/connectors/google-drive",
         {"json": {"workspace_id": str(ws_a), "access_token": "tok"}}),
        ("POST", "/api/v1/connectors/github",
         {"json": {"workspace_id": str(ws_a), "github_token": "tok", "repo_full_name": "o/r"}}),
    ]
    for method, url, kwargs in attempts:
        response = client.request(method, url, headers=hb, **kwargs)
        assert response.status_code == 404, (method, url, response.status_code, response.text)
        assert response.json()["success"] is False

    # The owner's data was not affected by any of that.
    assert client.get(f"/api/v1/documents/{doc_id}", headers=harness.headers(a)).status_code == 200
    assert client.get(f"/api/v1/documents?workspace_id={ws_a}", headers=harness.headers(a)).status_code == 200


def test_document_response_does_not_expose_server_storage_path(harness):
    upload = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("a.txt", b"alpha content", "text/plain")},
        headers=harness.headers(harness.user_a),
    )
    assert upload.status_code == 201
    assert "storage_path" not in upload.json()
    assert "storage" not in upload.text.lower()

    listing = harness.client.get(
        f"/api/v1/documents?workspace_id={harness.workspace_a.id}",
        headers=harness.headers(harness.user_a),
    )
    assert all("storage_path" not in item for item in listing.json())


def test_oversized_upload_is_rejected_with_413(harness, monkeypatch):
    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")
    response = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("big.txt", b"x" * (1024 * 1024 + 10), "text/plain")},
        headers=harness.headers(harness.user_a),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_reads_a_bounded_amount_of_the_request_body(harness, monkeypatch):
    """The route must not buffer an arbitrarily large body just to reject it."""
    from starlette.datastructures import UploadFile

    monkeypatch.setenv("MAX_DOCUMENT_SIZE_MB", "1")
    limit = 1024 * 1024
    read_sizes = []
    original_read = UploadFile.read

    async def recording_read(self, size=-1):
        read_sizes.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", recording_read)
    response = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("big.txt", b"x" * (limit * 3), "text/plain")},
        headers=harness.headers(harness.user_a),
    )
    assert response.status_code == 413
    assert read_sizes == [limit + 1]


# --- workspace validation (regression: PATCH name=null used to return 500) -------------

def test_workspace_patch_with_null_name_is_a_validation_error_not_a_500(harness):
    response = harness.client.patch(
        f"/api/v1/workspaces/{harness.workspace_a.id}",
        json={"name": None},
        headers=harness.headers(harness.user_a),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_workspace_names_are_validated(harness, name):
    headers = harness.headers(harness.user_a)
    assert harness.client.post("/api/v1/workspaces", json={"name": name}, headers=headers).status_code == 422
    assert harness.client.patch(
        f"/api/v1/workspaces/{harness.workspace_a.id}", json={"name": name}, headers=headers
    ).status_code == 422


def test_workspace_name_is_trimmed_and_valid_updates_still_work(harness):
    headers = harness.headers(harness.user_a)
    created = harness.client.post("/api/v1/workspaces", json={"name": "  Research  "}, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Research"
    patched = harness.client.patch(
        f"/api/v1/workspaces/{harness.workspace_a.id}", json={"name": "Renamed"}, headers=headers
    )
    assert patched.status_code == 200 and patched.json()["name"] == "Renamed"
    # An empty PATCH body (nothing to update) remains valid.
    assert harness.client.patch(
        f"/api/v1/workspaces/{harness.workspace_a.id}", json={}, headers=headers
    ).status_code == 200


def test_drive_root_folder_id_must_look_like_a_drive_id(harness):
    headers = harness.headers(harness.user_a)
    for bad in ["../about", "abc/export", "x' or 'y", "a b", "a" * 200]:
        response = harness.client.post(
            "/api/v1/connectors/google-drive",
            json={"workspace_id": str(harness.workspace_a.id), "access_token": "tok", "root_folder_id": bad},
            headers=headers,
        )
        assert response.status_code == 422, bad


# --- workspace deletion cleans up files and vectors --------------------------------------

def test_deleting_a_workspace_removes_document_files_and_vectors(harness):
    headers = harness.headers(harness.user_a)
    upload = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("a.txt", b"alpha content about orchids", "text/plain")},
        headers=headers,
    )
    doc_id = uuid.UUID(upload.json()["id"])
    assert harness.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=headers).status_code == 200
    assert harness.vector_store.points_by_document.get(doc_id)

    stored_files = [f for f in os.listdir(os.environ["DOCUMENT_STORAGE_PATH"])]
    assert len(stored_files) == 1

    response = harness.client.delete(f"/api/v1/workspaces/{harness.workspace_a.id}", headers=headers)
    assert response.status_code == 200

    assert os.listdir(os.environ["DOCUMENT_STORAGE_PATH"]) == []
    assert doc_id in harness.vector_store.deleted_document_ids
    assert doc_id not in harness.vector_store.points_by_document


def test_deleting_someone_elses_workspace_cleans_up_nothing(harness):
    owner = harness.headers(harness.user_a)
    upload = harness.client.post(
        "/api/v1/documents/upload",
        data={"workspace_id": str(harness.workspace_a.id)},
        files={"file": ("a.txt", b"alpha", "text/plain")},
        headers=owner,
    )
    doc_id = uuid.UUID(upload.json()["id"])
    harness.client.post(f"/api/v1/documents/{doc_id}/reindex", headers=owner)
    # (reindexing itself replaces vectors, so snapshot the delete calls so far)
    deletes_before = list(harness.vector_store.deleted_document_ids)

    response = harness.client.delete(
        f"/api/v1/workspaces/{harness.workspace_a.id}", headers=harness.headers(harness.user_b)
    )
    assert response.status_code == 404
    assert len(os.listdir(os.environ["DOCUMENT_STORAGE_PATH"])) == 1
    assert harness.vector_store.deleted_document_ids == deletes_before
    assert harness.vector_store.points_by_document.get(doc_id)


# --- error handling, CORS, configuration --------------------------------------------------

def test_unhandled_errors_are_logged_but_not_leaked(harness, monkeypatch, caplog):
    from app.services.workspace_service import WorkspaceService

    async def boom(self, user_id):
        raise RuntimeError("db password=hunter2 host=internal-db")

    monkeypatch.setattr(WorkspaceService, "get_workspaces_by_user", boom)
    with caplog.at_level(logging.ERROR):
        response = harness.client.get("/api/v1/workspaces", headers=harness.headers(harness.user_a))

    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": {"code": "INTERNAL_SERVER_ERROR", "message": "An unexpected error occurred"},
    }
    assert "hunter2" not in response.text
    assert any("hunter2" in (r.exc_text or "") or "hunter2" in str(r.exc_info) for r in caplog.records)


def test_cors_allows_the_configured_frontend_origin_only(harness):
    allowed = harness.client.options(
        "/api/v1/workspaces",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-credentials" not in allowed.headers

    denied = harness.client.options(
        "/api/v1/workspaces",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_cors_origins_setting_is_parsed(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com, https://admin.example.com ,")
    assert Settings.get_instance().cors_origin_list == [
        "https://app.example.com",
        "https://admin.example.com",
    ]


def test_production_settings_fail_fast(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "")

    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.get_instance()

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db/lumora")
    monkeypatch.setenv("SECRET_KEY", "too-short")

    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings.get_instance()

    monkeypatch.setenv("SECRET_KEY", "s" * 40)
    assert Settings.get_instance().is_production()

def test_async_engine_is_created_once_and_reused(monkeypatch, tmp_path):
    import asyncio

    from app.database import session as session_module

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/engine.db")

    async def scenario():
        await session_module.dispose_engine()
        first = await session_module.get_async_engine()
        second = await session_module.get_async_engine()
        factory_one = await session_module._get_session_factory()
        factory_two = await session_module._get_session_factory()
        await session_module.dispose_engine()
        third = await session_module.get_async_engine()
        await session_module.dispose_engine()
        return first, second, third, factory_one, factory_two

    first, second, third, factory_one, factory_two = asyncio.run(scenario())
    assert first is second
    assert factory_one is factory_two
    assert third is not first  # a fresh engine after shutdown disposal
