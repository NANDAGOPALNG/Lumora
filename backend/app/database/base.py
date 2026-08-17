from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all SQLAlchemy ORM models.

    All models must be imported (see app/models/__init__.py) so that
    they are registered on Base.metadata before Alembic autogenerate
    or Base.metadata.create_all() are used.
    """

    pass