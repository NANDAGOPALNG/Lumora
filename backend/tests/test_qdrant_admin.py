"""Tests for scripts/qdrant_admin.py (status / init / check-vectors / reset).

Uses qdrant-client's in-memory mode, which is a real (local) Qdrant engine:
nothing here touches the network or any real Qdrant cluster.
"""

import asyncio
import random
import uuid

import pytest
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.vector_store.store import COLLECTION_NAME, QdrantIntegrationError
from scripts import qdrant_admin as admin

SECRET = "qdrant-api-key-SECRET-123"


def run(coro):
    return asyncio.run(coro)


def new_client():
    return AsyncQdrantClient(":memory:")


def unit_vector(seed, size=1024):
    rng = random.Random(seed)
    vec = [rng.uniform(-1, 1) for _ in range(size)]
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec]


async def create_good_collection(client, size=1024):
    await client.create_collection(
        COLLECTION_NAME, vectors_config=qmodels.VectorParams(size=size, distance=qmodels.Distance.COSINE)
    )


async def add_point(client, vector, *, marker=None, point_id=None):
    payload = {"embedding_model": marker} if marker else {}
    point_id = point_id or str(uuid.uuid4())
    await client.upsert(COLLECTION_NAME, [qmodels.PointStruct(id=point_id, vector=vector, payload=payload)], wait=True)
    return point_id


async def count(client):
    return (await client.count(COLLECTION_NAME, exact=True)).count


# --------------------------------------------------------------------------- status


def test_status_of_a_missing_collection_suggests_init():
    async def go():
        client = new_client()
        report = await admin.get_status(client)
        return report, admin.format_status(report, ":memory:")

    report, text = run(go())
    assert report["exists"] is False and "does not exist yet" in text and "init" in text


def test_status_reports_config_count_and_marker_tally():
    async def go():
        client = new_client()
        await create_good_collection(client)
        await add_point(client, unit_vector(1), marker="jina-embeddings-v3")
        await add_point(client, unit_vector(2), marker="jina-embeddings-v3")
        await add_point(client, unit_vector(3))  # written before the marker existed
        report = await admin.get_status(client)
        return report, admin.format_status(report, "cluster.example")

    report, text = run(go())
    assert report["config_ok"] is True and report["vector_size"] == 1024 and report["distance"] == "Cosine"
    assert report["points_count"] == 3
    assert report["embedding_models"] == {"jina-embeddings-v3": 2, admin.MISSING_MARKER: 1}
    assert "check-vectors" in text and "may be old BGE-M3" in text  # the unmarked point is flagged


def test_status_flags_an_incompatible_configuration_without_changing_it():
    async def go():
        client = new_client()
        await create_good_collection(client, size=384)
        await client.upsert(COLLECTION_NAME, [qmodels.PointStruct(id=str(uuid.uuid4()), vector=[0.1] * 384)], wait=True)
        report = await admin.get_status(client)
        return report, await count(client)

    report, points = run(go())
    assert report["config_ok"] is False and "384" in report["config_error"]
    assert points == 1


def test_status_of_an_empty_collection_says_fresh_start():
    async def go():
        client = new_client()
        await create_good_collection(client)
        return admin.format_status(await admin.get_status(client), "h")

    assert "fresh start" in run(go())


# --------------------------------------------------------------------------- init


def test_init_creates_the_collection_with_1024_cosine():
    async def go():
        client = new_client()
        result = await admin.init_collection(client)
        return result, await admin.get_status(client)

    result, report = run(go())
    assert result == {"existed": False}
    assert report["exists"] and report["config_ok"] and report["points_count"] == 0


def test_init_is_idempotent_and_never_touches_existing_points():
    async def go():
        client = new_client()
        await create_good_collection(client)
        point_id = await add_point(client, unit_vector(1), marker="jina-embeddings-v3")
        result = await admin.init_collection(client)
        again = await admin.init_collection(client)
        stored = await client.retrieve(COLLECTION_NAME, ids=[point_id])
        return result, again, await count(client), stored

    result, again, points, stored = run(go())
    assert result == {"existed": True} and again == {"existed": True}
    assert points == 1 and stored[0].payload == {"embedding_model": "jina-embeddings-v3"}


