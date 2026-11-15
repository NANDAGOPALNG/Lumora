"""Stage 6B: GET /api/v1/dashboard/summary.

Real FastAPI app, real JWT auth, in-memory SQLite (see tests/_support.py).
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import event

from app.models.connector import Connector
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.workspace import Workspace
from tests._support import harness  # noqa: F401 - pytest fixture

URL = "/api/v1/dashboard/summary"
NOW = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _doc(workspace, name, status=DocumentStatus.INDEXED, chunks=0, at=NOW, connector_id=None):
    return Document(
        id=uuid4(), workspace_id=workspace.id, filename=name, file_type=name.rsplit(".", 1)[-1],
        file_size=1, status=status, chunk_count=chunks, uploaded_at=at, storage_path=f"/x/{uuid4()}",
        connector_id=connector_id,
    )


def _add(h, *rows):
    async def go():
        async with h.session_factory() as s:
            s.add_all(rows)
            await s.commit()

    h.run(go())


def _get(h, user=None):
    headers = h.headers(user) if user is not None else {}
    return h.client.get(URL, headers=headers)


def test_requires_authentication(harness):
    assert _get(harness).status_code == 401
    bad = harness.client.get(URL, headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401


def test_user_with_no_data_gets_zeros_and_empty_activity(harness):
    # user B has one workspace and nothing else; make a brand-new user with none
    from app.models.user import User

    lonely = User(id=uuid4(), email="lonely@example.com", name="L")
    _add(harness, lonely)
    body = _get(harness, lonely).json()
    assert body == {
        "stats": {"workspaces": 0, "documents": 0, "indexed_chunks": 0, "conversations": 0},
        "recent_activity": [],
    }


def test_response_shape_for_seeded_user_without_activity(harness):
    body = _get(harness, harness.user_a).json()
    assert set(body) == {"stats", "recent_activity"}
    assert set(body["stats"]) == {"workspaces", "documents", "indexed_chunks", "conversations"}
    assert body["stats"]["workspaces"] == 1
    assert body["recent_activity"] == []


def test_statistics_across_workspaces_and_statuses(harness):
    ws2 = Workspace(id=uuid4(), user_id=harness.user_a.id, name="WS-A2")
    _add(harness, ws2)
    _add(
        harness,
        _doc(harness.workspace_a, "a.pdf", DocumentStatus.INDEXED, 10),
        _doc(harness.workspace_a, "b.txt", DocumentStatus.INDEXED, 5),
        _doc(ws2, "c.md", DocumentStatus.INDEXED, 7),
        _doc(ws2, "d.md", DocumentStatus.FAILED, 99),      # failed: counted as doc, not chunks
        _doc(ws2, "e.md", DocumentStatus.PROCESSING, 50),  # in progress: same
        _doc(ws2, "f.md", DocumentStatus.UPLOADED, 0),
        Conversation(id=uuid4(), user_id=harness.user_a.id, title="one", created_at=NOW),
        Conversation(id=uuid4(), user_id=harness.user_a.id, title="two", created_at=NOW),
    )
    stats = _get(harness, harness.user_a).json()["stats"]
    assert stats == {"workspaces": 2, "documents": 6, "indexed_chunks": 22, "conversations": 2}


def test_user_isolation_for_stats_and_activity(harness):
    conn_b = Connector(
        id=uuid4(), workspace_id=harness.workspace_b.id, type="github",
        connection_name="b/secret-repo", github_repo="b/secret-repo", active=True, last_synced=NOW,
    )
    _add(
        harness,
        _doc(harness.workspace_b, "b-private.pdf", chunks=40),
        Conversation(id=uuid4(), user_id=harness.user_b.id, title="b-private-chat", created_at=NOW),
        conn_b,
    )
    a = _get(harness, harness.user_a).json()
    assert a["stats"] == {"workspaces": 1, "documents": 0, "indexed_chunks": 0, "conversations": 0}
    assert a["recent_activity"] == []

    b = _get(harness, harness.user_b).json()
    assert b["stats"] == {"workspaces": 1, "documents": 1, "indexed_chunks": 40, "conversations": 1}
    assert len(b["recent_activity"]) == 3
    # and A's data never leaks into B's view either
    _add(harness, _doc(harness.workspace_a, "a-private.pdf", chunks=3))
    assert "a-private" not in _get(harness, harness.user_b).text
    assert "b-private" not in _get(harness, harness.user_a).text
    assert "secret-repo" not in _get(harness, harness.user_a).text


def test_recent_activity_merges_types_sorted_newest_first(harness):
    conn = Connector(
        id=uuid4(), workspace_id=harness.workspace_a.id, type="github",
        connection_name="octo/repo", github_repo="octo/repo", active=True,
        last_synced=NOW - timedelta(hours=1),
    )
    drive = Connector(
        id=uuid4(), workspace_id=harness.workspace_a.id, type="google_drive",
        connection_name="My Drive", active=True, last_synced=NOW - timedelta(hours=4),
    )
    never = Connector(
        id=uuid4(), workspace_id=harness.workspace_a.id, type="github",
        connection_name="octo/never", github_repo="octo/never", active=True, last_synced=None,
    )
    d1 = _doc(harness.workspace_a, "old.pdf", at=NOW - timedelta(hours=5))
    d2 = _doc(harness.workspace_a, "new.pdf", at=NOW)
    conv = Conversation(id=uuid4(), user_id=harness.user_a.id, title="How do I deploy?", created_at=NOW - timedelta(hours=2))
    untitled = Conversation(id=uuid4(), user_id=harness.user_a.id, title=None, created_at=NOW - timedelta(hours=3))
    _add(harness, conn, drive, never, d1, d2, conv, untitled)

    activity = _get(harness, harness.user_a).json()["recent_activity"]
    assert [a["title"] for a in activity] == [
        "Uploaded new.pdf",
        "Synced octo/repo",
        "Started conversation: How do I deploy?",
        "Started conversation: Untitled conversation",
        "Synced My Drive",
        "Uploaded old.pdf",
    ]
    assert [a["type"] for a in activity] == [
        "document_uploaded", "connector_synced", "conversation_created",
        "conversation_created", "connector_synced", "document_uploaded",
    ]
    times = [a["created_at"] for a in activity]
    assert times == sorted(times, reverse=True)
    by_type = {a["id"]: a for a in activity}
    assert by_type[f"document:{d2.id}"]["workspace_id"] == str(harness.workspace_a.id)
    assert by_type[f"document:{d2.id}"]["link"] == f"/workspaces/{harness.workspace_a.id}"
    assert by_type[f"document:{d2.id}"]["description"] == "Document added to WS-A"
    assert by_type[f"connector:{conn.id}"]["link"] == "/integrations"
    assert by_type[f"connector:{conn.id}"]["description"] == "GitHub repository synced in WS-A"
    assert by_type[f"connector:{drive.id}"]["description"] == "Google Drive synced in WS-A"
    assert by_type[f"conversation:{conv.id}"]["link"] == f"/chat?c={conv.id}"
    assert by_type[f"conversation:{conv.id}"]["workspace_id"] is None
    # a connector that never synced produced no activity (nothing fabricated)
    assert f"connector:{never.id}" not in by_type


def test_connector_synced_documents_do_not_flood_the_feed(harness):
    conn = Connector(
        id=uuid4(), workspace_id=harness.workspace_a.id, type="github",
        connection_name="octo/repo", github_repo="octo/repo", active=True, last_synced=NOW,
    )
    _add(harness, conn)
    _add(harness, *[_doc(harness.workspace_a, f"f{i}.py", at=NOW, connector_id=conn.id) for i in range(30)])
    body = _get(harness, harness.user_a).json()
    assert body["stats"]["documents"] == 30   # still counted in the totals
    assert [a["type"] for a in body["recent_activity"]] == ["connector_synced"]


def test_activity_is_limited_to_ten_newest(harness):
    rows = [
        _doc(harness.workspace_a, f"d{i}.txt", at=NOW - timedelta(minutes=i)) for i in range(8)
    ] + [
        Conversation(id=uuid4(), user_id=harness.user_a.id, title=f"c{i}", created_at=NOW - timedelta(minutes=i, seconds=30))
        for i in range(8)
    ]
    _add(harness, *rows)
    activity = _get(harness, harness.user_a).json()["recent_activity"]
    assert len(activity) == 10
    times = [a["created_at"] for a in activity]
    assert times == sorted(times, reverse=True)
    assert activity[0]["title"] == "Uploaded d0.txt"
    # the 10 newest of the 16 are d0..d4 interleaved with c0..c4
    assert {a["title"] for a in activity} == (
        {f"Uploaded d{i}.txt" for i in range(5)} | {f"Started conversation: c{i}" for i in range(5)}
    )


def test_titles_are_shortened_and_never_contain_content_or_credentials(harness):
    long_title = "x" * 300
    _add(harness, Conversation(id=uuid4(), user_id=harness.user_a.id, title=long_title, created_at=NOW))
    activity = _get(harness, harness.user_a).json()["recent_activity"]
    assert len(activity[0]["title"]) < 120
    assert set(activity[0]) == {"id", "type", "title", "description", "created_at", "workspace_id", "link"}


def test_query_count_does_not_grow_with_data_volume(harness):
    def count_statements():
        statements = []

        def before(conn, cursor, statement, *_):
            statements.append(statement)

        event.listen(harness.engine.sync_engine, "before_cursor_execute", before)
        try:
            assert _get(harness, harness.user_a).status_code == 200
        finally:
            event.remove(harness.engine.sync_engine, "before_cursor_execute", before)
        return len(statements)

    small = count_statements()
    ws = [Workspace(id=uuid4(), user_id=harness.user_a.id, name=f"W{i}") for i in range(15)]
    _add(harness, *ws)
    _add(
        harness,
        *[_doc(w, f"f{i}.md", chunks=2) for i, w in enumerate(ws)],
        *[Conversation(id=uuid4(), user_id=harness.user_a.id, title=f"c{i}", created_at=NOW) for i in range(20)],
    )
    large = count_statements()
    assert large == small
    assert large <= 10
