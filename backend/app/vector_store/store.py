"""Qdrant vector-store integration for Lumora.

Manages a single collection (`knowledge_chunks`) and provides batch
upsert / document-level delete operations on top of AsyncQdrantClient.

This module is independent of PostgreSQL and the embedding engine: it
only accepts already-generated vectors and chunk metadata from the
caller - it does not read Chunk/Document rows and does not generate
embeddings itself.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qmodels

from app.config.settings import Settings

COLLECTION_NAME = "knowledge_chunks"
VECTOR_SIZE = 1024
VECTOR_DISTANCE = qmodels.Distance.COSINE

# Payload fields that document-scoped (and future workspace-scoped)
# filtering relies on. Qdrant Cloud requires an explicit payload index
# on any field used in a filter - without one, filtering fails with
# "Index required but not found".
INDEXED_PAYLOAD_FIELDS = ("document_id", "workspace_id")


class QdrantIntegrationError(Exception):
    """Raised for Qdrant configuration, connectivity, or operation failures.

    Never carries API keys or raw client internals in its message.
    """


@dataclass
class QdrantChunkPoint:
    """A single chunk's precomputed vector plus the payload to store with it."""

    chunk_id: UUID
    document_id: UUID
    workspace_id: UUID
    filename: str
    chunk_index: int
    source: str
    vector: List[float]


