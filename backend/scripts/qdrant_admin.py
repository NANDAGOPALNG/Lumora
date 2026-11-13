"""Operator commands for Lumora's Qdrant collection (`knowledge_chunks`).

Run from the `backend/` directory:

    python -m scripts.qdrant_admin status
    python -m scripts.qdrant_admin init
    python -m scripts.qdrant_admin check-vectors [--sample 5]
    python -m scripts.qdrant_admin reset                      # dry run only
    python -m scripts.qdrant_admin reset --execute --confirm-host <host>

Commands
--------
status          READ-ONLY. Connection, collection configuration (vector size
                and distance), point count, payload indexes, and which
                embedding model the stored points say they came from.
init            Creates the collection (1024 dims, cosine) and its payload
                indexes if they are missing. NEVER deletes or modifies any
                existing point or collection; an existing collection with an
                incompatible configuration is reported, not replaced.
check-vectors   READ-ONLY (Qdrant and PostgreSQL SELECT only). Re-embeds a few
                stored chunks with the current Jina model and compares them
                with the vectors in Qdrant, to detect leftover BGE-M3 vectors.
                Makes a small number of Jina API calls.
reset           DESTRUCTIVE. Deletes ONLY the `knowledge_chunks` collection
                (every vector in it) and recreates it empty. A dry run unless
                --execute is given; --execute also needs --confirm-host
                matching the Qdrant host and a typed confirmation. Never
                touches PostgreSQL or Cloudflare R2.

Nothing in the application ever calls `reset`; the web app only ever creates a
missing collection (QdrantVectorStore.ensure_collection) and deletes the
points of a single document.
"""

import argparse
import asyncio
import math
import sys
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence
from urllib.parse import urlparse
from uuid import UUID

from qdrant_client import AsyncQdrantClient

from app.vector_store.store import (
    COLLECTION_NAME,
    INDEXED_PAYLOAD_FIELDS,
    VECTOR_DISTANCE,
    VECTOR_SIZE,
    QdrantIntegrationError,
    QdrantVectorStore,
)

MISSING_MARKER = "<no embedding_model marker>"

# Cosine similarity between a stored vector and a fresh Jina embedding of the
# same text. The same model reproduces its own vector (~1.0); a different
# model lives in an unrelated vector space (~0).
MATCH_THRESHOLD = 0.95
MISMATCH_THRESHOLD = 0.5


class AdminError(Exception):
    """A user-facing problem; its message is always safe to print."""


def host_of(url: Optional[str]) -> str:
    """The host part of a Qdrant URL, for display and confirmation. Never
    includes credentials, a path, or a query string."""
    if not url:
        raise AdminError("QDRANT_URL is not configured")
    if url.startswith(":memory:"):
        return ":memory:"
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.hostname or url


def _store_for(client: AsyncQdrantClient) -> QdrantVectorStore:
    store = QdrantVectorStore()
    store._client = client
    return store


# --------------------------------------------------------------------------- status


async def get_status(client: AsyncQdrantClient, sample_size: int = 1000) -> Dict[str, Any]:
    """Read-only report on the collection (see `status`)."""
    report: Dict[str, Any] = {"collection": COLLECTION_NAME}
    report["exists"] = bool(await client.collection_exists(COLLECTION_NAME))
    if not report["exists"]:
        return report

    info = await client.get_collection(COLLECTION_NAME)
    vectors = info.config.params.vectors
    report["vector_size"] = getattr(vectors, "size", None)
    distance = getattr(vectors, "distance", None)
    report["distance"] = str(getattr(distance, "value", distance))
    report["points_count"] = info.points_count

    try:
        QdrantVectorStore._verify_vector_config(info)
        report["config_ok"] = True
        report["config_error"] = None
    except QdrantIntegrationError as exc:
        report["config_ok"] = False
        report["config_error"] = str(exc)

    indexed = set((info.payload_schema or {}).keys())
    report["missing_payload_indexes"] = [f for f in INDEXED_PAYLOAD_FIELDS if f not in indexed]

    markers: Counter = Counter()
    sampled = 0
    offset = None
    while sampled < sample_size:
        points, offset = await client.scroll(
            COLLECTION_NAME,
            limit=min(256, sample_size - sampled),
            offset=offset,
            with_payload=["embedding_model"],
            with_vectors=False,
        )
        for point in points:
            markers[(point.payload or {}).get("embedding_model") or MISSING_MARKER] += 1
        sampled += len(points)
        if offset is None or not points:
            break
    report["sampled_points"] = sampled
    report["embedding_models"] = dict(markers)
    return report


