from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class Analysis(Base):
    __tablename__ = 'analyses'

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    pipeline_definition: Mapped[dict] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default='draft')
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)
    result_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail: Mapped[str | None] = mapped_column(String, nullable=True)


class AnalysisDataSource(Base):
    __tablename__ = 'analysis_datasources'

    analysis_id: Mapped[str] = mapped_column(
        String,
        ForeignKey('analyses.id', ondelete='CASCADE'),
        primary_key=True,
    )
    datasource_id: Mapped[str] = mapped_column(
        String,
        ForeignKey('datasources.id', ondelete='CASCADE'),
        primary_key=True,
    )
