from sqlalchemy import Column, Integer, String, BigInteger, Text, JSON, Boolean, Index

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