def format_status(report: Dict[str, Any], host: str) -> str:
    lines = [f"Qdrant host: {host}", f"Collection:  {report['collection']}"]
    if not report["exists"]:
        lines += [
            "Status:      does not exist yet",
            "Next step:   `python -m scripts.qdrant_admin init` (or just upload a document - "
            "the app creates it on first use).",
        ]
        return "\n".join(lines)

    lines += [
        f"Vectors:     size={report['vector_size']}, distance={report['distance']} "
        f"(expected size={VECTOR_SIZE}, distance={getattr(VECTOR_DISTANCE, 'value', VECTOR_DISTANCE)})",
        f"Config:      {'OK' if report['config_ok'] else 'INCOMPATIBLE - ' + str(report['config_error'])}",
        f"Points:      {report['points_count']}",
    ]
    if report["missing_payload_indexes"]:
        lines.append(
            "Indexes:     missing " + ", ".join(report["missing_payload_indexes"])
            + " (the app creates them on the next upload/search/delete, or run `init`)"
        )
    else:
        lines.append("Indexes:     OK")

    models = report["embedding_models"]
    if models:
        shown = ", ".join(f"{name}: {count}" for name, count in sorted(models.items()))
        lines.append(f"Embedding model of {report['sampled_points']} sampled point(s): {shown}")
        if MISSING_MARKER in models:
            lines.append(
                f"WARNING:     {models[MISSING_MARKER]} sampled point(s) predate the embedding_model marker. "
                "They may be old BGE-M3 vectors - the collection config cannot tell (both are 1024-dim cosine). "
                "Run `check-vectors` to find out."
            )
    elif report["points_count"] == 0:
        lines.append("Embedding model: collection is empty (a fresh start).")
    return "\n".join(lines)


# --------------------------------------------------------------------------- init


async def init_collection(client: AsyncQdrantClient) -> Dict[str, Any]:
    """Create the collection and payload indexes if missing. Never deletes
    anything; raises QdrantIntegrationError for an incompatible existing
    collection instead of replacing it."""
    existed = bool(await client.collection_exists(COLLECTION_NAME))
    await _store_for(client).ensure_collection()
    return {"existed": existed}


# --------------------------------------------------------------------------- check-vectors


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


EmbedFn = Callable[..., Awaitable[List[List[float]]]]
LoadContentsFn = Callable[[List[UUID]], Awaitable[Dict[UUID, str]]]


async def check_vectors(
    client: AsyncQdrantClient,
    load_contents: LoadContentsFn,
    embed: EmbedFn,
    sample: int = 5,
    scan_limit: int = 2000,
) -> Dict[str, Any]:
    """Compare up to `sample` stored vectors with fresh Jina embeddings of
    the same chunk text. Points without an embedding_model marker are
    examined first, because those are the ones that might be old."""
    if not await client.collection_exists(COLLECTION_NAME):
        raise AdminError(f"Collection '{COLLECTION_NAME}' does not exist; nothing to check")

    unmarked: List[str] = []
    marked: List[str] = []
    offset = None
    scanned = 0
    while scanned < scan_limit:
        points, offset = await client.scroll(
            COLLECTION_NAME, limit=256, offset=offset,
            with_payload=["embedding_model"], with_vectors=False,
        )
        for point in points:
            ((marked if (point.payload or {}).get("embedding_model") else unmarked)).append(str(point.id))
        scanned += len(points)
        if offset is None or not points:
            break

    chosen = (unmarked + marked)[:sample]
    result: Dict[str, Any] = {"examined": [], "orphans": 0, "sampled": len(chosen)}
    if not chosen:
        result["verdict"] = "EMPTY"
        return result

    records = await client.retrieve(COLLECTION_NAME, ids=chosen, with_vectors=True, with_payload=False)
    vectors = {str(r.id): list(r.vector) for r in records}
    contents = await load_contents([UUID(point_id) for point_id in vectors])

    to_embed = [(pid, contents[UUID(pid)]) for pid in vectors if UUID(pid) in contents]
    result["orphans"] = len(vectors) - len(to_embed)
    if to_embed:
        fresh = await embed([text for _, text in to_embed], task="retrieval.passage")
        for (pid, _), new_vector in zip(to_embed, fresh):
            result["examined"].append({"point_id": pid, "cosine": cosine(vectors[pid], new_vector)})

    scores = [item["cosine"] for item in result["examined"]]
    if not scores:
        result["verdict"] = "NO_CHUNK_TEXT"
    elif all(s >= MATCH_THRESHOLD for s in scores):
        result["verdict"] = "JINA"
    elif all(s < MISMATCH_THRESHOLD for s in scores):
        result["verdict"] = "NOT_JINA"
    elif any(s < MISMATCH_THRESHOLD for s in scores):
        result["verdict"] = "MIXED"
    else:
        result["verdict"] = "INCONCLUSIVE"
    return result


