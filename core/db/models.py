from sqlalchemy import JSON, BigInteger, Boolean, Column, Index, Integer, String, Text

from .db_mgr import Base


class Sticker(Base):
    """Sticker metadata table."""
    __tablename__ = "stickers"

    id = Column(String, primary_key=True, nullable=False)
    desc = Column(Text, nullable=False)
    path = Column(String, nullable=False)
    extra = Column(JSON, nullable=True)


class ImageDescCache(Base):
    """Image description cache table indexed by MD5."""
    __tablename__ = "image_desc_cache"

    md5 = Column(String(32), primary_key=True, nullable=False)
    description = Column(Text, nullable=False)
    count = Column(Integer, nullable=False, default=0)
    last_seen = Column(BigInteger, nullable=False)


class Persona(Base):
    """Persona storage table."""
    __tablename__ = "personas"

    id = Column(String, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    format = Column(String, nullable=False, default="text")
    content = Column(Text, nullable=False)
    reference_image_path = Column(Text, nullable=True)
    chat_rules = Column(Text, nullable=False, default="")
    private_chat_rules = Column(Text, nullable=False, default="")
    group_chat_rules = Column(Text, nullable=False, default="")
    created_at = Column(BigInteger, nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)


class TelemetryMessage(Base):
    """Raw message telemetry records for hourly aggregation."""
    __tablename__ = "telemetry_messages"
    __table_args__ = (
        Index("ix_telemetry_messages_reported_ts", "reported", "timestamp"),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    platform = Column(String(32), nullable=False)
    reported = Column(Boolean, nullable=False, default=False)


class TelemetryLLMUsage(Base):
    """Raw LLM call telemetry records for hourly aggregation."""
    __tablename__ = "telemetry_llm_usage"
    __table_args__ = (
        Index("ix_telemetry_llm_reported_ts", "reported", "timestamp"),
    )

    id = Column(String(36), primary_key=True, nullable=False)
    timestamp = Column(BigInteger, nullable=False)
    model = Column(String(128), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=True)
    response_time_ms = Column(Integer, nullable=False, default=0)
    success = Column(Boolean, nullable=False, default=True)
    reported = Column(Boolean, nullable=False, default=False)


class PluginStoreSource(Base):
    """Plugin store source metadata table."""
    __tablename__ = "plugin_store_sources"

    id = Column(String, primary_key=True, nullable=False)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    cache_file = Column(String, nullable=True)  # filename under plugin_src/
    updated_at = Column(BigInteger, nullable=False, default=0)
    is_current = Column(Boolean, nullable=False, default=False)
    created_at = Column(BigInteger, nullable=False, default=0)


class MessageRecord(Base):
    """Structured IM history, independent of the bounded LLM context."""
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at", "id"),
        Index("ix_messages_memory", "session_id", "llm_message_id"),
    )

    id = Column(String(32), primary_key=True)
    session_id = Column(String, nullable=False)
    self_id = Column(String, nullable=True)
    platform = Column(String, nullable=False)
    platform_message_id = Column(String, nullable=True)
    dedup_key = Column(String(64), unique=True, nullable=True)
    is_notice = Column(Boolean, nullable=False, default=False)
    is_mentioned = Column(Boolean, nullable=True)
    direction = Column(String(16), nullable=False)
    sender_id = Column(String, nullable=True)
    sender_name = Column(String, nullable=True)
    timestamp = Column(BigInteger, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    chain = Column(JSON, nullable=False)
    status = Column(String(16), nullable=False)
    error_type = Column(String, nullable=True)
    llm_message_id = Column(String(32), nullable=True)
    schema_version = Column(Integer, nullable=False, default=1)


class ChatSessionRecord(Base):
    """One persistent LLM session, independent of its platform routing key."""
    __tablename__ = "chat_sessions"

    id = Column(String(37), primary_key=True, nullable=False)
    session_key = Column(String, unique=True, nullable=False)
    title = Column(Text().evaluates_none(), nullable=True, server_default="")
    description = Column(Text().evaluates_none(), nullable=True, server_default="")
    content = Column(JSON, nullable=False, server_default="[]")
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=False)
    data = Column(JSON, nullable=False, server_default="{}")


class DatabaseMigration(Base):
    """Completed data imports, committed atomically with their imported rows."""
    __tablename__ = "database_migrations"

    name = Column(String, primary_key=True, nullable=False)
    app_version = Column(String, nullable=False)
    executed_at = Column(BigInteger, nullable=False)
