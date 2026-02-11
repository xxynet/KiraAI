from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from fastapi import FastAPI


Handler = Callable[..., Any]


@dataclass
class RouteDefinition:
    path: str
    methods: Sequence[str]
    endpoint: Handler
    name: Optional[str] = None
    tags: Optional[List[str]] = None
    response_model: Optional[Any] = None
    status_code: Optional[int] = None
    response_class: Optional[Any] = None
    dependencies: Optional[Sequence[Any]] = None
    include_in_schema: bool = True
    summary: Optional[str] = None
    description: Optional[str] = None
    responses: Optional[Dict[int, Dict[str, Any]]] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class Routes:
    def __init__(self, app: FastAPI, context: Any | None = None) -> None:
        self.app = app
        self.context = context

    def get_routes(self) -> List[RouteDefinition]:
        raise NotImplementedError

    def register(self) -> None:
        for route in self.get_routes():
            self._register_route(route)

    def _register_route(self, route: RouteDefinition) -> None:
        options: Dict[str, Any] = {
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