_VERDICTS = {
    "EMPTY": "The collection has no points: nothing to check.",
    "NO_CHUNK_TEXT": "None of the sampled points has a matching chunk row in PostgreSQL, so they could not be compared.",
    "JINA": "All sampled vectors match fresh Jina embeddings of their text: they are Jina-compatible.",
    "NOT_JINA": "The sampled vectors do NOT match Jina embeddings of their text: they are almost certainly old "
                "(BGE-M3) vectors. Searching against them returns wrong results. See `reset` in the README.",
    "MIXED": "Some sampled vectors match Jina and some do not: the collection mixes vector spaces. See `reset` in the README.",
    "INCONCLUSIVE": "Similarity scores fall between the match and mismatch thresholds; try a larger --sample.",
}


def format_check(result: Dict[str, Any]) -> str:
    lines = [f"Sampled {result['sampled']} point(s); {result['orphans']} had no chunk row in PostgreSQL."]
    for item in result["examined"]:
        lines.append(f"  point {item['point_id']}: cosine vs fresh Jina embedding = {item['cosine']:.4f}")
    lines.append(f"Verdict: {_VERDICTS[result['verdict']]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- reset


async def reset_collection(
    client: AsyncQdrantClient,
    host: str,
    *,
    execute: bool,
    confirm_host: Optional[str],
    confirm_prompt: Callable[[str], str],
) -> Dict[str, Any]:
    """Delete ONLY `knowledge_chunks` and recreate it empty.

    Does nothing unless `execute` is true, `confirm_host` equals the real
    Qdrant host, and `confirm_prompt` returns the collection name.
    """
    exists = bool(await client.collection_exists(COLLECTION_NAME))
    points = None
    if exists:
        points = (await client.get_collection(COLLECTION_NAME)).points_count

    plan = {"host": host, "collection": COLLECTION_NAME, "exists": exists, "points": points}
    if not execute:
        return {**plan, "executed": False}

    if not confirm_host or confirm_host.strip().lower() != host.lower():
        raise AdminError(
            f"--confirm-host must equal the Qdrant host exactly ('{host}'). Nothing was deleted."
        )
    typed = confirm_prompt(COLLECTION_NAME)
    if typed.strip() != COLLECTION_NAME:
        raise AdminError("Confirmation did not match. Nothing was deleted.")

    if exists:
        await client.delete_collection(COLLECTION_NAME)
    await _store_for(client).ensure_collection()
    return {**plan, "executed": True}


def format_reset(result: Dict[str, Any]) -> str:
    where = f"collection '{result['collection']}' on {result['host']}"
    if not result["exists"]:
        what = f"{where} does not exist; it would simply be created."
    else:
        what = f"{where}, which holds {result['points']} point(s)."
    if not result["executed"]:
        return (
            f"DRY RUN - nothing was changed.\nWould DELETE {what}\n"
            "It would then recreate it empty (1024 dims, cosine) with its payload indexes.\n"
            "It would NOT touch PostgreSQL (documents, chunks) or Cloudflare R2 (files).\n"
            f"To really do it: python -m scripts.qdrant_admin reset --execute --confirm-host {result['host']}"
        )
    return (
        f"DONE. Deleted {what}\nRecreated it empty (1024 dims, cosine) with its payload indexes.\n"
        "PostgreSQL and Cloudflare R2 were not touched. Existing documents still have chunk rows "
        "but no vectors: delete them, or reindex each (POST /api/v1/documents/{id}/reindex)."
    )


# --------------------------------------------------------------------------- CLI


def _make_client() -> tuple:
    from app.config.settings import Settings

    try:
        settings = Settings.get_instance()
    except Exception as exc:
        # pydantic's validation error echoes input values (which can include
        # secrets), so only the exception type is ever shown.
        raise AdminError(
            f"Could not load settings ({type(exc).__name__}). Check that backend/.env exists "
            "and defines the required variables (see .env.example)."
        ) from None
    if not settings.qdrant_url:
        raise AdminError("QDRANT_URL is not set. Add it (and QDRANT_API_KEY) to backend/.env.")
    host = host_of(settings.qdrant_url)
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key), host


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.qdrant_admin", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="read-only report on the collection")
    sub.add_parser("init", help="create the collection/indexes if missing (never deletes)")
    check = sub.add_parser("check-vectors", help="read-only: detect old non-Jina vectors")
    check.add_argument("--sample", type=int, default=5, help="how many points to compare (default 5)")
    reset = sub.add_parser("reset", help="DESTRUCTIVE: delete and recreate the collection (dry run by default)")
    reset.add_argument("--execute", action="store_true", help="really delete (otherwise a dry run)")
    reset.add_argument("--confirm-host", help="the Qdrant host, repeated to confirm the target cluster")
    return parser