def test_init_refuses_an_incompatible_collection_and_leaves_it_alone():
    async def go():
        client = new_client()
        await create_good_collection(client, size=384)
        await client.upsert(COLLECTION_NAME, [qmodels.PointStruct(id=str(uuid.uuid4()), vector=[0.1] * 384)], wait=True)
        with pytest.raises(QdrantIntegrationError, match="incompatible"):
            await admin.init_collection(client)
        info = await client.get_collection(COLLECTION_NAME)
        return info.config.params.vectors.size, await count(client)

    size, points = run(go())
    assert size == 384 and points == 1  # not recreated, not emptied


# --------------------------------------------------------------------------- check-vectors


def fixed_text_embedding(text):
    return unit_vector(sum(map(ord, text)))


async def fake_embed(texts, task="retrieval.passage"):
    assert task == "retrieval.passage"
    return [fixed_text_embedding(t) for t in texts]


def contents_loader(mapping):
    async def load(ids):
        return {i: mapping[i] for i in ids if i in mapping}

    return load


def test_check_vectors_recognises_jina_vectors():
    async def go():
        client = new_client()
        await create_good_collection(client)
        texts = {}
        for text in ("alpha text", "beta text", "gamma text"):
            pid = uuid.uuid4()
            await add_point(client, fixed_text_embedding(text), point_id=str(pid))
            texts[pid] = text
        return await admin.check_vectors(client, contents_loader(texts), fake_embed, sample=3)

    result = run(go())
    assert result["verdict"] == "JINA" and len(result["examined"]) == 3
    assert all(item["cosine"] > 0.999 for item in result["examined"])


def test_check_vectors_recognises_old_vectors_from_another_model():
    async def go():
        client = new_client()
        await create_good_collection(client)
        texts = {}
        for seed, text in enumerate(("alpha text", "beta text", "gamma text")):
            pid = uuid.uuid4()
            await add_point(client, unit_vector(10_000 + seed), point_id=str(pid))  # unrelated vector space
            texts[pid] = text
        return await admin.check_vectors(client, contents_loader(texts), fake_embed, sample=3)

    result = run(go())
    assert result["verdict"] == "NOT_JINA"
    assert "BGE-M3" in admin._VERDICTS["NOT_JINA"]
    assert all(abs(item["cosine"]) < 0.3 for item in result["examined"])


def test_check_vectors_reports_a_mixed_collection():
    async def go():
        client = new_client()
        await create_good_collection(client)
        texts = {}
        good, old = uuid.uuid4(), uuid.uuid4()
        await add_point(client, fixed_text_embedding("good"), point_id=str(good), marker="jina-embeddings-v3")
        await add_point(client, unit_vector(777), point_id=str(old))
        texts = {good: "good", old: "old"}
        return await admin.check_vectors(client, contents_loader(texts), fake_embed, sample=5)

    assert run(go())["verdict"] == "MIXED"


def test_check_vectors_examines_unmarked_points_first():
    async def go():
        client = new_client()
        await create_good_collection(client)
        texts, unmarked = {}, uuid.uuid4()
        for i in range(6):
            pid = uuid.uuid4()
            await add_point(client, fixed_text_embedding(f"t{i}"), point_id=str(pid), marker="jina-embeddings-v3")
            texts[pid] = f"t{i}"
        await add_point(client, unit_vector(5), point_id=str(unmarked))
        texts[unmarked] = "the old one"
        return await admin.check_vectors(client, contents_loader(texts), fake_embed, sample=1), unmarked

    result, unmarked = run(go())
    assert result["examined"][0]["point_id"] == str(unmarked) and result["verdict"] == "NOT_JINA"


