from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate, UserResponse
from uuid import UUID
from typing import Optional, List

class UserService:
    def __init__(self, user_repository: UserRepository):
        self.user_repository = user_repository

    async def create_user(self, user_create: UserCreate) -> UserResponse:
        # Convert UserCreate to User model
        from app.models.user import User
        from datetime import datetime

        user_data = user_create.model_dump(exclude_unset=True)
        user = User(**user_data)

        # Create user through repository
        created_user = await self.user_repository.create(user)

        # Convert to response schema
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

    async def get_user_by_username(self, username: str) -> Optional[UserResponse]:
        user = await self.user_repository.get_by_username(username)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def get_active_users(self, is_active: bool = True) -> List[UserResponse]:
        users = await self.user_repository.get_active_users(is_active)
        return [UserResponse.model_validate(user) for user in users]

    async def update_user(self, user_id: UUID, user_update: UserUpdate) -> Optional[UserResponse]:
        update_data = user_update.model_dump(exclude_unset=True)
        user = await self.user_repository.update(user_id, update_data)
        if user:
            return UserResponse.model_validate(user)
        return None

    async def delete_user(self, user_id: UUID) -> bool:
        return await self.user_repository.delete(user_id)