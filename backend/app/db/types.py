"""
跨数据库兼容的字段类型

提供 GUID 类型，在 SQLite 下映射为 String(36)，在 PostgreSQL 下映射为原生 UUID。
"""

import uuid
from sqlalchemy.types import TypeDecorator, CHAR


class GUID(TypeDecorator):
    """
    平台无关的 UUID 类型。

    - PostgreSQL: 使用原生 UUID 类型
    - SQLite: 使用 CHAR(36) 存储 UUID 字符串
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value