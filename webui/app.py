"""
KiraAI WebUI Application
Provides a web-based admin panel for managing KiraAI system
"""
import os
import time
import uuid
import json
import secrets
import string
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn
import jwt
import psutil

from core.lifecycle import KiraLifecycle
from core.logging_manager import get_logger, log_cache_manager
from core.utils.path_utils import get_data_path

logger = get_logger("webui", "blue")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OverviewResponse(BaseModel):
    total_adapters: int = 0
    active_adapters: int = 0
    total_providers: int = 0
    active_providers: int = 0
    total_messages: int = 0
    system_status: str = "unknown"
    runtime_duration: int = 0  # System uptime in seconds
    memory_usage: int = 0  # Process memory usage in MB
    total_memory: int = 0  # Total system memory in MB


class ProviderBase(BaseModel):
    name: str
    type: str
    status: str = "inactive"
    config: Dict = Field(default_factory=dict)


class ProviderResponse(ProviderBase):
    id: str
    model_config_data: Dict = Field(default_factory=dict, alias="model_config")


class ModelCreateRequest(BaseModel):
    model_type: str
    model_id: str
    config: Dict = Field(default_factory=dict)


class ModelUpdateRequest(BaseModel):
    config: Dict = Field(default_factory=dict)


class AdapterBase(BaseModel):
    name: str
    platform: str
    status: str = "inactive"
    config: Dict = Field(default_factory=dict)


class AdapterResponse(AdapterBase):
    id: str


class PersonaBase(BaseModel):
    name: str
    description: str = ""
    traits: Dict = Field(default_factory=dict)


class PersonaResponse(PersonaBase):
    id: str


class SettingsRequest(BaseModel):
    language: str = "en"
    theme: str = "light"


class SettingsResponse(SettingsRequest):
    updated_by: Optional[str] = None


class TokenLoginRequest(BaseModel):
    access_token: str


class StickerItem(BaseModel):
    id: str
    desc: str = ""
    path: str


class StickerUpdateRequest(BaseModel):
    desc: str = ""