async def _run(args: argparse.Namespace, client: AsyncQdrantClient, host: str, out: Callable[[str], None],
               prompt: Callable[[str], str]) -> int:
    if args.command == "status":
        out(format_status(await get_status(client), host))
    elif args.command == "init":
        result = await init_collection(client)
        out(("Collection already existed and its configuration is compatible; nothing was changed.\n"
             if result["existed"] else f"Created collection '{COLLECTION_NAME}' (1024 dims, cosine).\n")
            + format_status(await get_status(client), host))
    elif args.command == "check-vectors":
        from sqlalchemy import select

        from app.database.session import _get_session_factory, dispose_engine
        from app.embeddings import embed_texts
        from app.models.chunk import Chunk

        factory = await _get_session_factory()

        async def load_contents(ids: List[UUID]) -> Dict[UUID, str]:
            async with factory() as session:  # SELECT only; nothing is committed
                rows = await session.execute(select(Chunk.id, Chunk.content).where(Chunk.id.in_(ids)))
                return {row.id: row.content for row in rows}

        try:
            out(format_check(await check_vectors(client, load_contents, embed_texts, sample=max(1, args.sample))))
        finally:
            await dispose_engine()
    elif args.command == "reset":
        out(format_reset(await reset_collection(
            client, host, execute=args.execute, confirm_host=args.confirm_host, confirm_prompt=prompt,
        )))
    return 0


def main(argv: Optional[Sequence[str]] = None, *, make_client=_make_client, out=print,
         prompt: Optional[Callable[[str], str]] = None) -> int:
    args = build_parser().parse_args(argv)
    prompt = prompt or (lambda name: input(f"Type the collection name ({name}) to confirm deletion: "))

    async def runner() -> int:
        try:
            client, host = make_client()
        except AdminError as exc:
            out(f"Error: {exc}")
            return 2
        try:
            return await _run(args, client, host, out, prompt)
        except AdminError as exc:
            out(f"Error: {exc}")
            return 1
        except Exception as exc:  # never echo raw client errors (they can contain URLs)
            out(f"Error: {type(exc).__name__} while talking to Qdrant/Jina/PostgreSQL. "
                "Check QDRANT_URL, QDRANT_API_KEY, JINA_API_KEY and DATABASE_URL.")
            return 1
        finally:
            await client.close()

    return asyncio.run(runner())


if __name__ == "__main__":
    sys.exit(main())