class QdrantVectorStore:
    """Thin wrapper around AsyncQdrantClient for the `knowledge_chunks` collection."""

    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None):
        settings = Settings.get_instance()
        self._url = url or settings.qdrant_url
        self._api_key = api_key or settings.qdrant_api_key
        self._client: Optional[AsyncQdrantClient] = None

    def _get_client(self) -> AsyncQdrantClient:
        """Lazily create (and cache) the underlying AsyncQdrantClient."""
        if self._client is not None:
            return self._client

        if not self._url:
            raise QdrantIntegrationError("QDRANT_URL is not configured")

        try:
            self._client = AsyncQdrantClient(url=self._url, api_key=self._api_key)
        except Exception as exc:
            raise QdrantIntegrationError("Failed to create Qdrant client") from exc

        return self._client

    async def close(self) -> None:
        """Release the underlying client connection, if one was created."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def ensure_collection(self) -> None:
        """Create `knowledge_chunks` if it doesn't exist yet, and ensure the
        payload indexes that filtering (e.g. document-scoped deletion) needs.

        If the collection already exists, verify its vector configuration
        matches (size=1024, distance=COSINE) rather than touching it - an
        incompatible existing collection raises QdrantIntegrationError
        instead of being silently overwritten or recreated. Existing
        points are never touched by this method.
        """
        client = self._get_client()

        try:
            exists = await client.collection_exists(COLLECTION_NAME)
        except Exception as exc:
            raise QdrantIntegrationError("Failed to check Qdrant collection existence") from exc

        if not exists:
            try:
                await client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=qmodels.VectorParams(
                        size=VECTOR_SIZE, distance=VECTOR_DISTANCE
                    ),
                )
            except Exception as exc:
                raise QdrantIntegrationError("Failed to create Qdrant collection") from exc

            await self._ensure_payload_indexes(client, existing_indexes=set())
            return

        try:
            info = await client.get_collection(COLLECTION_NAME)
        except Exception as exc:
            raise QdrantIntegrationError("Failed to fetch Qdrant collection info") from exc

        self._verify_vector_config(info)

        existing_indexes = set((info.payload_schema or {}).keys())
        await self._ensure_payload_indexes(client, existing_indexes=existing_indexes)

    @staticmethod
    async def _ensure_payload_indexes(
        client: AsyncQdrantClient, existing_indexes: set
    ) -> None:
        """Create a UUID payload index for each field filtering relies on,
        skipping any that are already indexed. Never touches existing points.
        """
        for field_name in INDEXED_PAYLOAD_FIELDS:
            if field_name in existing_indexes:
                continue
            try:
                await client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name=field_name,
                    field_schema=qmodels.PayloadSchemaType.UUID,
                )
            except Exception as exc:
                raise QdrantIntegrationError(
                    f"Failed to create Qdrant payload index for '{field_name}'"
                ) from exc

    @staticmethod
    def _verify_vector_config(info: qmodels.CollectionInfo) -> None:
        vectors_config = info.config.params.vectors

        if isinstance(vectors_config, dict):
            raise QdrantIntegrationError(
                "Existing 'knowledge_chunks' collection uses named vectors, "
                "which is incompatible with the expected single unnamed vector"
            )

        size = getattr(vectors_config, "size", None)
        distance = getattr(vectors_config, "distance", None)

        if size != VECTOR_SIZE or distance != VECTOR_DISTANCE:
            raise QdrantIntegrationError(
                "Existing 'knowledge_chunks' collection has an incompatible "
                f"vector configuration (size={size}, distance={distance}); "
                f"expected size={VECTOR_SIZE}, distance={VECTOR_DISTANCE}"
            )

    async def upsert_chunks(self, chunks: Sequence[QdrantChunkPoint]) -> None:
        """Batch-upsert precomputed chunk vectors as Qdrant points.

        Each point's ID is the chunk's own PostgreSQL UUID, so upserting
        the same chunk_id again replaces that point rather than creating
        a duplicate. Does not regenerate embeddings - vectors must
        already be computed by the caller.
        """
        if not chunks:
            return

        await self.ensure_collection()
        client = self._get_client()

        points = [
            qmodels.PointStruct(
                id=str(chunk.chunk_id),
                vector=chunk.vector,
                payload=self._build_payload(chunk),
            )
            for chunk in chunks
        ]

        try:
            await client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
        except Exception as exc:
            raise QdrantIntegrationError("Failed to upsert chunks to Qdrant") from exc

    @staticmethod
    def _build_payload(chunk: QdrantChunkPoint) -> Dict[str, Any]:
        return {
            "chunk_id": str(chunk.chunk_id),
            "document_id": str(chunk.document_id),
            "workspace_id": str(chunk.workspace_id),
            "filename": chunk.filename,
            "chunk_index": chunk.chunk_index,
            "source": chunk.source,
        }

    async def delete_document_chunks(self, document_id: UUID) -> None:
        """Delete all points belonging to a single document.

        Uses a payload filter on document_id - never deletes the whole
        collection, and never touches another document's points.
        """
        client = self._get_client()

        try:
            exists = await client.collection_exists(COLLECTION_NAME)
        except Exception as exc:
            raise QdrantIntegrationError("Failed to check Qdrant collection existence") from exc

        if not exists:
            return

        # Filtering by document_id requires a payload index on that field.
        # A collection created before this check was added (or created
        # outside this module) may not have one yet, so verify/create it
        # here too - this does not touch existing points.
        await self.ensure_collection()

        try:
            await client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.FilterSelector(
                    filter=qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="document_id",
                                match=qmodels.MatchValue(value=str(document_id)),
                            )
                        ]
                    )
                ),
                wait=True,
            )
        except Exception as exc:
            raise QdrantIntegrationError("Failed to delete document chunks from Qdrant") from exc

    async def check_connection(self) -> Dict[str, Any]:
        """Manual verification helper: confirms connectivity and reports
        basic, non-sensitive collection info (no API key, no raw client
        internals)."""
        client = self._get_client()

        try:
            collections = await client.get_collections()
        except Exception as exc:
            raise QdrantIntegrationError("Failed to connect to Qdrant") from exc

        collection_names = [c.name for c in collections.collections]
        result: Dict[str, Any] = {"connected": True, "collections": collection_names}

        if COLLECTION_NAME in collection_names:
            try:
                info = await client.get_collection(COLLECTION_NAME)
            except Exception as exc:
                raise QdrantIntegrationError("Failed to fetch Qdrant collection info") from exc

            vectors_config = info.config.params.vectors
            result[COLLECTION_NAME] = {
                "points_count": info.points_count,
                "vector_size": getattr(vectors_config, "size", None),
                "distance": str(getattr(vectors_config, "distance", None)),
            }

        return result