def _generate_strong_password(length: int = 16) -> str:
    """Generate a strong password, including upper/lower cased alphabets、digits and special characters"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    logger.info(f"Generated access_token: {token}")
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
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, "kiraai_secret_key", algorithm="HS256")
    return encoded_jwt


def _verify_jwt_token(token: str) -> Dict:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, "kiraai_secret_key", algorithms=["HS256"])
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


class KiraWebUI:
    """
    WebUI class for KiraAI admin panel
    Holds lifecycle instance for accessing system components
    """

    def __init__(self, lifecycle: KiraLifecycle):
        """
        Initialize WebUI instance

        Args:
            lifecycle: Optional KiraLifecycle instance for accessing system components
        """
        self.lifecycle = lifecycle
        self.access_token = _get_or_generate_access_token()
        self.app = FastAPI(
            title="KiraAI Admin Panel",
            description="Administration panel for KiraAI system",
            version="1.0.0",
            openapi_url="/api/openapi.json",
            docs_url="/api/docs",
        )

        # In-memory stores (placeholder until lifecycle-backed)
        self._providers: Dict[str, ProviderResponse] = {}
        self._adapters: Dict[str, AdapterResponse] = {}
        self._personas: Dict[str, PersonaResponse] = {}
        self._settings = SettingsResponse()

        # Paths
        self.webui_dir = Path(__file__).parent
        self.static_dir = self.webui_dir / "static"
        self.templates_dir = self.webui_dir / "templates"
        self.sticker_dir = get_data_path() / "sticker"

        # Setup CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Mount static files
        if self.static_dir.exists():
            self.app.mount(
                "/static", StaticFiles(directory=str(self.static_dir)), name="static"
            )
        if self.sticker_dir.exists():
            self.app.mount(
                "/sticker", StaticFiles(directory=str(self.sticker_dir)), name="sticker"
            )

        # Register routes
        self._register_routes()

    async def run(self, host: str, port: int):
        config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="info",
            loop="asyncio"
        )

        server = uvicorn.Server(config)
        await server.serve()

    def _register_routes(self):
        """Register all routes for the web application"""

        async def require_auth(authorization: Optional[str] = Header(None)) -> str:
            """Authenticate requests using JWT Bearer token."""
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing or invalid authorization header",
                )

            token = authorization.split(" ", 1)[1]
            payload = _verify_jwt_token(token)
            return payload.get("sub", "admin")

        @self.app.get("/login", response_class=HTMLResponse, tags=["web"])
        async def login_page():
            """Serve the login page"""
            template_path = self.templates_dir / "login.html"
            if template_path.exists():
                with open(template_path, "r", encoding="utf-8") as f:
                    return HTMLResponse(content=f.read())
            return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)

        @self.app.get("/", response_class=HTMLResponse, tags=["web"])
        async def index(request: Request):
            """Serve the main HTML page"""
            template_path = self.templates_dir / "index.html"
            if template_path.exists():
                with open(template_path, "r", encoding="utf-8") as f:
                    return HTMLResponse(content=f.read())
            return HTMLResponse(content="<h1>Template not found</h1>", status_code=404)

        @self.app.get("/api/health", tags=["system"])
        async def health():
            """Health check endpoint"""
            return {"status": "ok", "lifecycle_available": self.lifecycle is not None}

        @self.app.post(
            "/api/auth/login", response_model=LoginResponse, tags=["auth"]
        )
        async def token_login(payload: TokenLoginRequest):
            """Authenticate using access token and issue JWT bearer token"""
            if payload.access_token != self.access_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid access token",
                )

            access_token = _create_jwt_token(
                data={"sub": "admin"},
                expires_delta=timedelta(hours=24)
            )
            return LoginResponse(access_token=access_token)

        @self.app.post(
            "/api/auth/logout",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["auth"],
            dependencies=[Depends(require_auth)],
        )
        async def logout():
            """Logout endpoint (JWT tokens are stateless)"""
            return None

        @self.app.get(
            "/api/overview",
            response_model=OverviewResponse,
            tags=["overview"],
            dependencies=[Depends(require_auth)],
        )
        async def get_overview():
            """Get overview statistics"""
            # Calculate runtime duration from started_ts in lifecycle stats
            runtime_duration = 0
            if self.lifecycle and self.lifecycle.stats:
                started_ts = self.lifecycle.stats.get_stats("started_ts")
                if started_ts:
                    runtime_duration = int(time.time()) - started_ts
            
            # Get memory usage information using psutil
            memory_usage = 0
            total_memory = 0
            try:
                process = psutil.Process(os.getpid())
                memory_info = process.memory_info()
                # Get RSS (Resident Set Size) in MB
                memory_usage = int(memory_info.rss / (1024 * 1024))
                # Get total system memory in MB
                total_memory = int(psutil.virtual_memory().total / (1024 * 1024))
            except Exception as e:
                logger.warning(f"Failed to get memory info: {e}")
            
            total_adapters = 0
            active_adapters = 0
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
                try:
                    adapter_mgr = self.lifecycle.adapter_manager
                    adapter_infos = adapter_mgr.get_adapter_infos()
                    total_adapters = len(adapter_infos)
                    running_adapters = set(adapter_mgr.get_adapters().keys())
                    active_adapters = len(
                        [
                            info
                            for info in adapter_infos
                            if info.enabled and info.name in running_adapters
                        ]
                    )
                except Exception as e:
                    logger.error(f"Failed to collect adapter stats for overview: {e}")
                    total_adapters = len(self._adapters)
                    active_adapters = len(
                        [a for a in self._adapters.values() if a.status == "active"]
                    )
            else:
                total_adapters = len(self._adapters)
                active_adapters = len(
                    [a for a in self._adapters.values() if a.status == "active"]
                )

            total_providers = len(self._providers)
            active_providers = len(
                [p for p in self._providers.values() if p.status == "active"]
            )

            if self.lifecycle and getattr(self.lifecycle, "provider_manager", None):
                try:
                    providers_config = self.lifecycle.kira_config.get("providers", {}) or {}
                    total_providers = len(providers_config)
                    active_providers = len(
                        [
                            provider_id
                            for provider_id in providers_config.keys()
                            if provider_id in self.lifecycle.provider_manager._providers
                        ]
                    )
                except Exception as e:
                    logger.error(f"Failed to collect provider stats for overview: {e}")

            total_messages = 0
            if self.lifecycle and getattr(self.lifecycle, "stats", None):
                try:
                    message_stats = self.lifecycle.stats.get_stats("messages") or {}
                    total_messages = int(message_stats.get("total_messages", 0) or 0)
                except Exception as e:
                    logger.error(f"Failed to collect message stats for overview: {e}")

            return OverviewResponse(
                total_adapters=total_adapters,
                active_adapters=active_adapters,
                total_providers=total_providers,
                active_providers=active_providers,
                total_messages=total_messages,
                system_status="running" if self.lifecycle else "unknown",
                runtime_duration=runtime_duration,
                memory_usage=memory_usage,
                total_memory=total_memory,
            )

        @self.app.get(
            "/api/providers",
            response_model=List[ProviderResponse],
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def list_providers():
            """List all providers"""
            if not self.lifecycle or not self.lifecycle.provider_manager:
                return list(self._providers.values())

            providers = []
            configured_providers = self.lifecycle.kira_config.get("providers", {})
            active_providers = self.lifecycle.provider_manager._providers

            for provider_id in configured_providers.keys():
                provider_info = self.lifecycle.provider_manager.get_provider_info(provider_id)
                if not provider_info:
                    continue
                is_active = provider_id in active_providers
                config = self.lifecycle.kira_config.get("providers", {}).get(provider_id, {})
                providers.append(ProviderResponse(
                    id=provider_info.provider_id,
                    name=provider_info.provider_name,
                    type=provider_info.provider_type,
                    status="active" if is_active else "inactive",
                    config=provider_info.provider_config,
                    model_config_data=config.get("model_config", {})
                ))

            return providers

        @self.app.get(
            "/api/provider-types",
            response_model=List[str],
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_provider_types():
            """Get scanned provider types from lifecycle's provider manager"""
            try:
                if not self.lifecycle or not self.lifecycle.provider_manager:
                    logger.warning("Provider manager not available for get_provider_types")
                    return []
                return self.lifecycle.provider_manager.get_provider_types()
            except Exception as e:
                logger.error(f"Error getting provider types: {e}")
                return []

        @self.app.get(
            "/api/providers/schema/{provider_type}",
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_provider_schema(provider_type: str):
            """Get schema for a specific provider type"""
            if not self.lifecycle or not self.lifecycle.provider_manager:
                raise HTTPException(status_code=404, detail="Provider manager not available")
            
            schema = self.lifecycle.provider_manager.get_schema(provider_type)
            if not schema:
                raise HTTPException(status_code=404, detail=f"Schema not found for provider type: {provider_type}")
            return schema

        @self.app.get(
            "/api/adapter-platforms",
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def get_adapter_platforms():
            """Get scanned adapter platforms from lifecycle's adapter manager"""
            try:
                if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
                    logger.warning("Adapter manager not available for get_adapter_platforms")
                    return []
                return self.lifecycle.adapter_manager.get_adapter_types()
            except Exception as e:
                logger.error(f"Error getting adapter platforms: {e}")
                return []

        @self.app.get(
            "/api/adapters/schema/{platform}",
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def get_adapter_schema(platform: str):
            """Get schema for a specific adapter platform"""
            if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
                raise HTTPException(status_code=404, detail="Adapter manager not available")

            schema = self.lifecycle.adapter_manager.get_schema(platform)
            if not schema:
                raise HTTPException(status_code=404, detail=f"Schema not found for adapter platform: {platform}")
            return schema

        @self.app.post(
            "/api/providers",
            response_model=ProviderResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def create_provider(payload: ProviderBase):
            """Create a provider"""
            if not self.lifecycle or not self.lifecycle.provider_manager:
                # Fallback to in-memory for testing/standalone
                provider_id = _generate_id()
                provider_data = payload.model_dump()
                provider_data["id"] = provider_id
                provider_data["model_config_data"] = {}
                provider = ProviderResponse(**provider_data)
                self._providers[provider_id] = provider
                return provider

            provider_id = _generate_id()
            provider_type = payload.type
            
            # Use generate_provider_config to create basic config structure from schema
            try:
                # We need to manually inject the user-provided config into the generated one
                # First generate default config
                generated_config = self.lifecycle.provider_manager.generate_provider_config(provider_type, provider_id)
                
                if not generated_config:
                     raise HTTPException(status_code=400, detail=f"Failed to generate config for type {provider_type}")

                # Update with payload config
                # The payload.config contains values from the form
                # generated_config structure: {"format": type, "provider_config": {...}, "model_config": {...}}
                
                # Merge payload config into generated provider_config
                if payload.config:
                    generated_config["provider_config"].update(payload.config)
                
                if payload.name:
                    generated_config["name"] = payload.name
                
                # Save via kira_config (generate_provider_config already saved it, but we updated it)
                self.lifecycle.kira_config["providers"][provider_id] = generated_config
                self.lifecycle.kira_config.save_config()
                
                # Instantiate and register in provider manager
                config_for_instantiation = generated_config.copy()
                self.lifecycle.provider_manager.set_provider(provider_id, config_for_instantiation)
                
                return ProviderResponse(
                    id=provider_id,
                    name=payload.name or provider_id,
                    type=provider_type,
                    status="active",
                    config=generated_config["provider_config"],
                    model_config_data=generated_config.get("model_config", {})
                )
                
            except Exception as e:
                logger.error(f"Error creating provider: {e}")
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get(
            "/api/providers/{provider_id}",
            response_model=ProviderResponse,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_provider(provider_id: str):
            """Get a provider by id"""
            if self.lifecycle and self.lifecycle.provider_manager:
                provider_inst = self.lifecycle.provider_manager.get_provider(provider_id)
                provider_info = self.lifecycle.provider_manager.get_provider_info(provider_id)
                if not provider_info:
                    raise HTTPException(status_code=404, detail="Provider not found")
                config = self.lifecycle.kira_config.get("providers", {}).get(provider_id, {})
                return ProviderResponse(
                    id=provider_info.provider_id,
                    name=provider_info.provider_name,
                    type=provider_info.provider_type,
                    status="active" if provider_inst else "inactive",
                    config=provider_info.provider_config,
                    model_config_data=config.get("model_config", {})
                )

            provider = self._providers.get(provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail="Provider not found")
            return provider

        @self.app.put(
            "/api/providers/{provider_id}",
            response_model=ProviderResponse,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def update_provider(provider_id: str, payload: ProviderBase):
            """Update a provider"""
            if self.lifecycle and self.lifecycle.provider_manager:
                config = self.lifecycle.kira_config.get("providers", {}).get(provider_id)
                if not config:
                    raise HTTPException(status_code=404, detail="Provider not found")
                
                if payload.config:
                    config["provider_config"].update(payload.config)
                
                if payload.name:
                    config["name"] = payload.name
                
                # Save
                self.lifecycle.kira_config["providers"][provider_id] = config
                self.lifecycle.kira_config.save_config()
                
                # Re-instantiate
                config_for_instantiation = config.copy()
                self.lifecycle.provider_manager.set_provider(provider_id, config_for_instantiation)
                
                return ProviderResponse(
                    id=provider_id,
                    name=config.get("name", provider_id),
                    type=config.get("format", "unknown"),
                    status="active",
                    config=config["provider_config"],
                    model_config_data=config.get("model_config", {})
                )

            provider = self._providers.get(provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail="Provider not found")
            updated = provider.model_copy(update=payload.model_dump())
            self._providers[provider_id] = updated
            return updated

        @self.app.post(
            "/api/providers/{provider_id}/models",
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def add_model(provider_id: str, payload: ModelCreateRequest):
            if not self.lifecycle or not self.lifecycle.provider_manager:
                raise HTTPException(status_code=500, detail="Provider manager not available")

            model_type = payload.model_type
            model_id = payload.model_id
            if not model_type or not model_id:
                raise HTTPException(status_code=400, detail="model_type and model_id are required")

            success = self.lifecycle.provider_manager.register_model(
                provider_id=provider_id,
                model_type=model_type,
                model_id=model_id,
                config=payload.config or {}
            )
            if not success:
                raise HTTPException(status_code=400, detail="Failed to register model")

            return {"success": True}

        @self.app.get(
            "/api/providers/{provider_id}/models",
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_models(provider_id: str):
            if not self.lifecycle or not self.lifecycle.provider_manager:
                raise HTTPException(status_code=500, detail="Provider manager not available")
            models = self.lifecycle.provider_manager.get_models(provider_id)
            return models

        @self.app.put(
            "/api/providers/{provider_id}/models/{model_type}/{model_id:path}",
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def update_model(provider_id: str, model_type: str, model_id: str, payload: ModelUpdateRequest):
            if not self.lifecycle or not self.lifecycle.provider_manager:
                raise HTTPException(status_code=500, detail="Provider manager not available")
            success = self.lifecycle.provider_manager.update_model(
                provider_id=provider_id,
                model_type=model_type,
                model_id=model_id,
                config=payload.config or {}
            )
            if not success:
                raise HTTPException(status_code=404, detail="Model not found")
            return {"success": True}

        @self.app.delete(
            "/api/providers/{provider_id}/models/{model_type}/{model_id:path}",
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_model(provider_id: str, model_type: str, model_id: str):
            if not self.lifecycle or not self.lifecycle.provider_manager:
                raise HTTPException(status_code=500, detail="Provider manager not available")
            success = self.lifecycle.provider_manager.delete_model(
                provider_id=provider_id,
                model_type=model_type,
                model_id=model_id
            )
            if not success:
                raise HTTPException(status_code=404, detail="Model not found")
            return {"success": True}

        @self.app.delete(
            "/api/providers/{provider_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_provider(provider_id: str):
            """Delete a provider"""
            if self.lifecycle and self.lifecycle.provider_manager:
                found = False
                # Remove from active providers
                if provider_id in self.lifecycle.provider_manager._providers:
                    del self.lifecycle.provider_manager._providers[provider_id]
                    found = True
                
                # Remove from config
                if provider_id in self.lifecycle.kira_config.get("providers", {}):
                    del self.lifecycle.kira_config["providers"][provider_id]
                    self.lifecycle.kira_config.save_config()
                    found = True
                
                if not found:
                    raise HTTPException(status_code=404, detail="Provider not found")
                return None

            if provider_id not in self._providers:
                raise HTTPException(status_code=404, detail="Provider not found")
            self._providers.pop(provider_id, None)
            return None

        @self.app.get(
            "/api/adapters",
            response_model=List[AdapterResponse],
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def list_adapters():
            """List adapters"""
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
                try:
                    adapter_mgr = self.lifecycle.adapter_manager
                    adapter_infos = adapter_mgr.get_adapter_infos()
                    running_adapters = set(adapter_mgr.get_adapters().keys())
                    adapters: List[AdapterResponse] = []
                    for info in adapter_infos:
                        status = "active" if info.enabled and info.name in running_adapters else "inactive"
                        adapters.append(
                            AdapterResponse(
                                id=info.adapter_id,
                                name=info.name,
                                platform=info.platform,
                                status=status,
                                config=info.config,
                            )
                        )
                    return adapters
                except Exception as e:
                    logger.error(f"Error listing adapters from lifecycle: {e}")
            return list(self._adapters.values())

        @self.app.post(
            "/api/adapters",
            response_model=AdapterResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def create_adapter(payload: AdapterBase):
            """Create adapter"""
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
                name = payload.name
                platform = payload.platform
                if not name or not platform:
                    raise HTTPException(status_code=400, detail="name and platform are required")
                try:
                    adapter_mgr = self.lifecycle.adapter_manager
                    info = await adapter_mgr.create_adapter(
                        name=name,
                        platform=platform,
                        status=payload.status,
                        config=payload.config or {},
                    )
                    if not info:
                        raise HTTPException(status_code=500, detail="Failed to create adapter")
                    running_adapters = set(adapter_mgr.get_adapters().keys())
                    status_value = "active" if info.enabled and info.name in running_adapters else "inactive"
                    return AdapterResponse(
                        id=info.adapter_id,
                        name=info.name,
                        platform=info.platform,
                        status=status_value,
                        config=info.config,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"Error creating adapter: {e}")
                    raise HTTPException(status_code=500, detail=str(e))
            adapter_id = _generate_id()
            adapter = AdapterResponse(id=adapter_id, **payload.model_dump())
            self._adapters[adapter_id] = adapter
            return adapter

        @self.app.get(
            "/api/adapters/{adapter_id}",
            response_model=AdapterResponse,
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def get_adapter(adapter_id: str):
            """Get adapter by id"""
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None) and getattr(self.lifecycle, "kira_config", None):
                try:
                    adapter_mgr = self.lifecycle.adapter_manager
                    info = adapter_mgr.get_adapter_info(adapter_id)
                    if not info:
                        raise HTTPException(status_code=404, detail="Adapter not found")
                    running_adapters = set(adapter_mgr.get_adapters().keys())
                    status = "active" if info.enabled and info.name in running_adapters else "inactive"
                    return AdapterResponse(
                        id=adapter_id,
                        name=info.name,
                        platform=info.platform,
                        status=status,
                        config=info.config,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"Error getting adapter {adapter_id} from lifecycle: {e}")
            adapter = self._adapters.get(adapter_id)
            if not adapter:
                raise HTTPException(status_code=404, detail="Adapter not found")
            return adapter

        @self.app.put(
            "/api/adapters/{adapter_id}",
            response_model=AdapterResponse,
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def update_adapter(adapter_id: str, payload: AdapterBase):
            """Update adapter"""
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
                try:
                    adapter_mgr = self.lifecycle.adapter_manager
                    info = await adapter_mgr.update_adapter(
                        adapter_id=adapter_id,
                        name=payload.name,
                        platform=payload.platform,
                        status=payload.status,
                        config=payload.config or {},
                    )
                    if not info:
                        raise HTTPException(status_code=404, detail="Adapter not found")
                    running_adapters = set(adapter_mgr.get_adapters().keys())
                    status_value = "active" if info.enabled and info.name in running_adapters else "inactive"
                    return AdapterResponse(
                        id=info.adapter_id,
                        name=info.name,
                        platform=info.platform,
                        status=status_value,
                        config=info.config,
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(f"Error updating adapter {adapter_id}: {e}")
                    raise HTTPException(status_code=500, detail=str(e))
            adapter = self._adapters.get(adapter_id)
            if not adapter:
                raise HTTPException(status_code=404, detail="Adapter not found")
            updated = adapter.model_copy(update=payload.model_dump())
            self._adapters[adapter_id] = updated
            return updated

        @self.app.delete(
            "/api/adapters/{adapter_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["adapters"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_adapter(adapter_id: str):
            """Delete adapter"""
            if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
                adapter_mgr = self.lifecycle.adapter_manager
                try:
                    deleted = await adapter_mgr.delete_adapter(adapter_id)
                except Exception as e:
                    logger.error(f"Error deleting adapter {adapter_id}: {e}")
                    raise HTTPException(status_code=500, detail=str(e))
                if not deleted:
                    raise HTTPException(status_code=404, detail="Adapter not found")
                return None
            if adapter_id not in self._adapters:
                raise HTTPException(status_code=404, detail="Adapter not found")
            self._adapters.pop(adapter_id, None)
            return None

        @self.app.get(
            "/api/personas/current/content",
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def get_current_persona_content():
            """Get current persona content from lifecycle persona_manager"""
            if self.lifecycle and self.lifecycle.persona_manager:
                persona_content = self.lifecycle.persona_manager.get_persona()
                return {"content": persona_content, "format": "text"}
            raise HTTPException(status_code=404, detail="Persona manager not available")

        @self.app.put(
            "/api/personas/current/content",
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def update_current_persona_content(payload: dict):
            """Update current persona content via lifecycle persona_manager"""
            if not self.lifecycle or not self.lifecycle.persona_manager:
                raise HTTPException(status_code=404, detail="Persona manager not available")
            
            content = payload.get("content", "")
            self.lifecycle.persona_manager.update_persona(content)
            return {"content": content, "format": "text"}

        @self.app.get(
            "/api/personas",
            response_model=List[PersonaResponse],
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def list_personas():
            """List personas"""
            return list(self._personas.values())

        @self.app.post(
            "/api/personas",
            response_model=PersonaResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def create_persona(payload: PersonaBase):
            """Create persona"""
            persona_id = _generate_id()
            persona = PersonaResponse(id=persona_id, **payload.model_dump())
            self._personas[persona_id] = persona
            return persona

        @self.app.get(
            "/api/personas/{persona_id}",
            response_model=PersonaResponse,
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def get_persona(persona_id: str):
            """Get persona"""
            persona = self._personas.get(persona_id)
            if not persona:
                raise HTTPException(status_code=404, detail="Persona not found")
            return persona

        @self.app.put(
            "/api/personas/{persona_id}",
            response_model=PersonaResponse,
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def update_persona(persona_id: str, payload: PersonaBase):
            """Update persona"""
            persona = self._personas.get(persona_id)
            if not persona:
                raise HTTPException(status_code=404, detail="Persona not found")
            updated = persona.model_copy(update=payload.model_dump())
            self._personas[persona_id] = updated
            return updated

        @self.app.delete(
            "/api/personas/{persona_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["personas"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_persona(persona_id: str):
            """Delete persona"""
            if persona_id not in self._personas:
                raise HTTPException(status_code=404, detail="Persona not found")
            self._personas.pop(persona_id, None)
            return None

        @self.app.get(
            "/api/settings",
            response_model=SettingsResponse,
            tags=["settings"],
            dependencies=[Depends(require_auth)],
        )
        async def get_settings():
            """Get system settings"""
            return self._settings

        @self.app.put(
            "/api/settings",
            response_model=SettingsResponse,
            tags=["settings"],
            dependencies=[Depends(require_auth)],
        )
        async def update_settings(payload: SettingsRequest):
            """Update system settings"""
            self._settings = SettingsResponse(
                **payload.model_dump(), updated_by="admin"
            )
            return self._settings

        @self.app.get(
            "/api/configuration",
            tags=["configuration"],
            dependencies=[Depends(require_auth)],
        )
        async def get_configuration():
            if not self.lifecycle or not getattr(self.lifecycle, "kira_config", None):
                raise HTTPException(status_code=500, detail="Configuration not available")
            config = self.lifecycle.kira_config
            bot_config = config.get("bot_config", {})
            models = config.get("models", {})
            providers_config = config.get("providers", {}) or {}
            providers = []
            provider_models: Dict[str, Dict] = {}
            for provider_id, provider_cfg in providers_config.items():
                provider_name = provider_cfg.get("name") or provider_cfg.get("provider_config", {}).get("name") or provider_id
                providers.append({"id": provider_id, "name": provider_name})
                model_config: Dict = {}
                if self.lifecycle and self.lifecycle.provider_manager:
                    try:
                        models_from_manager = self.lifecycle.provider_manager.get_models(provider_id)
                        if models_from_manager:
                            model_config = models_from_manager
                    except Exception as e:
                        logger.error(f"Error getting models for provider {provider_id}: {e}")
                if not model_config:
                    model_config = provider_cfg.get("model_config", {}) or {}
                provider_models[provider_id] = model_config
            return {
                "configuration": {
                    "bot_config": bot_config,
                    "models": models,
                },
                "providers": providers,
                "provider_models": provider_models,
            }

        @self.app.post(
            "/api/configuration",
            tags=["configuration"],
            dependencies=[Depends(require_auth)],
        )
        async def update_configuration(payload: Dict):
            if not self.lifecycle or not getattr(self.lifecycle, "kira_config", None):
                raise HTTPException(status_code=500, detail="Configuration not available")
            config = self.lifecycle.kira_config
            bot_config = payload.get("bot_config")
            models = payload.get("models")
            updated = False
            if isinstance(bot_config, dict):
                config["bot_config"] = bot_config
                updated = True
            if isinstance(models, dict):
                config["models"] = models
                updated = True
            if updated:
                config.save_config()
                logger.info(f"Configuration saved")
            return {
                "status": "ok",
                "configuration": {
                    "bot_config": config.get("bot_config", {}),
                    "models": config.get("models", {}),
                },
            }

        @self.app.get(
            "/api/stickers",
            response_model=List[StickerItem],
            tags=["stickers"],
            dependencies=[Depends(require_auth)],
        )
        async def list_stickers():
            sticker_config_path = get_data_path() / "config" / "sticker.json"
            if not sticker_config_path.exists():
                return []
            try:
                with open(sticker_config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    return []
                data = json.loads(content)
            except Exception as e:
                logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to load stickers",
                )
            stickers: List[StickerItem] = []
            if not isinstance(data, dict):
                return stickers
            sticker_folder = get_data_path() / "sticker"
            for sticker_id, info in data.items():
                if not isinstance(info, dict):
                    continue
                path = info.get("path")
                desc = info.get("desc") or ""
                if not path:
                    continue
                file_path = sticker_folder / path
                if not file_path.exists():
                    continue
                stickers.append(
                    StickerItem(
                        id=str(sticker_id),
                        desc=str(desc),
                        path=str(path),
                    )
                )
            return stickers

        @self.app.post(
            "/api/stickers",
            response_model=StickerItem,
            tags=["stickers"],
            dependencies=[Depends(require_auth)],
        )
        async def add_sticker(
            file: UploadFile = File(...),
            id: Optional[str] = Form(None),
            description: Optional[str] = Form(None),
        ):
            if not file or not file.filename:
                raise HTTPException(status_code=400, detail="Sticker file is required")
            try:
                file_bytes = await file.read()
            except Exception as e:
                logger.error(f"Failed to read uploaded sticker file: {e}")
                raise HTTPException(status_code=500, detail="Failed to read sticker file")
            sticker_id = id.strip() if id else None
            desc = description.strip() if description else None
            if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
                try:
                    result = await self.lifecycle.sticker_manager.add_sticker(
                        file_bytes=file_bytes,
                        original_filename=file.filename,
                        sticker_id=sticker_id,
                        desc=desc,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))
                except Exception as e:
                    logger.error(f"Error adding sticker: {e}")
                    raise HTTPException(status_code=500, detail="Failed to add sticker")
                return StickerItem(id=result["id"], desc=result["desc"], path=result["path"])
            sticker_config_path = get_data_path() / "config" / "sticker.json"
            try:
                if sticker_config_path.exists():
                    with open(sticker_config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    data = json.loads(content) if content.strip() else {}
                else:
                    data = {}
            except Exception as e:
                logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to load stickers")
            if not isinstance(data, dict):
                data = {}
            sid = None
            if sticker_id:
                if sticker_id in data:
                    raise HTTPException(status_code=400, detail="Sticker id already exists")
                sid = sticker_id
            else:
                numeric_ids = []
                for key in data.keys():
                    if isinstance(key, str) and key.isdigit():
                        try:
                            numeric_ids.append(int(key))
                        except Exception:
                            continue
                next_id = max(numeric_ids) + 1 if numeric_ids else 1
                sid = str(next_id)
            sticker_folder = get_data_path() / "sticker"
            try:
                sticker_folder.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create sticker folder {sticker_folder}: {e}")
                raise HTTPException(status_code=500, detail="Failed to prepare sticker folder")
            from pathlib import Path as _Path
            base_name = _Path(file.filename).name
            try:
                ext = _Path(base_name).suffix
            except Exception:
                ext = ""
            if not ext:
                ext = ".png"
                base_name = f"{base_name}{ext}"
            filename = base_name
            file_path = sticker_folder / filename
            try:
                with open(file_path, "wb") as f:
                    f.write(file_bytes)
            except Exception as e:
                logger.error(f"Failed to save sticker file {file_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to save sticker file")
            final_desc = desc or ""
            data[sid] = {
                "desc": final_desc,
                "path": filename,
            }
            try:
                sticker_config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(sticker_config_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(data, indent=4, ensure_ascii=False))
            except Exception as e:
                logger.error(f"Failed to save stickers to {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to save stickers")
            return StickerItem(id=sid, desc=final_desc, path=filename)

        @self.app.get(
            "/api/stickers/{sticker_id}",
            response_model=StickerItem,
            tags=["stickers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_sticker(sticker_id: str):
            sid = str(sticker_id)
            data = None
            sticker = None
            path = ""
            desc = ""
            if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
                sticker = self.lifecycle.sticker_manager.sticker_dict.get(sid)
                if not isinstance(sticker, dict):
                    raise HTTPException(status_code=404, detail="Sticker not found")
                path = sticker.get("path") or ""
                desc = sticker.get("desc") or ""
            else:
                sticker_config_path = get_data_path() / "config" / "sticker.json"
                if not sticker_config_path.exists():
                    raise HTTPException(status_code=404, detail="Sticker not found")
                try:
                    with open(sticker_config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    data = json.loads(content) if content.strip() else {}
                except Exception as e:
                    logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
                    raise HTTPException(status_code=500, detail="Failed to load stickers")
                sticker = data.get(sid)
                if not isinstance(sticker, dict):
                    raise HTTPException(status_code=404, detail="Sticker not found")
                path = sticker.get("path") or ""
                desc = sticker.get("desc") or ""
            if not path:
                raise HTTPException(status_code=404, detail="Sticker not found")
            file_path = get_data_path() / "sticker" / path
            if not file_path.exists():
                raise HTTPException(status_code=404, detail="Sticker not found")
            return StickerItem(id=sid, desc=str(desc), path=str(path))

        @self.app.put(
            "/api/stickers/{sticker_id}",
            response_model=StickerItem,
            tags=["stickers"],
            dependencies=[Depends(require_auth)],
        )
        async def update_sticker(sticker_id: str, payload: StickerUpdateRequest):
            desc = payload.desc or ""
            if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
                try:
                    result = self.lifecycle.sticker_manager.update_sticker_desc(sticker_id, desc)
                except KeyError:
                    raise HTTPException(status_code=404, detail="Sticker not found")
                except Exception as e:
                    logger.error(f"Error updating sticker {sticker_id}: {e}")
                    raise HTTPException(status_code=500, detail="Failed to update sticker")
                return StickerItem(id=result["id"], desc=result["desc"], path=result["path"])
            sticker_config_path = get_data_path() / "config" / "sticker.json"
            if not sticker_config_path.exists():
                raise HTTPException(status_code=404, detail="Sticker not found")
            try:
                with open(sticker_config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                data = json.loads(content) if content.strip() else {}
            except Exception as e:
                logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to load stickers")
            sticker = data.get(str(sticker_id))
            if not isinstance(sticker, dict):
                raise HTTPException(status_code=404, detail="Sticker not found")
            sticker["desc"] = desc
            try:
                with open(sticker_config_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(data, indent=4, ensure_ascii=False))
            except Exception as e:
                logger.error(f"Failed to save stickers to {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to save stickers")
            path = sticker.get("path") or ""
            return StickerItem(id=str(sticker_id), desc=desc, path=path)

        @self.app.delete(
            "/api/stickers/{sticker_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["stickers"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_sticker(sticker_id: str, delete_file: bool = False):
            if self.lifecycle and getattr(self.lifecycle, "sticker_manager", None):
                try:
                    self.lifecycle.sticker_manager.delete_sticker(sticker_id, delete_file=delete_file)
                except KeyError:
                    raise HTTPException(status_code=404, detail="Sticker not found")
                except Exception as e:
                    logger.error(f"Error deleting sticker {sticker_id}: {e}")
                    raise HTTPException(status_code=500, detail="Failed to delete sticker")
                return None
            sticker_config_path = get_data_path() / "config" / "sticker.json"
            if not sticker_config_path.exists():
                raise HTTPException(status_code=404, detail="Sticker not found")
            try:
                with open(sticker_config_path, "r", encoding="utf-8") as f:
                    content = f.read()
                data = json.loads(content) if content.strip() else {}
            except Exception as e:
                logger.error(f"Failed to load stickers from {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to load stickers")
            sticker = data.pop(str(sticker_id), None)
            if not isinstance(sticker, dict):
                raise HTTPException(status_code=404, detail="Sticker not found")
            path = sticker.get("path")
            if path:
                file_path = get_data_path() / "sticker" / path
                if delete_file and file_path.exists():
                    try:
                        file_path.unlink()
                    except Exception as e:
                        logger.error(f"Error deleting sticker file {file_path}: {e}")
            try:
                with open(sticker_config_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(data, indent=4, ensure_ascii=False))
            except Exception as e:
                logger.error(f"Failed to save stickers to {sticker_config_path}: {e}")
                raise HTTPException(status_code=500, detail="Failed to save stickers")
            return None

        # Session Management Endpoints
        @self.app.get(
            "/api/sessions",
            tags=["sessions"],
            dependencies=[Depends(require_auth)],
        )
        async def list_sessions():
            """List all sessions from memory_manager"""
            if not self.lifecycle or not self.lifecycle.memory_manager:
                return {"sessions": []}
            
            # Get all session keys from chat_memory
            session_keys = list(self.lifecycle.memory_manager.chat_memory.keys())
            
            # Parse session keys and build session info
            sessions = []
            for session_key in session_keys:
                parts = session_key.split(":")
                if len(parts) >= 3:
                    adapter_name, session_type, session_id = parts[0], parts[1], ":".join(parts[2:])
                    sessions.append({
                        "id": session_key,
                        "adapter_name": adapter_name,
                        "session_type": session_type,
                        "session_id": session_id,
                        "message_count": sum(len(chunk) for chunk in self.lifecycle.memory_manager.chat_memory.get(session_key, []))
                    })
            
            return {"sessions": sessions}

        @self.app.get(
            "/api/sessions/{session_id:path}",
            tags=["sessions"],
            dependencies=[Depends(require_auth)],
        )
        async def get_session(session_id: str):
            """Get session data by session id"""
            if not self.lifecycle or not self.lifecycle.memory_manager:
                raise HTTPException(status_code=404, detail="Memory manager not available")
            
            # Read memory for the session (returns raw chunks)
            memory = self.lifecycle.memory_manager.read_memory(session_id)
            
            # Parse session id
            parts = session_id.split(":")
            if len(parts) < 3:
                raise HTTPException(status_code=400, detail="Invalid session id format")
            
            adapter_name, session_type, session_key = parts[0], parts[1], ":".join(parts[2:])
            
            return {
                "id": session_id,
                "adapter_name": adapter_name,
                "session_type": session_type,
                "session_id": session_key,
                "messages": memory
            }

        @self.app.put(
            "/api/sessions/{session_id:path}",
            tags=["sessions"],
            dependencies=[Depends(require_auth)],
        )
        async def update_session(session_id: str, payload: dict):
            """Update session data"""
            if not self.lifecycle or not self.lifecycle.memory_manager:
                raise HTTPException(status_code=404, detail="Memory manager not available")
            
            # Get messages from payload (now expects raw chunks structure)
            messages = payload.get("messages", [])
            
            # Write memory directly (assuming frontend sends back the same structure it received)
            self.lifecycle.memory_manager.write_memory(session_id, messages)
            
            return {
                "id": session_id,
                "adapter_name": session_id.split(":")[0] if ":" in session_id else "",
                "session_type": session_id.split(":")[1] if ":" in session_id else "",
                "session_id": ":".join(session_id.split(":")[2:]) if session_id.count(":") >= 2 else session_id,
                "messages": messages
            }

        @self.app.delete(
            "/api/sessions/{session_id:path}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["sessions"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_session(session_id: str):
            """Delete session"""
            if not self.lifecycle or not self.lifecycle.memory_manager:
                raise HTTPException(status_code=404, detail="Memory manager not available")
            
            # Delete session from memory
            self.lifecycle.memory_manager.delete_session(session_id)
            
            return None

        @self.app.get(
            "/api/live-log",
            tags=["logs"],
        )
        async def live_log(
            authorization: Optional[str] = Header(None),
            token: Optional[str] = None
        ):
            """
            SSE endpoint for real-time log streaming.
            Returns server-sent events containing log entries.
            Supports JWT token authentication via Authorization header or query parameter.
            """
            # Verify token from header or query parameter
            jwt_token = None
            
            # Try to get token from Authorization header
            if authorization and authorization.startswith("Bearer "):
                jwt_token = authorization.split(" ", 1)[1]
            # Fallback to query parameter
            elif token:
                jwt_token = token
            
            # Verify token if provided
            if jwt_token:
                try:
                    _verify_jwt_token(jwt_token)
                except HTTPException:
                    raise
            
            async def event_generator():
                # Create a queue for this client
                que = log_cache_manager.add_queue()
                try:
                    while True:
                        # Wait for log entry from queue
                        log_entry = await que.get()
                        # Format as SSE event
                        data = json.dumps(log_entry, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                except Exception as e:
                    logger.error(f"Error in SSE stream: {e}")
                finally:
                    # Clean up queue when client disconnects
                    log_cache_manager.remove_queue(que)

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

        @self.app.get(
            "/api/log-history",
            tags=["logs"],
            dependencies=[Depends(require_auth)],
        )
        async def get_log_history(limit: int = 100):
            """
            Get historical log entries from log cache.
            Returns the last N log entries from the in-memory cache.
            """
            try:
                # Get logs from cache manager
                cached_logs = log_cache_manager.get_cache()
                
                # Limit the number of logs returned
                if limit > 0:
                    recent_logs = cached_logs[-limit:] if len(cached_logs) > limit else cached_logs
                else:
                    recent_logs = cached_logs
                
                # Format logs for response
                logs = []
                for log in recent_logs:
                    logs.append({
                        "time": log.get("time", ""),
                        "level": log.get("level", "INFO"),
                        "name": log.get("name", ""),
                        "message": log.get("message", ""),
                        "color": log.get("color", "blue"),
                        "raw": f"{log.get('time', '')} {log.get('level', 'INFO')} [{log.get('name', '')}] {log.get('message', '')}"
                    })
                
                return {"logs": logs, "total": len(logs)}
            except Exception as e:
                logger.error(f"Error reading log cache: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to read log cache: {str(e)}"
                )

        @self.app.get(
            "/api/log-config",
            tags=["logs"],
            dependencies=[Depends(require_auth)],
        )
        async def get_log_config():
            """
            Get log configuration including max queue size.
            Returns configuration settings from core/logging_manager.py
            """
            try:
                # Import MAX_QUEUE_SIZE from logging_manager
                from core.logging_manager import MAX_QUEUE_SIZE
                
                return {
                    "maxQueueSize": MAX_QUEUE_SIZE
                }
            except Exception as e:
                logger.error(f"Error reading log config: {e}")
                # Return default value if import fails
                return {
                    "maxQueueSize": 100
                }

    def get_app(self) -> FastAPI:
        """
        Get the FastAPI application instance

        Returns:
            FastAPI application instance
        """
        return self.app


if __name__ == '__main__':
    webui = KiraWebUI()
    app = webui.get_app()
    uvicorn.run(
        app,
        host="0.0.0.0",  # Listen on all interfaces
        port=5267,  # Default port
    )
