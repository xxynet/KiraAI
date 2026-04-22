from sqlalchemy import Column, Integer, String, BigInteger, Text, JSON

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
