from datetime import datetime

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Udf(Base):
    __tablename__ = 'udfs'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    signature: Mapped[dict] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default='user')
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