def test_check_vectors_handles_orphans_empty_and_missing_collection():
    async def go():
        client = new_client()
        with pytest.raises(admin.AdminError, match="does not exist"):
            await admin.check_vectors(client, contents_loader({}), fake_embed)
        await create_good_collection(client)
        empty = await admin.check_vectors(client, contents_loader({}), fake_embed)
        await add_point(client, unit_vector(1))
        orphan = await admin.check_vectors(client, contents_loader({}), fake_embed)
        return empty, orphan

    empty, orphan = run(go())
    assert empty["verdict"] == "EMPTY"
    assert orphan["verdict"] == "NO_CHUNK_TEXT" and orphan["orphans"] == 1


def test_check_vectors_never_modifies_qdrant():
    async def go():
        client = new_client()
        await create_good_collection(client)
        pid = uuid.uuid4()
        await add_point(client, unit_vector(3), point_id=str(pid))
        before = await client.retrieve(COLLECTION_NAME, ids=[str(pid)], with_vectors=True, with_payload=True)
        await admin.check_vectors(client, contents_loader({pid: "x"}), fake_embed)
        after = await client.retrieve(COLLECTION_NAME, ids=[str(pid)], with_vectors=True, with_payload=True)
        return before, after, await count(client)

    before, after, points = run(go())
    assert before[0].vector == after[0].vector and before[0].payload == after[0].payload and points == 1


# --------------------------------------------------------------------------- reset


def never_prompt(_name):
    raise AssertionError("the user must not be prompted in this scenario")


async def seeded_client():
    client = new_client()
    await create_good_collection(client)
    await add_point(client, unit_vector(1))
    await add_point(client, unit_vector(2))
    return client


def test_reset_is_a_dry_run_by_default_and_deletes_nothing():
    async def go():
        client = await seeded_client()
        result = await admin.reset_collection(
            client, "cluster.example", execute=False, confirm_host=None, confirm_prompt=never_prompt
        )
        return result, await count(client)

    result, points = run(go())
    assert result["executed"] is False and result["points"] == 2 and points == 2
    text = admin.format_reset(result)
    assert "DRY RUN" in text and "NOT touch PostgreSQL" in text and "--confirm-host cluster.example" in text


@pytest.mark.parametrize("confirm_host", [None, "", "other-cluster.example"])
def test_reset_refuses_without_the_correct_host_confirmation(confirm_host):
    async def go():
        client = await seeded_client()
        with pytest.raises(admin.AdminError, match="--confirm-host"):
            await admin.reset_collection(
                client, "cluster.example", execute=True, confirm_host=confirm_host, confirm_prompt=never_prompt
            )
        return await count(client)

    assert run(go()) == 2


def test_reset_refuses_if_the_typed_confirmation_is_wrong():
    async def go():
        client = await seeded_client()
        with pytest.raises(admin.AdminError, match="Confirmation did not match"):
            await admin.reset_collection(
                client, "cluster.example", execute=True, confirm_host="cluster.example",
                confirm_prompt=lambda name: "yes",
            )
        return await count(client)

    assert run(go()) == 2


def test_reset_deletes_only_knowledge_chunks_and_recreates_it_empty_and_valid():
    async def go():
        client = await seeded_client()
        await client.create_collection(
            "someone_elses_collection", vectors_config=qmodels.VectorParams(size=8, distance=qmodels.Distance.DOT)
        )
        await client.upsert("someone_elses_collection", [qmodels.PointStruct(id=str(uuid.uuid4()), vector=[1.0] * 8)], wait=True)
        prompts = []

        def prompt(name):
            prompts.append(name)
            return name

        result = await admin.reset_collection(
            client, "Cluster.Example", execute=True, confirm_host="cluster.example", confirm_prompt=prompt
        )
        status = await admin.get_status(client)
        other = (await client.count("someone_elses_collection", exact=True)).count
        return result, status, other, prompts

    result, status, other, prompts = run(go())
    assert result["executed"] is True and prompts == [COLLECTION_NAME]
    assert status["exists"] and status["config_ok"] and status["points_count"] == 0  # fresh, correct config
    assert other == 1  # a different collection on the same cluster is untouched
    assert "PostgreSQL and Cloudflare R2 were not touched" in admin.format_reset(result)


