from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

if TYPE_CHECKING:
    from core.lifecycle import KiraLifecycle


Handler = Callable[..., Any]


@dataclass
class RouteDefinition:
    path: str
    methods: Sequence[str]
    endpoint: Handler
    name: str | None = None
    tags: list[str] | None = None
    response_model: Any | None = None
    status_code: int | None = None
    response_class: Any | None = None
    dependencies: Sequence[Any] | None = None
    include_in_schema: bool = True
    summary: str | None = None
    description: str | None = None
    responses: dict[int, dict[str, Any]] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Routes:
    def __init__(self, app: FastAPI, lifecycle: KiraLifecycle | None = None) -> None:
        self.app = app
        self.lifecycle = lifecycle

    def get_routes(self) -> list[RouteDefinition]:
        raise NotImplementedError

    def register(self) -> None:
        for route in self.get_routes():
            self._register_route(route)

    def _register_route(self, route: RouteDefinition) -> None:
        options: dict[str, Any] = {
            "response_model": route.response_model,
            "status_code": route.status_code,
            "tags": route.tags,
            "dependencies": route.dependencies,
            "summary": route.summary,
            "description": route.description,
            "responses": route.responses,
            "name": route.name,
            "include_in_schema": route.include_in_schema,
            "response_class": route.response_class,
        }
        options.update(route.extra)
        filtered_options = {key: value for key, value in options.items() if value is not None}
        self.app.add_api_route(
            route.path,
            route.endpoint,
            methods=list(route.methods),
            **filtered_options,
        )

