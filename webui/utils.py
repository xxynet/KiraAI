"""
Shared utility functions for the WebUI.
"""
import base64
import hashlib
import json
import os
import secrets
import stat
import string
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from fastapi import HTTPException, status

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path

logger = get_logger("webui", "blue")


def _load_persisted_jwt_secret() -> str:
    """Return a JWT secret stable across processes/workers/restarts.

    Priority: JWT_SECRET env var → on-disk file → newly generated + saved.
    The on-disk fallback lets multiple workers share the same secret and
    keeps tokens valid across restarts when JWT_SECRET isn't provisioned.
    """
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        return env_secret

    secret_path = get_data_path() / ".jwt_secret"
    try:
        if secret_path.is_file():
            content = secret_path.read_text(encoding="utf-8").strip()
            if content:
                return content
    except OSError as e:
        logger.warning(f"Could not read persisted JWT secret at {secret_path}: {e}")

    generated = secrets.token_hex(32)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp file in same dir + replace, so partial writes can't
        # leave an empty secret file behind.
        fd, tmp_name = tempfile.mkstemp(prefix=".jwt_secret.", dir=str(secret_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(generated)
            try:
                os.chmod(tmp_name, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                # chmod is best-effort (no-op on Windows); not fatal.
                pass
            os.replace(tmp_name, secret_path)
        except Exception:
            # Clean up the temp file if replace failed
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    except OSError as e:
        logger.warning(
            f"Could not persist JWT secret to {secret_path}: {e}. "
            "Secret will be regenerated on next process start."
        )
    return generated


def _is_usable_access_token(token: object) -> bool:
    """Check that the login form can submit this token unchanged."""
    # Match the login form's JavaScript trim(), including the BOM.
    trim_chars = (
        "\t\n\v\f\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
        "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
    )
    if not isinstance(token, str) or not token or token == "disabled" or token != token.strip(trim_chars):
        return False
    try:
        token.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


BACKUP_DIR_NAME = "backups"
RESTORE_MARKER_NAME = ".restore_pending.json"


def _restore_marker_path() -> Path:
    # Kept under the backup directory: restore never writes there and backups
    # never include it, so an archive cannot forge or capture the marker.
    return get_data_path() / BACKUP_DIR_NAME / RESTORE_MARKER_NAME


def _write_private_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            # The marker must survive a power loss before live files change.
            os.fsync(target.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _try_lock_restore_marker(handle) -> bool:
    """Take an exclusive OS lock on the marker without waiting."""
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _recover_interrupted_restore() -> None:
    """Roll back credentials when a restore stopped before re-asserting them.

    A restore holds an OS lock on this marker while it runs, so a second
    process that imports this module mid-restore leaves it alone. After a
    crash the lock is gone and the marker holds the credentials a restart
    would otherwise load from the archive.
    """
    marker_path = _restore_marker_path()
    try:
        handle = marker_path.open("r+b")
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.warning("Could not open the restore marker %s: %s", marker_path, exc)
        return

    delete_marker = False
    try:
        if not _try_lock_restore_marker(handle):
            # Another process is still running the restore.
            return
        delete_marker = _apply_restore_marker(marker_path, handle.read())
    finally:
        handle.close()

    if not delete_marker:
        return
    try:
        # Windows cannot unlink a file while it is open; the lock is released.
        marker_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Could not remove the restore marker %s: %s", marker_path, exc)


def _apply_restore_marker(marker_path: Path, raw: bytes) -> bool:
    """Apply the marker payload; return True when it can be removed."""
    marker = None
    try:
        marker = json.loads(raw)
    except (ValueError, RecursionError):
        pass
    if not isinstance(marker, dict):
        # Keep it: the archive's credentials may be live and a later start, or
        # a token rotation, still needs to know the restore never finished.
        logger.warning("Unreadable restore marker at %s; keeping it", marker_path)
        return False

    token = marker.get("access_token")
    if not _is_usable_access_token(token):
        token = None
    token_setup_done = marker.get("token_setup_done") is True
    secret_from_env = marker.get("jwt_secret_from_env") is True
    secret = None
    restored = True
    encoded_secret = marker.get("jwt_secret")
    if isinstance(encoded_secret, str):
        try:
            secret = base64.b64decode(encoded_secret.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError):
            # Keep the marker: dropping it would leave the archive's key live.
            restored = False

    secret_path = get_data_path() / ".jwt_secret"
    try:
        if secret_from_env:
            if os.path.lexists(secret_path):
                if secret_path.is_dir() and not secret_path.is_symlink():
                    secret_path.rmdir()
                else:
                    secret_path.unlink()
        elif secret:
            if secret_path.is_dir() and not secret_path.is_symlink():
                secret_path.rmdir()
            try:
                current_secret = secret_path.read_bytes()
            except OSError:
                current_secret = None
            if current_secret != secret:
                _write_private_file(secret_path, secret)
            else:
                try:
                    os.chmod(secret_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
    except OSError as exc:
        restored = False
        logger.warning("Could not restore the JWT signing key after an interrupted restore: %s", exc)

    if token is not None or token_setup_done:
        config_path = get_data_path() / "webui.json"
        try:
            config = None
            try:
                with config_path.open(encoding="utf-8") as source:
                    loaded = json.load(source)
                if isinstance(loaded, dict):
                    config = dict(loaded)
            except (OSError, ValueError, RecursionError):
                config = None
            changed = config is None
            config = config or {}
            if token is not None and config.get("access_token") != token:
                config["access_token"] = token
                changed = True
            if token_setup_done and not config.get("token_setup_done"):
                config["token_setup_done"] = True
                changed = True
            if changed:
                if config_path.is_dir() and not config_path.is_symlink():
                    config_path.rmdir()
                try:
                    payload = json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8")
                except UnicodeEncodeError:
                    payload = json.dumps(config, indent=2, ensure_ascii=True).encode("utf-8")
                _write_private_file(config_path, payload)
            else:
                try:
                    os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError:
                    pass
        except OSError as exc:
            restored = False
            logger.warning(
                "Could not restore webui.json credentials after an interrupted restore: %s", exc
            )

    if not restored:
        # Keep the marker so the next start can retry.
        return False
    logger.warning("Restored credentials after an interrupted restore")
    return True


# JWT secret: read from environment variable, fall back to a persisted file,
# generating one on first use if neither is present. Sharing a stable secret
# across workers keeps tokens valid between restarts. Recovery must run first
# so a restore that died half-way cannot leave the archive's key live.
try:
    _recover_interrupted_restore()
except Exception:
    logger.exception("Could not recover credentials after an interrupted restore")
_JWT_SECRET = _load_persisted_jwt_secret()


def _load_webui_config() -> dict:
    """Load webui.json, treating only an absent file as a fresh config."""
    config_path = get_data_path() / "webui.json"
    try:
        with config_path.open(encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        if config_path.is_symlink():
            raise
        return {"host": "0.0.0.0", "port": 5267}
    if not isinstance(config, dict):
        raise ValueError("WebUI config must be a JSON object")
    return config


def _save_webui_config(config: dict):
    """Replace webui.json only after the new JSON has been fully written."""
    config_path = (get_data_path() / "webui.json").resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".webui.", dir=config_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, config_path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _get_or_generate_access_token() -> tuple[str | None, bool]:
    """Return the active token and whether this startup generated it."""
    try:
        config = _load_webui_config()
        token = config.get("access_token")
        if _is_usable_access_token(token):
            return token, False

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
        token = ''.join(secrets.choice(alphabet) for _ in range(16))
        config["access_token"] = token
        _save_webui_config(config)
        if _load_webui_config().get("access_token") == token:
            return token, True
    except (OSError, ValueError, RuntimeError):
        pass
    return None, False


def _update_webui_config(**changes) -> None:
    """Persist changed fields while preserving the rest of webui.json."""
    config = _load_webui_config()
    config.update(changes)
    _save_webui_config(config)


def _tokens_match(submitted: object, current: object) -> bool:
    """Compare access tokens without leaking the length of the matching prefix."""
    if not isinstance(submitted, str) or not isinstance(current, str):
        return False
    # surrogatepass keeps the encoding injective for any JSON-decodable string.
    return secrets.compare_digest(
        submitted.encode("utf-8", "surrogatepass"),
        current.encode("utf-8", "surrogatepass"),
    )


def _access_token_fingerprint(token: str) -> str:
    """Derive a short, stable fingerprint of the current access token.

    Embedding this in the JWT lets require_auth invalidate every existing
    session the moment the access token is rotated — without any per-request
    file I/O, since it is computed purely from the in-memory token value.
    """
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _create_jwt_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=5)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, _JWT_SECRET, algorithm="HS256")
    return encoded_jwt


def _verify_jwt_token(token: str) -> dict:
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


def verify_session_token(token: str, app_state) -> dict:
    """Verify a session JWT end to end: signature/expiry, auth_mode, and the
    access-token (tv) binding.

    Shared by require_auth and the plugin page/static auth checks so every
    auth-required path enforces the same claims — in particular, rotating the
    access token invalidates old sessions everywhere, not just on API routes.
    Raises HTTPException(401) on any failure and returns the decoded payload.
    """
    payload = _verify_jwt_token(token)
    current_mode = "disabled" if getattr(app_state, "disable_auth", False) else "enabled"
    if payload.get("auth_mode", "enabled") != current_mode:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token issued under a different auth mode, please re-login",
        )
    current_token = getattr(app_state, "access_token", "")
    if current_token is None or payload.get("tv") != _access_token_fingerprint(current_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated by an access-token change, please re-login",
        )
    return payload


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