def test_reset_of_a_missing_collection_just_creates_it():
    async def go():
        client = new_client()
        result = await admin.reset_collection(
            client, "h", execute=True, confirm_host="h", confirm_prompt=lambda n: n
        )
        return result, await admin.get_status(client)

    result, status = run(go())
    assert result["exists"] is False and status["exists"] and status["config_ok"]


# --------------------------------------------------------------------------- CLI wiring


def cli(argv, client, host="cluster.example", prompt=None):
    lines = []
    code = admin.main(argv, make_client=lambda: (client, host), out=lines.append, prompt=prompt or never_prompt)
    return code, "\n".join(lines)


def test_cli_reset_without_flags_is_only_a_dry_run():
    client = new_client()
    run(create_good_collection(client))
    run(add_point(client, unit_vector(1)))
    # one event loop per admin.main() call, so use a fresh in-memory client per call
    code, text = cli(["reset"], client)
    assert code == 0 and "DRY RUN" in text


def test_cli_reset_execute_without_host_confirmation_fails_and_deletes_nothing():
    client = new_client()
    code, text = cli(["reset", "--execute"], client)
    assert code == 1 and "--confirm-host" in text


def test_cli_status_never_prints_credentials(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", f"https://user:{SECRET}@cluster.example:6333")
    monkeypatch.setenv("QDRANT_API_KEY", SECRET)
    client = new_client()
    code, text = cli(["status"], client, host=admin.host_of(f"https://user:{SECRET}@cluster.example:6333"))
    assert code == 0 and SECRET not in text and "cluster.example" in text


def test_cli_errors_do_not_echo_raw_exception_text():
    class Boom:
        async def collection_exists(self, *_):
            raise RuntimeError(f"connect failed for https://x:{SECRET}@host")

        async def close(self):
            pass

    code, text = cli(["status"], Boom())
    assert code == 1 and SECRET not in text and "RuntimeError" in text


def test_cli_reports_missing_qdrant_url():
    def make_client():
        raise admin.AdminError("QDRANT_URL is not configured")

    lines = []
    assert admin.main(["status"], make_client=make_client, out=lines.append) == 2
    assert "QDRANT_URL" in lines[0]


def test_host_of_strips_credentials_paths_and_ports():
    assert admin.host_of("https://abc.cloud.qdrant.io:6333") == "abc.cloud.qdrant.io"
    assert admin.host_of("abc.cloud.qdrant.io") == "abc.cloud.qdrant.io"
    assert admin.host_of("https://u:p@abc.example/some/path?x=1") == "abc.example"
    assert admin.host_of(":memory:") == ":memory:"
    with pytest.raises(admin.AdminError):
        admin.host_of(None)


def test_real_make_client_never_leaks_settings_validation_values(monkeypatch):
    """Invalid settings must produce a short safe error, not pydantic's dump
    (which echoes input values such as secrets)."""
    from app.config.settings import Settings

    def boom(cls):
        raise ValueError("input_value='SUPER-SECRET-KEY-123'")

    monkeypatch.setattr(Settings, "get_instance", classmethod(boom))
    lines = []
    assert admin.main(["status"], out=lines.append) == 2
    text = "\n".join(lines)
    assert "SUPER-SECRET-KEY-123" not in text
    assert "ValueError" in text and ".env" in text


def test_real_make_client_reports_empty_qdrant_url(monkeypatch):
    from app.config.settings import Settings

    class Fake:
        qdrant_url = ""
        qdrant_api_key = ""

    monkeypatch.setattr(Settings, "get_instance", classmethod(lambda cls: Fake()))
    lines = []
    assert admin.main(["status"], out=lines.append) == 2
    assert "QDRANT_URL is not set" in lines[0]
