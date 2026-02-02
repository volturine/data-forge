from sqlalchemy.ext.asyncio import AsyncSession

from modules.udf import service


async def ensure_udf_seeds(session: AsyncSession) -> None:
    await service.seed_defaults(session)
