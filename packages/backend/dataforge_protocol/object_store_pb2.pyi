from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ObjectStoreUrl(_message.Message):
    __slots__ = ("url",)
    URL_FIELD_NUMBER: _ClassVar[int]
    url: str
    def __init__(self, url: _Optional[str] = ...) -> None: ...

class ObjectStoreUrlClassificationRequest(_message.Message):
    __slots__ = ("value",)
    VALUE_FIELD_NUMBER: _ClassVar[int]
    value: str
    def __init__(self, value: _Optional[str] = ...) -> None: ...

class ObjectStoreUrlClassificationResponse(_message.Message):
    __slots__ = ("is_object_store", "is_managed", "object_url")
    IS_OBJECT_STORE_FIELD_NUMBER: _ClassVar[int]
    IS_MANAGED_FIELD_NUMBER: _ClassVar[int]
    OBJECT_URL_FIELD_NUMBER: _ClassVar[int]
    is_object_store: bool
    is_managed: bool
    object_url: ObjectStoreUrl
    def __init__(self, is_object_store: _Optional[bool] = ..., is_managed: _Optional[bool] = ..., object_url: _Optional[_Union[ObjectStoreUrl, _Mapping]] = ...) -> None: ...

class ObjectStorePathParts(_message.Message):
    __slots__ = ("parts", "bucket", "namespace")
    PARTS_FIELD_NUMBER: _ClassVar[int]
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    NAMESPACE_FIELD_NUMBER: _ClassVar[int]
    parts: _containers.RepeatedScalarFieldContainer[str]
    bucket: str
    namespace: str
    def __init__(self, parts: _Optional[_Iterable[str]] = ..., bucket: _Optional[str] = ..., namespace: _Optional[str] = ...) -> None: ...

class ObjectStoreJoinRequest(_message.Message):
    __slots__ = ("base", "parts")
    BASE_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    base: ObjectStoreUrl
    parts: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, base: _Optional[_Union[ObjectStoreUrl, _Mapping]] = ..., parts: _Optional[_Iterable[str]] = ...) -> None: ...

class ObjectStoreStorageOptions(_message.Message):
    __slots__ = ("endpoint_url", "access_key_id", "secret_access_key", "region", "force_virtual_addressing", "py_io_impl")
    ENDPOINT_URL_FIELD_NUMBER: _ClassVar[int]
    ACCESS_KEY_ID_FIELD_NUMBER: _ClassVar[int]
    SECRET_ACCESS_KEY_FIELD_NUMBER: _ClassVar[int]
    REGION_FIELD_NUMBER: _ClassVar[int]
    FORCE_VIRTUAL_ADDRESSING_FIELD_NUMBER: _ClassVar[int]
    PY_IO_IMPL_FIELD_NUMBER: _ClassVar[int]
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    region: str
    force_virtual_addressing: bool
    py_io_impl: str
    def __init__(self, endpoint_url: _Optional[str] = ..., access_key_id: _Optional[str] = ..., secret_access_key: _Optional[str] = ..., region: _Optional[str] = ..., force_virtual_addressing: _Optional[bool] = ..., py_io_impl: _Optional[str] = ...) -> None: ...

class ObjectStoreStorageOptionsResponse(_message.Message):
    __slots__ = ("storage_options",)
    STORAGE_OPTIONS_FIELD_NUMBER: _ClassVar[int]
    storage_options: ObjectStoreStorageOptions
    def __init__(self, storage_options: _Optional[_Union[ObjectStoreStorageOptions, _Mapping]] = ...) -> None: ...

class ObjectStoreUploadStart(_message.Message):
    __slots__ = ("target", "content_type", "max_bytes")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    target: ObjectStoreUrl
    content_type: str
    max_bytes: int
    def __init__(self, target: _Optional[_Union[ObjectStoreUrl, _Mapping]] = ..., content_type: _Optional[str] = ..., max_bytes: _Optional[int] = ...) -> None: ...

class ObjectStoreUploadChunk(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    def __init__(self, data: _Optional[bytes] = ...) -> None: ...

class ObjectStoreUploadCommit(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ObjectStoreUploadAbort(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ObjectStoreUploadRequest(_message.Message):
    __slots__ = ("start", "chunk", "commit", "abort")
    START_FIELD_NUMBER: _ClassVar[int]
    CHUNK_FIELD_NUMBER: _ClassVar[int]
    COMMIT_FIELD_NUMBER: _ClassVar[int]
    ABORT_FIELD_NUMBER: _ClassVar[int]
    start: ObjectStoreUploadStart
    chunk: ObjectStoreUploadChunk
    commit: ObjectStoreUploadCommit
    abort: ObjectStoreUploadAbort
    def __init__(self, start: _Optional[_Union[ObjectStoreUploadStart, _Mapping]] = ..., chunk: _Optional[_Union[ObjectStoreUploadChunk, _Mapping]] = ..., commit: _Optional[_Union[ObjectStoreUploadCommit, _Mapping]] = ..., abort: _Optional[_Union[ObjectStoreUploadAbort, _Mapping]] = ...) -> None: ...

class ObjectStoreTransferChunk(_message.Message):
    __slots__ = ("data",)
    DATA_FIELD_NUMBER: _ClassVar[int]
    data: bytes
    def __init__(self, data: _Optional[bytes] = ...) -> None: ...

class ObjectStoreBucket(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class ObjectStoreExistsResponse(_message.Message):
    __slots__ = ("exists",)
    EXISTS_FIELD_NUMBER: _ClassVar[int]
    exists: bool
    def __init__(self, exists: _Optional[bool] = ...) -> None: ...

class ObjectStorePrefixesResponse(_message.Message):
    __slots__ = ("prefixes",)
    PREFIXES_FIELD_NUMBER: _ClassVar[int]
    prefixes: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, prefixes: _Optional[_Iterable[str]] = ...) -> None: ...

class ObjectStoreMetadataFilesResponse(_message.Message):
    __slots__ = ("files",)
    FILES_FIELD_NUMBER: _ClassVar[int]
    files: _containers.RepeatedCompositeFieldContainer[ObjectStoreUrl]
    def __init__(self, files: _Optional[_Iterable[_Union[ObjectStoreUrl, _Mapping]]] = ...) -> None: ...
