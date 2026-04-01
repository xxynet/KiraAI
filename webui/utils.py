"""
Shared utility functions for the WebUI.
"""
import json
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException, status
import jwt
import os

from core.logging_manager import get_logger

logger = get_logger("webui", "blue")

# JWT secret: read from environment variable, fall back to a random key per process (development only)
_JWT_SECRET = os.environ.get("JWT_SECRET") or secrets.token_hex(32)


def _generate_strong_password(length: int = 16) -> str:
    """Generate a strong password with upper/lower alphabets, digits, and special characters."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    logger.info("Generated new access_token")
    return token


def _load_webui_config() -> Dict:
    """Load webui.json"""
    config_path = Path(__file__).parent.parent / "data" / "webui.json"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"host": "0.0.0.0", "port": 5267}


def _save_webui_config(config: Dict):
    """Save webui.json file"""
    config_path = Path(__file__).parent.parent / "data" / "webui.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _get_or_generate_access_token() -> str:
    """Get or generate access_token"""
    config = _load_webui_config()
    if "access_token" not in config or not config["access_token"]:
        config["access_token"] = _generate_strong_password()
        _save_webui_config(config)
    return config["access_token"]


def _create_jwt_token(data: Dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=5)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _JWT_SECRET, algorithm="HS256")
    return encoded_jwt


def _verify_jwt_token(token: str) -> Dict:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


def _generate_id() -> str:
    """Generate a short unique identifier."""
    return uuid.uuid4().hex[:12]


def schema_to_dict(fields: list) -> dict:
    """Convert a list of BaseConfigField objects to a plain dict keyed by field.key.

    Fields whose key is missing or whose to_dict() raises are silently skipped.
    """
    result: dict = {}
    for f in fields:
        key = getattr(f, "key", None)
        if not key:
            continue
        try:
            result[str(key)] = f.to_dict()
        except Exception:
            continue
    return result
