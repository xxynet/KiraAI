from datetime import datetime, tzinfo


def format_timestamp(value: int | float, timezone: tzinfo | None) -> str:
    """Render Unix seconds in the configured timezone or the host's local timezone."""
    try:
        date = datetime.fromtimestamp(value, tz=timezone)
        if timezone is None:
            date = date.astimezone()
        return date.isoformat(sep=" ", timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return "Unknown"
