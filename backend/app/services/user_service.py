from typing import Optional
from uuid import UUID

from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse, UserUpdate


class UserService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def create_user(self, user_create: UserCreate) -> UserResponse:
        from app.models.user import User

        user_data = user_create.model_dump(exclude_unset=True)
        user = User(**user_data)

        created_user = await self.user_repository.create(user)

        return UserResponse.model_validate(created_user)

    async def get_user_by_id(self, user_id: UUID) -> Optional[UserResponse]:
        user = await self.user_repository.get_by_id(user_id)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def get_user_by_email(self, email: str) -> Optional[UserResponse]:
        user = await self.user_repository.get_by_email(email)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> Optional[UserResponse]:
        update_data = user_update.model_dump(exclude_unset=True)
        user = await self.user_repository.update(user_id, update_data)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def delete_user(self, user_id: UUID) -> bool:
        return await self.user_repository.delete(user_id)
