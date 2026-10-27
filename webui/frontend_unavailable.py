"""Self-contained recovery page for an unavailable WebUI build."""

import json
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import quote

from fastapi.responses import HTMLResponse

from core.config.default import VERSION

_WEBUI_DIR = Path(__file__).parent
# Load bundled resources once, before serving requests on the event loop.
_MESSAGES = {
    locale: json.loads(
        (_WEBUI_DIR / "locales" / f"frontend_unavailable.{locale}.json").read_text(encoding="utf-8")
    )
    for locale in ("en", "zh")
}
_TEMPLATE = Template(
    (_WEBUI_DIR / "templates" / "frontend_unavailable.html").read_text(encoding="utf-8")
)
_PAGE = _TEMPLATE.substitute(
    {
        key: "".join(
            f'<span lang="{locale}" data-language="{locale}">{escape(messages[key])}</span>'
            for locale, messages in _MESSAGES.items()
        )
        for key in _MESSAGES["en"]
    },
    page_title=escape(_MESSAGES["en"]["title"]),
    release_url=escape(
        f"https://github.com/KiraAI-Dev/KiraAI/releases/tag/{quote(VERSION, safe='')}",
        quote=True,
    ),
)


def frontend_unavailable_response() -> HTMLResponse:
    return HTMLResponse(
        content=_PAGE,
        status_code=503,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
