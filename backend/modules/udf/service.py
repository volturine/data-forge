import ast
import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlmodel import Session

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


def create_udf(session: Session, data: UdfCreateSchema) -> UdfResponseSchema:
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
    session.commit()
    session.refresh(udf)
    return UdfResponseSchema.model_validate(udf)


def get_udf(session: Session, udf_id: str) -> UdfResponseSchema:
    result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type, attr-defined]
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')
    return UdfResponseSchema.model_validate(udf)


def list_udfs(
    session: Session,
    query: str | None = None,
    dtype_key: str | None = None,
    tag: str | None = None,
) -> list[UdfResponseSchema]:
    stmt = select(Udf)

    if query:
        q = f'%{query.lower()}%'
        stmt = stmt.where(or_(Udf.name.ilike(q), Udf.description.ilike(q)))  # type: ignore[arg-type, attr-defined, union-attr]

    result = session.execute(stmt)
    udfs = result.scalars().all()

    filtered_udfs = [u for u in udfs if (not dtype_key or _signature_key(u.signature) == dtype_key) and (not tag or tag in (u.tags or []))]
    return [UdfResponseSchema.model_validate(u) for u in filtered_udfs]


def update_udf(session: Session, udf_id: str, data: UdfUpdateSchema) -> UdfResponseSchema:
    result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type, attr-defined]
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
    session.commit()
    session.refresh(udf)
    return UdfResponseSchema.model_validate(udf)


def delete_udf(session: Session, udf_id: str) -> None:
    result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type, attr-defined]
    udf = result.scalar_one_or_none()
    if not udf:
        raise ValueError(f'UDF {udf_id} not found')
    session.delete(udf)
    session.commit()


def clone_udf(session: Session, udf_id: str, data: UdfCloneSchema) -> UdfResponseSchema:
    result = session.execute(select(Udf).where(Udf.id == udf_id))  # type: ignore[arg-type, attr-defined]
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
    session.commit()
    session.refresh(cloned)
    return UdfResponseSchema.model_validate(cloned)


def match_udfs(session: Session, dtypes: list[str]) -> list[UdfResponseSchema]:
    dtype_key = ','.join(dtypes)
    return list_udfs(session, dtype_key=dtype_key)


def export_udfs(session: Session) -> list[UdfResponseSchema]:
    result = session.execute(select(Udf))
    udfs = result.scalars().all()
    return [UdfResponseSchema.model_validate(u) for u in udfs]


def import_udfs(session: Session, payload: UdfImportSchema) -> list[UdfResponseSchema]:
    """Import UDFs with atomic transaction - either all succeed or all fail."""
    created: list[UdfResponseSchema] = []
    udfs_to_refresh: list[Udf] = []

    # Use a single transaction to guarantee atomicity
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        for item in payload.udfs:
            _validate_code(item.code)

            existing_result = session.execute(select(Udf).where(Udf.name == item.name))  # type: ignore[arg-type, attr-defined]
            udf = existing_result.scalar_one_or_none()

            if udf and not payload.overwrite:
                continue

            if udf and payload.overwrite:
                udf.description = item.description
                udf.signature = item.signature.model_dump()
                udf.code = item.code
                udf.tags = item.tags
                udf.source = item.source or 'user'
                udf.updated_at = datetime.now(UTC)
                udfs_to_refresh.append(udf)
            else:
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
                udfs_to_refresh.append(new_udf)

    for udf in udfs_to_refresh:
        session.refresh(udf)
        created.append(UdfResponseSchema.model_validate(udf))

    return created


def seed_defaults(session: Session) -> list[UdfResponseSchema]:
    result = session.execute(select(Udf))
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

    return [create_udf(session, item) for item in defaults]
