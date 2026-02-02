import ast
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.udf.models import Udf
from modules.udf.schemas import (
    UdfCloneSchema,
    UdfCreateSchema,
    UdfImportSchema,
    UdfInputSchema,
    UdfResponseSchema,
    UdfSignatureSchema,
    UdfUpdateSchema,
)


def _validate_code(code: str) -> None:
    if not code.strip():
        raise ValueError('UDF code cannot be empty')
    try:
        ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f'Invalid Python syntax: {e.msg}')


def _signature_key(signature: dict) -> str:
    inputs = signature.get('inputs') or []
    if not isinstance(inputs, list):
        return ''
    dtypes = [str(item.get('dtype') or '') for item in inputs]
    return ','.join(dtypes)


async def create_udf(session: AsyncSession, data: UdfCreateSchema) -> UdfResponseSchema:
    _validate_code(data.code)
    now = datetime.now(UTC)
    udf = Udf(
        id=str(uuid.uuid4()),
        name=data.name,
        description=data.description,
        signature=data.signature.model_dump(),
        code=data.code,
        tags=data.tags,
        source=data.source or 'user',
        created_at=now,
        updated_at=now,
    )
    session.add(udf)
    await session.commit()
    await session.refresh(udf)
    return UdfResponseSchema.model_validate(udf)


async def get_udf(session: AsyncSession, udf_id: str) -> UdfResponseSchema:
    result = await session.execute(select(Udf).where(Udf.id == udf_id))
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')
    return UdfResponseSchema.model_validate(udf)


async def list_udfs(
    session: AsyncSession,
    query: str | None = None,
    dtype_key: str | None = None,
    tag: str | None = None,
) -> list[UdfResponseSchema]:
    stmt = select(Udf)
    
    # Apply SQL-level text search filtering
    if query:
        q = f'%{query.lower()}%'
        stmt = stmt.where(
            or_(
                Udf.name.ilike(q),
                Udf.description.ilike(q)
            )
        )
    
    result = await session.execute(stmt)
    udfs = result.scalars().all()

    # Apply Python-side filters for complex JSON fields
    filtered_udfs = []
    for u in udfs:
        # Signature dtype key filter (requires parsing JSON signature)
        if dtype_key and _signature_key(u.signature) != dtype_key:
            continue
        
        # Tag filter (requires parsing JSON tags array)
        if tag:
            tags = u.tags or []
            if tag not in tags:
                continue
        
        filtered_udfs.append(u)

    return [UdfResponseSchema.model_validate(u) for u in filtered_udfs]


async def update_udf(session: AsyncSession, udf_id: str, data: UdfUpdateSchema) -> UdfResponseSchema:
    result = await session.execute(select(Udf).where(Udf.id == udf_id))
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')

    if data.name is not None:
        udf.name = data.name
    if data.description is not None:
        udf.description = data.description
    if data.signature is not None:
        udf.signature = data.signature.model_dump()
    if data.code is not None:
        _validate_code(data.code)
        udf.code = data.code
    if data.tags is not None:
        udf.tags = data.tags
    if data.source is not None:
        udf.source = data.source

    udf.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(udf)
    return UdfResponseSchema.model_validate(udf)


async def delete_udf(session: AsyncSession, udf_id: str) -> None:
    result = await session.execute(select(Udf).where(Udf.id == udf_id))
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')
    await session.delete(udf)
    await session.commit()


async def clone_udf(session: AsyncSession, udf_id: str, data: UdfCloneSchema) -> UdfResponseSchema:
    result = await session.execute(select(Udf).where(Udf.id == udf_id))
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')

    now = datetime.now(UTC)
    cloned = Udf(
        id=str(uuid.uuid4()),
        name=data.name or f'{udf.name} (copy)',
        description=udf.description,
        signature=udf.signature,
        code=udf.code,
        tags=udf.tags,
        source=udf.source,
        created_at=now,
        updated_at=now,
    )
    session.add(cloned)
    await session.commit()
    await session.refresh(cloned)
    return UdfResponseSchema.model_validate(cloned)


