from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

# Import models to register them with Base.metadata
from app.models import User, Workspace, Document