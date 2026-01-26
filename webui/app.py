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

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
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
            
            return OverviewResponse(
                total_adapters=len(self._adapters),
                active_adapters=len(
                    [a for a in self._adapters.values() if a.status == "active"]
                ),
                total_providers=len(self._providers),
                active_providers=len(
                    [p for p in self._providers.values() if p.status == "active"]
                ),
                total_messages=0,
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
            return list(self._providers.values())

        @self.app.post(
            "/api/providers",
            response_model=ProviderResponse,
            status_code=status.HTTP_201_CREATED,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def create_provider(payload: ProviderBase):
            """Create a provider"""
            provider_id = _generate_id()
            provider = ProviderResponse(id=provider_id, **payload.model_dump())
            self._providers[provider_id] = provider
            return provider

        @self.app.get(
            "/api/providers/{provider_id}",
            response_model=ProviderResponse,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def get_provider(provider_id: str):
            """Get a provider by id"""
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
            provider = self._providers.get(provider_id)
            if not provider:
                raise HTTPException(status_code=404, detail="Provider not found")
            updated = provider.model_copy(update=payload.model_dump())
            self._providers[provider_id] = updated
            return updated

        @self.app.delete(
            "/api/providers/{provider_id}",
            status_code=status.HTTP_204_NO_CONTENT,
            tags=["providers"],
            dependencies=[Depends(require_auth)],
        )
        async def delete_provider(provider_id: str):
            """Delete a provider"""
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
