from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UdfInputSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    dtype: str
    label: str | None = None


class UdfSignatureSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inputs: list[UdfInputSchema] = Field(default_factory=list)
    output_dtype: str | None = None


class UdfCreateSchema(BaseModel):
    name: str
    description: str | None = None
    signature: UdfSignatureSchema
    code: str
    tags: list[str] | None = None
    source: str | None = None


class UdfUpdateSchema(BaseModel):
    name: str | None = None
    description: str | None = None
    signature: UdfSignatureSchema | None = None
    code: str | None = None
    tags: list[str] | None = None
    source: str | None = None


class UdfResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    signature: dict
    code: str
    tags: list[str] | None
    source: str
    created_at: datetime
    updated_at: datetime


class UdfCloneSchema(BaseModel):
    name: str | None = None


class UdfExportSchema(BaseModel):
    udfs: list[UdfResponseSchema]


class UdfImportItemSchema(BaseModel):
    name: str
    description: str | None = None
    signature: UdfSignatureSchema
    code: str
    tags: list[str] | None = None
    source: str | None = None


class UdfImportSchema(BaseModel):
    udfs: list[UdfImportItemSchema]
    overwrite: bool = False
