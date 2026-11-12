from typing import List, Optional
from uuid import UUID

from app.repositories.document_repository import DocumentRepository
from app.storage.factory import delete_stored_file
from app.vector_store import QdrantIntegrationError
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate


class WorkspaceService:
    def __init__(
        self,
        workspace_repository: WorkspaceRepository,
        document_repository: Optional[DocumentRepository] = None,
        vector_store=None,
    ):
        self.workspace_repository = workspace_repository
        # Needed only to clean up documents' stored files and Qdrant vectors
        # when a workspace is deleted (see delete_workspace_for_user).
        self.document_repository = document_repository
        self.vector_store = vector_store

    async def create_workspace(self, workspace_create: WorkspaceCreate, user_id: UUID) -> WorkspaceResponse:
        from app.models.workspace import Workspace

        workspace_data = workspace_create.model_dump(exclude_unset=True)
        workspace = Workspace(**workspace_data)
        workspace.user_id = user_id

        created_workspace = await self.workspace_repository.create(workspace)

        return WorkspaceResponse.model_validate(created_workspace)

    async def get_workspaces_by_user(self, user_id: UUID) -> List[WorkspaceResponse]:
        workspaces = await self.workspace_repository.get_by_user(user_id)
        return [WorkspaceResponse.model_validate(workspace) for workspace in workspaces]

    async def get_workspace_by_name(self, name: str) -> Optional[WorkspaceResponse]:
        workspace = await self.workspace_repository.get_by_name(name)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def get_workspace_for_user(self, workspace_id: UUID, user_id: UUID) -> Optional[WorkspaceResponse]:
        """Fetch a single workspace, scoped to its owner.

        Returns None both when the workspace doesn't exist and when it
        belongs to a different user, so callers can't distinguish the two.
        """
        workspace = await self.workspace_repository.get_by_id_and_user(workspace_id, user_id)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def update_workspace_for_user(
        self, workspace_id: UUID, user_id: UUID, workspace_update: WorkspaceUpdate
    ) -> Optional[WorkspaceResponse]:
        """Update a workspace, scoped to its owner.

        Returns None both when the workspace doesn't exist and when it
        belongs to a different user.
        """
        update_data = workspace_update.model_dump(exclude_unset=True)
        workspace = await self.workspace_repository.update_for_owner(workspace_id, user_id, update_data)
        if workspace:
            return WorkspaceResponse.model_validate(workspace)
        return None

    async def delete_workspace_for_user(self, workspace_id: UUID, user_id: UUID) -> bool:
        """Delete a workspace owned by `user_id`, including all of its
        documents' stored files and Qdrant vectors.

        Returns False both when the workspace doesn't exist and when it
        belongs to a different user.

        The database cascade removes the workspace's documents, chunks,
        and connectors, but Qdrant and the local file store are separate
        systems with no cascade - without this cleanup every document in
        a deleted workspace would leave an orphaned file and orphaned
        vectors behind (the same gap per-document deletion already
        closes in DocumentService.delete_document_for_user).
        """
        artifacts = []
        if self.document_repository is not None:
            documents = await self.document_repository.get_by_workspace_owner(
                workspace_id, user_id
            )
            artifacts = [(document.id, document.storage_path) for document in documents]

        deleted = await self.workspace_repository.delete_for_owner(workspace_id, user_id)
        if not deleted:
            return False

        for document_id, storage_path in artifacts:
            # Each file is removed from the provider that owns it (local or
            # R2). Best-effort: the database rows are already gone.
            await delete_stored_file(storage_path)
            if self.vector_store is not None:
                try:
                    await self.vector_store.delete_document_chunks(document_id)
                except QdrantIntegrationError:
                    # The database rows are already gone; a transient Qdrant
                    # failure shouldn't turn a successful delete into an error.
                    pass

        return True