async def match_udfs(session: AsyncSession, dtypes: list[str]) -> list[UdfResponseSchema]:
    dtype_key = ','.join(dtypes)
    return await list_udfs(session, dtype_key=dtype_key)


async def export_udfs(session: AsyncSession) -> list[UdfResponseSchema]:
    result = await session.execute(select(Udf))
    udfs = result.scalars().all()
    return [UdfResponseSchema.model_validate(u) for u in udfs]


async def import_udfs(session: AsyncSession, payload: UdfImportSchema) -> list[UdfResponseSchema]:
    """Import UDFs with atomic transaction - either all succeed or all fail."""
    created: list[UdfResponseSchema] = []
    udfs_to_create: list[Udf] = []
    
    # First pass: validate all UDFs and prepare changes
    for item in payload.udfs:
        # Validate code syntax early
        _validate_code(item.code)
        
        existing_result = await session.execute(select(Udf).where(Udf.name == item.name))
        udf = existing_result.scalar_one_or_none()
        
        if udf and not payload.overwrite:
            continue
            
        if udf and payload.overwrite:
            # Update existing UDF (will be committed at the end)
            udf.description = item.description
            udf.signature = item.signature.model_dump()
            udf.code = item.code
            udf.tags = item.tags
            udf.source = item.source or 'user'
            udf.updated_at = datetime.now(UTC)
            udfs_to_create.append(udf)
        else:
            # Create new UDF
            now = datetime.now(UTC)
            new_udf = Udf(
                id=str(uuid.uuid4()),
                name=item.name,
                description=item.description,
                signature=item.signature.model_dump(),
                code=item.code,
                tags=item.tags,
                source=item.source or 'user',
                created_at=now,
                updated_at=now,
            )
            session.add(new_udf)
            udfs_to_create.append(new_udf)
    
    # Commit all changes atomically
    if udfs_to_create:
        await session.commit()
        
        # Refresh all UDFs to get their final state
        for udf in udfs_to_create:
            await session.refresh(udf)
            created.append(UdfResponseSchema.model_validate(udf))
    
    return created


async def seed_defaults(session: AsyncSession) -> list[UdfResponseSchema]:
    result = await session.execute(select(Udf))
    existing = result.scalars().first()
    if existing:
        return []

    defaults = [
        UdfCreateSchema(
            name='Ratio',
            description='Compute a ratio between two numbers.',
            signature=UdfSignatureSchema(
                inputs=[
                    UdfInputSchema(position=0, dtype='Float64', label='numerator'),
                    UdfInputSchema(position=1, dtype='Float64', label='denominator'),
                ],
                output_dtype='Float64',
            ),
            code=(
                'def udf(numerator, denominator):\n'
                '    if denominator in (0, None):\n'
                '        return None\n'
                '    return numerator / denominator\n'
            ),
            tags=['math', 'ratio'],
            source='seeded',
        ),
        UdfCreateSchema(
            name='Coalesce',
            description='Return the first non-null value.',
            signature=UdfSignatureSchema(
                inputs=[
                    UdfInputSchema(position=0, dtype='String', label='primary'),
                    UdfInputSchema(position=1, dtype='String', label='fallback'),
                ],
                output_dtype='String',
            ),
            code=('def udf(primary, fallback):\n    return primary if primary is not None else fallback\n'),
            tags=['string', 'cleanup'],
            source='seeded',
        ),
        UdfCreateSchema(
            name='Normalize',
            description='Normalize a numeric value into 0-1.',
            signature=UdfSignatureSchema(
                inputs=[
                    UdfInputSchema(position=0, dtype='Float64', label='value'),
                    UdfInputSchema(position=1, dtype='Float64', label='min'),
                    UdfInputSchema(position=2, dtype='Float64', label='max'),
                ],
                output_dtype='Float64',
            ),
            code=(
                'def udf(value, min_value, max_value):\n'
                '    if value is None or min_value is None or max_value in (None, 0):\n'
                '        return None\n'
                '    return (value - min_value) / (max_value - min_value)\n'
            ),
            tags=['math', 'normalize'],
            source='seeded',
        ),
    ]

    created: list[UdfResponseSchema] = []
    for item in defaults:
        created.append(await create_udf(session, item))
    return created
