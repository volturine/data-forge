from buf.validate import validate_pb2 as _validate_pb2
from dataforge_protocol import common_pb2 as _common_pb2
from google.protobuf import struct_pb2 as _struct_pb2
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

class ObjectStorePathParts(_message.Message):
    __slots__ = ("parts", "bucket")
    PARTS_FIELD_NUMBER: _ClassVar[int]
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    parts: _containers.RepeatedScalarFieldContainer[str]
    bucket: str
    def __init__(self, parts: _Optional[_Iterable[str]] = ..., bucket: _Optional[str] = ...) -> None: ...

class ObjectStoreJoinRequest(_message.Message):
    __slots__ = ("base", "parts")
    BASE_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    base: ObjectStoreUrl
    parts: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, base: _Optional[_Union[ObjectStoreUrl, _Mapping]] = ..., parts: _Optional[_Iterable[str]] = ...) -> None: ...

class ObjectStoreStorageOptionsResponse(_message.Message):
    __slots__ = ("options",)
    OPTIONS_FIELD_NUMBER: _ClassVar[int]
    options: _struct_pb2.Struct
    def __init__(self, options: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ObjectStoreBytes(_message.Message):
    __slots__ = ("target", "data", "content_type")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    target: ObjectStoreUrl
    data: bytes
    content_type: str
    def __init__(self, target: _Optional[_Union[ObjectStoreUrl, _Mapping]] = ..., data: _Optional[bytes] = ..., content_type: _Optional[str] = ...) -> None: ...

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
