import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ENV = os.getenv("ENVIRONMENT", "development").lower()
LOG_LEVEL = logging.INFO if ENV == "production" else logging.DEBUG

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler()],
)

load_dotenv(dotenv_path=Path(__file__).parent / ".env", override=True)
"""
FastAPI application to generate professional resumes from GitHub repositories using AI.
Optimized for production with modular design, robust logging, and efficient session management.
"""

import asyncio
import ipaddress
import json
import os
import platform
import re
import time
import urllib.parse
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import redis
from api_analytics.fastapi import Analytics
from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from github import Github, GithubException
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from tools import clone_repo_tool, create_resume_tool, gitingest_tool
from tools.gitingest import IGNORE_DIRS, IGNORE_EXTENSIONS
from tools.utils import robust_rmtree

# --- Analytics Counters ---
ANALYTICS_TOTAL_USERS_KEY = "analytics:total_users"
ANALYTICS_TOTAL_REPOS_KEY = "analytics:total_repos_analyzed"
ANALYTICS_TOTAL_REPO_SIZE_KEY = "analytics:total_repo_size_mb"
ANALYTICS_TOTAL_FILES_KEY = "analytics:total_files_analyzed"
ANALYTICS_MAX_REPO_SIZE_KEY = "analytics:max_repo_size_mb"
ANALYTICS_MAX_FILES_KEY = "analytics:max_files_in_repo"


async def increment_analytics_counter(key: str, unique_value: str = None):
    if not redis_client:
        return
    if unique_value:
        # Use a Redis set for unique values (e.g., users)
        await asyncio.to_thread(redis_client.sadd, key, unique_value)
    else:
        await asyncio.to_thread(redis_client.incr, key)


async def increment_repo_size_and_files(size_mb: float, file_count: int):
    if not redis_client:
        return
    await asyncio.to_thread(redis_client.incrbyfloat, ANALYTICS_TOTAL_REPO_SIZE_KEY, size_mb)
    await asyncio.to_thread(redis_client.incrby, ANALYTICS_TOTAL_FILES_KEY, file_count)
    # Track max repo size
    current_max_size = await asyncio.to_thread(redis_client.get, ANALYTICS_MAX_REPO_SIZE_KEY)
    if not current_max_size or float(size_mb) > float(current_max_size):
        await asyncio.to_thread(redis_client.set, ANALYTICS_MAX_REPO_SIZE_KEY, size_mb)
    # Track max file count
    current_max_files = await asyncio.to_thread(redis_client.get, ANALYTICS_MAX_FILES_KEY)
    if not current_max_files or int(file_count) > int(current_max_files):
        await asyncio.to_thread(redis_client.set, ANALYTICS_MAX_FILES_KEY, file_count)


async def get_analytics():
    if not redis_client:
        return {
            "total_users": None,
            "total_repos_analyzed": None,
            "total_repo_size_mb": None,
            "total_files_analyzed": None,
            "avg_repo_size_mb": None,
            "avg_files_per_repo": None,
            "max_repo_size_mb": None,
            "max_files_in_repo": None,
        }
    total_users = await asyncio.to_thread(redis_client.scard, ANALYTICS_TOTAL_USERS_KEY)
    total_repos = await asyncio.to_thread(redis_client.get, ANALYTICS_TOTAL_REPOS_KEY)
    total_repo_size = await asyncio.to_thread(redis_client.get, ANALYTICS_TOTAL_REPO_SIZE_KEY)
    total_files = await asyncio.to_thread(redis_client.get, ANALYTICS_TOTAL_FILES_KEY)
    max_repo_size = await asyncio.to_thread(redis_client.get, ANALYTICS_MAX_REPO_SIZE_KEY)
    max_files = await asyncio.to_thread(redis_client.get, ANALYTICS_MAX_FILES_KEY)
    total_repos_val = int(total_repos) if total_repos else 0
    total_repo_size_val = float(total_repo_size) if total_repo_size else 0.0
    total_files_val = int(total_files) if total_files else 0
    avg_repo_size = (total_repo_size_val / total_repos_val) if total_repos_val else 0.0
    avg_files = (total_files_val / total_repos_val) if total_repos_val else 0.0
    return {
        "total_users": total_users,
        "total_repos_analyzed": total_repos_val,
        "total_repo_size_mb": total_repo_size_val,
        "total_files_analyzed": total_files_val,
        "avg_repo_size_mb": avg_repo_size,
        "avg_files_per_repo": avg_files,
        "max_repo_size_mb": float(max_repo_size) if max_repo_size else 0.0,
        "max_files_in_repo": int(max_files) if max_files else 0,
    }


# Configuration
ENV = os.getenv("ENVIRONMENT", "development").lower()
LOG_LEVEL = logging.INFO if ENV == "production" else logging.DEBUG
SESSION_COOKIE_NAME = "gitresume_session"
SESSION_EXPIRY_SECONDS = 604800  # 7 days
CACHE_TTL = 300  # Cache time-to-live in seconds
DDoS_WINDOW = 10  # Seconds for DDoS tracking
DDoS_MAX_REQUESTS = 50  # Max requests in DDoS window
CLOUDFLARE_ONLY = os.getenv("CLOUDFLARE_ONLY", "false").lower() == "true"

# Cloudflare IP ranges for middleware
CLOUDFLARE_IP_RANGES = [
    # IPv4
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
    # IPv6
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
]
CLOUDFLARE_NETWORKS = [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_IP_RANGES]

# Global caches
repository_cache = {}
request_counts = defaultdict(list)


def get_redis_client() -> Optional[redis.Redis]:
    """Initialize and return a Redis client or None if connection fails."""
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST"),
            port=int(os.getenv("REDIS_PORT")),
            decode_responses=True,
            username=os.getenv("REDIS_USERNAME"),
            password=os.getenv("REDIS_PASSWORD"),
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30,
            max_connections=20,
        )
        client.ping()
        logging.info({"message": "Redis connection established successfully"})
        return client
    except Exception as e:
        logging.warning(
            {
                "message": "Redis connection failed, falling back to memory-based rate limiting",
                "error": str(e),
            }
        )
        return None


redis_client = get_redis_client()


def validate_github_url(url: str) -> bool:
    """Validate if the provided URL is a valid GitHub repository URL."""
    if not url or not isinstance(url, str) or re.search(r'[<>"\'`]', url):
        return False
    pattern = r"^https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+/?$"
    return bool(re.match(pattern, url))


def validate_github_token(token: str) -> bool:
    """Validate if the provided GitHub token is in a valid format."""
    if not token or not isinstance(token, str):
        return False
    pattern = r"^[a-zA-Z0-9_]+$"
    return bool(re.match(pattern, token)) and len(token) >= 20


def sanitize_input(text: str, max_length: int = 1000) -> str:
    """Sanitize input string by removing dangerous characters and enforcing length limit."""
    if not text or not isinstance(text, str):
        return ""
    return re.sub(r'[<>"\'`]', "", text.strip())[:max_length]


# Set Windows event loop policy if applicable
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    logging.info({"message": "Set WindowsProactorEventLoopPolicy for Windows compatibility"})


class GitHubSessionData(BaseModel):
    """Pydantic model for session data."""

    user_id: str
    access_token: Optional[str] = None
    github_token: Optional[str] = None
    redirect_url: Optional[str] = None
    session_id: str
    created_at: str
    repo_url: Optional[str] = None
    local_path: Optional[str] = None
    job_description: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    status: Optional[str] = None

    @field_validator("repo_url")
    def validate_repo_url(cls, v):
        if v and not validate_github_url(v):
            raise ValueError("Invalid GitHub repository URL")
        return v

    @field_validator("github_token")
    def validate_github_token_field(cls, v):
        if v and not validate_github_token(v):
            raise ValueError("Invalid GitHub token format")
        return v

    @field_validator("job_description")
    def validate_job_description(cls, v):
        if v:
            return sanitize_input(v, max_length=5000)
        return v

    model_config = {"arbitrary_types_allowed": True}


async def save_session(session: GitHubSessionData):
    """Save session data to Redis with expiry."""
    if not redis_client:
        raise RuntimeError("Redis is required for session management.")
    await asyncio.to_thread(
        redis_client.setex,
        f"session:{session.session_id}",
        SESSION_EXPIRY_SECONDS,
        session.model_dump_json(),
    )


async def get_session(session_id: str) -> Optional[GitHubSessionData]:
    """Retrieve session data from Redis."""
    if not redis_client:
        return None
    data = await asyncio.to_thread(redis_client.get, f"session:{session_id}")
    if not data:
        return None
    try:
        return GitHubSessionData(**json.loads(data))
    except Exception as e:
        logging.warning(
            {
                "message": "Invalid session data in Redis",
                "session_id": session_id,
                "error": str(e),
            }
        )
        return None


async def delete_session(session_id: str):
    """Delete session data from Redis."""
    if redis_client:
        await asyncio.to_thread(redis_client.delete, f"session:{session_id}")


def set_session_cookie(response, session_id: str):
    """Set session cookie on the response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=SESSION_EXPIRY_SECONDS,
        httponly=True,
        secure=ENV == "production",
        samesite="Lax",
    )


async def get_cached_repository_validation(repo_url: str, github_token: str = None) -> Dict[str, Any]:
    """Retrieve or validate repository access, caching results."""
    cache_key = f"{repo_url}_{hash(github_token) if github_token else 'public'}"
    current_time = time.time()

    if cache_key in repository_cache:
        cached_result, timestamp = repository_cache[cache_key]
        if current_time - timestamp < CACHE_TTL:
            logging.debug({"message": "Using cached repository validation", "repo": repo_url})
            return cached_result

    result = await validate_repository_access(repo_url, github_token)
    repository_cache[cache_key] = (result, current_time)

    # Clean up stale cache entries
    if len(repository_cache) > 1000:
        cutoff_time = current_time - CACHE_TTL
        stale_keys = [k for k, (_, timestamp) in repository_cache.items() if timestamp < cutoff_time]
        for k in stale_keys:
            repository_cache.pop(k, None)
        logging.debug(
            {
                "message": "Cleaned stale repository cache entries",
                "removed": len(stale_keys),
            }
        )

    return result


async def periodic_cleanup():
    """Periodically clean up stale cache entries."""
    while True:
        try:
            await asyncio.sleep(300)
            current_time = time.time()
            cutoff_time = current_time - CACHE_TTL
            old_keys = [k for k, (_, timestamp) in repository_cache.items() if timestamp < cutoff_time]
            for key in old_keys:
                repository_cache.pop(key, None)
            if old_keys:
                logging.info(
                    {
                        "message": "Cleaned up repository cache",
                        "removed_entries": len(old_keys),
                    }
                )
        except Exception as e:
            logging.error({"message": "Error in periodic cleanup", "error": str(e)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle, including startup and shutdown."""
    logging.info({"message": "Application starting up"})

    if redis_client:
        try:
            ping_result = await asyncio.to_thread(redis_client.ping)
            logging.info(
                {
                    "message": "Redis connection validated on startup",
                    "result": ping_result,
                }
            )
        except Exception as e:
            logging.warning({"message": "Redis validation failed on startup", "error": str(e)})

    cleanup_task = asyncio.create_task(periodic_cleanup())
    logging.info({"message": "Started periodic cleanup task"})

    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            logging.info({"message": "Periodic cleanup task cancelled"})
        logging.info({"message": "Application shutdown complete"})


# Initialize FastAPI app
app = FastAPI(
    title="GitHub to Resume Generator",
    description="Generate professional resumes from GitHub repositories using AI",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if ENV != "production" else None,
    redoc_url="/redoc" if ENV != "production" else None,
)


# Rate limiting setup
def rate_limit_key_func(request: Request) -> str:
    """Generate rate limit key based on client IP."""
    return (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP")
        or request.client.host
        if request.client
        else "unknown"
    )


limiter = Limiter(
    key_func=rate_limit_key_func,
    default_limits=["10/hour", "2/minute"],
    storage_uri=f"redis://{os.getenv('REDIS_USERNAME', 'default')}:{os.getenv('REDIS_PASSWORD')}@{os.getenv('REDIS_HOST')}:{os.getenv('REDIS_PORT')}"
    if redis_client
    else None,
)
app.state.limiter = limiter


# Remove the default SlowAPI JSON handler for RateLimitExceeded
# app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Add a custom handler to render the ratelimit.jinja template
@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Render a user-friendly rate limit error page."""
    logging.warning(
        {
            "message": "Rate limit exceeded",
            "path": request.url.path,
            "client_ip": rate_limit_key_func(request),
            "detail": str(exc.detail) if hasattr(exc, "detail") else str(exc),
        }
    )
    return templates.TemplateResponse(
        "ratelimit.jinja",
        {
            "request": request,
            "error_code": 429,
            "error_message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
        },
        status_code=429,
    )


# Middleware setup
if os.getenv("API_ANALYTICS_KEY"):
    app.add_middleware(Analytics, api_key=os.getenv("API_ANALYTICS_KEY"))
    logging.info({"message": "API Analytics middleware enabled"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET_KEY"),
    session_cookie=SESSION_COOKIE_NAME,
    max_age=SESSION_EXPIRY_SECONDS,
    same_site="lax",
    https_only=ENV == "production",
)

# Mount static files
static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory="templates")


# Middleware for HTTPS scheme and security headers
@app.middleware("http")
async def force_https_and_security_headers(request: Request, call_next):
    """Force HTTPS scheme and add security headers."""
    if "x-forwarded-proto" in request.headers:
        request.scope["scheme"] = request.headers["x-forwarded-proto"]

    if request.url.path == "/health":
        return await call_next(request)

    try:
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "X-XSS-Protection": "1; mode=block",
                "Referrer-Policy": "strict-origin-when-cross-origin",
            }
        )
        if ENV == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
    except Exception as e:
        logging.warning({"message": "Error in security headers middleware", "error": str(e)})
        return Response("Bad Request", status_code=400)


# Middleware for request validation
@app.middleware("http")
async def validate_requests(request: Request, call_next):
    """Validate incoming HTTP requests for suspicious patterns."""
    if request.url.path == "/health":
        return await call_next(request)

    if not hasattr(request, "method") or not request.method:
        logging.warning(
            {
                "message": "Invalid request without method",
                "client_ip": rate_limit_key_func(request),
            }
        )
        return Response("Bad Request", status_code=400)

    if request.url.path and any(
        suspicious in request.url.path.lower() for suspicious in ["../", ".env", "config", "admin"]
    ):
        logging.warning(
            {
                "message": "Suspicious path access attempt",
                "path": request.url.path,
                "client_ip": rate_limit_key_func(request),
            }
        )
        return Response("Not Found", status_code=404)

    return await call_next(request)


# Middleware for DDoS protection
@app.middleware("http")
async def ddos_protection_middleware(request: Request, call_next):
    """Prevent DDoS attacks by limiting requests per IP."""
    client_ip = rate_limit_key_func(request)
    current_time = time.time()
    request_counts[client_ip] = [t for t in request_counts[client_ip] if current_time - t < DDoS_WINDOW]
    request_counts[client_ip].append(current_time)
    if len(request_counts[client_ip]) > DDoS_MAX_REQUESTS:
        logging.warning({"message": "DDoS protection triggered", "ip": client_ip})
        return Response("Too many requests. Please try again later.", status_code=429)
    return await call_next(request)


# Middleware for Cloudflare-only access
if CLOUDFLARE_ONLY:

    @app.middleware("http")
    async def cloudflare_only_middleware(request: Request, call_next):
        """Restrict access to Cloudflare IPs if enabled."""
        client_ip = rate_limit_key_func(request)
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if not any(ip_obj in net for net in CLOUDFLARE_NETWORKS):
                logging.warning({"message": "Blocked non-Cloudflare IP", "ip": client_ip})
                return Response("Access denied. Please use the public site.", status_code=403)
        except Exception:
            logging.warning({"message": "Invalid IP address", "ip": client_ip})
            return Response("Access denied.", status_code=403)
        return await call_next(request)


async def get_filtered_repo_stats(local_path: str) -> Dict[str, Any]:
    """Calculates repository stats, ignoring specified directories and extensions."""

    def calculate_stats():
        file_count = 0
        total_size = 0
        repo_root = Path(local_path)
        for root, dirs, files in os.walk(repo_root):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file_name in files:
                file_path = Path(root) / file_name
                if file_path.suffix.lower() not in IGNORE_EXTENSIONS:
                    try:
                        total_size += file_path.stat().st_size
                        file_count += 1
                    except FileNotFoundError:
                        continue
        return {"file_count": file_count, "repo_size_mb": total_size / (1024 * 1024)}

    return await asyncio.to_thread(calculate_stats)


async def validate_repository_access(repo_url: str, github_token: str = None) -> Dict[str, Any]:
    """Validate access to a GitHub repository with clear error handling and messaging.

    Args:
        repo_url: URL of the GitHub repository (e.g., https://github.com/owner/repo)
        github_token: Optional GitHub personal access token for authentication

    Returns:
        Dictionary containing validation result, repository status, and error details if any
    """
    # Normalize and validate URL
    if not repo_url.startswith("https://github.com/"):
        return {
            "success": False,
            "is_public": False,
            "error_message": "Invalid GitHub repository URL. Please use format: https://github.com/owner/repo",
            "error_code": "invalid_url",
            "owner": None,
            "repo_name": None,
        }

    # Extract owner and repo name
    path_part = repo_url.replace("https://github.com/", "").strip("/")
    segments = path_part.split("/")
    if len(segments) < 2:
        return {
            "success": False,
            "is_public": False,
            "error_message": "Invalid repository path. Please provide both owner and repository name",
            "error_code": "invalid_path",
            "owner": None,
            "repo_name": None,
        }

    owner, repo_name = segments[0], segments[1]
    repo_full_name = f"{owner}/{repo_name}"

    try:
        # Initialize GitHub client
        github_client = Github(github_token) if github_token else Github()
        repo_obj = github_client.get_repo(repo_full_name)

        logging.info(
            {
                "message": "Successfully validated repository access",
                "repo": repo_url,
                "is_public": not repo_obj.private,
                "owner": owner,
                "repo_name": repo_name,
            }
        )

        return {
            "success": True,
            "is_public": not repo_obj.private,
            "error_message": None,
            "error_code": None,
            "owner": owner,
            "repo_name": repo_name,
        }

    except GithubException as e:
        error_details = {
            "repo": repo_url,
            "error": str(e),
            "status_code": getattr(e, "status", "unknown"),
        }

        error_code = "api_error"
        error_message = f"Failed to access repository: {str(e)}"

        if e.status == 404:
            logging.warning({**error_details, "message": "Repository not found or inaccessible"})
            error_code = "not_found_or_private"
            error_message = (
                "Repository not found or requires authentication. Please verify the URL and access permissions."
            )
            if not github_token:
                error_message = (
                    "Repository is private or does not exist. For private repositories, a GitHub token is required."
                )

        elif e.status == 403:
            logging.warning({**error_details, "message": "Access to repository denied"})
            error_code = "access_denied"
            error_message = "Access denied. You don't have permission to view this repository."

        elif e.status == 401:
            logging.warning({**error_details, "message": "Authentication failed"})
            error_code = "auth_required"
            error_message = "Authentication failed. Please provide a valid GitHub token."

        else:
            logging.error({**error_details, "message": "GitHub API error occurred"})

        return {
            "success": False,
            "is_public": False,
            "error_message": error_message,
            "error_code": error_code,
            "owner": owner,
            "repo_name": repo_name,
        }

    except Exception as e:
        logging.error(
            {
                "message": "Unexpected error during repository validation",
                "repo": repo_url,
                "error": str(e),
                "type": type(e).__name__,
            }
        )
        return {
            "success": False,
            "is_public": False,
            "error_message": f"An unexpected error occurred: {str(e)}",
            "error_code": "unexpected_error",
            "owner": owner,
            "repo_name": repo_name,
        }


async def enforce_private_repo_auth(
    validation_result: Dict[str, Any],
    session_data: Optional[GitHubSessionData],
    github_token: Optional[str],
) -> tuple[bool, Optional[str]]:
    """Ensure private repositories require authentication."""
    if not validation_result["success"]:
        return False, validation_result["error_message"]
    if not validation_result["is_public"] and not (session_data and (session_data.access_token or github_token)):
        return (
            False,
            "Authentication required to access private repository. Please log in with GitHub.",
        )
    return True, None


def build_index_context(
    request: Request,
    session_data: Optional[GitHubSessionData] = None,
    repo_url: str = "",
    job_description: str = "",
    error: Optional[str] = None,
    path: str = "/",
) -> Dict[str, Any]:
    """Build context for rendering the index template."""
    is_authenticated = bool(session_data and session_data.access_token)
    return {
        "request": request,
        "repo_url": repo_url,
        "job_description_hidden": job_description,
        "job_description": job_description,
        "loading": False,
        "streaming": False,
        "result": None,
        "error": error,
        "pre_filled": bool(repo_url),
        "is_authenticated": is_authenticated,
        "github_token": session_data.github_token if session_data else None,
        "is_public": False,
        "current_path": path,
        "session_id": session_data.session_id if session_data else None,
    }


@app.get("/health")
async def health_check():
    """Return application health status."""
    active_sessions = 0
    if redis_client:
        try:
            cursor = 0
            session_pattern = "session:*"
            while True:
                cursor, keys = await asyncio.to_thread(redis_client.scan, cursor, match=session_pattern, count=100)
                active_sessions += len(keys)
                if cursor == 0:
                    break
        except Exception as e:
            logging.error({"message": "Failed to count active sessions in Redis", "error": str(e)})

    analytics = await get_analytics()
    return {
        "status": "healthy",
        "environment": ENV,
        "redis_connected": redis_client is not None,
        "active_sessions": active_sessions,
        "total_users": analytics["total_users"],
        "total_repos_analyzed": analytics["total_repos_analyzed"],
        "total_repo_size_mb": analytics["total_repo_size_mb"],
        "total_files_analyzed": analytics["total_files_analyzed"],
        "avg_repo_size_mb": analytics["avg_repo_size_mb"],
        "avg_files_per_repo": analytics["avg_files_per_repo"],
        "max_repo_size_mb": analytics["max_repo_size_mb"],
        "max_files_in_repo": analytics["max_files_in_repo"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon.ico."""
    favicon_path = static_dir / "favicon-32x32.png"
    if favicon_path.exists():
        response = FileResponse(favicon_path)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    logging.warning({"message": "Favicon not found", "path": str(favicon_path)})
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/favicon-16x16.png")
async def favicon_16():
    """Serve favicon-16x16.png."""
    favicon_path = static_dir / "favicon-16x16.png"
    if favicon_path.exists():
        response = FileResponse(favicon_path)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/favicon-32x32.png")
async def favicon_32():
    """Serve favicon-32x32.png."""
    favicon_path = static_dir / "favicon-32x32.png"
    if favicon_path.exists():
        response = FileResponse(favicon_path)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    raise HTTPException(status_code=404, detail="Favicon not found")


@app.get("/apple-touch-icon.png")
async def apple_touch_icon():
    """Serve apple-touch-icon.png."""
    favicon_path = static_dir / "apple-touch-icon.png"
    if favicon_path.exists():
        response = FileResponse(favicon_path)
        response.headers["Cache-Control"] = "public, max-age=86400"
        return response
    raise HTTPException(status_code=404, detail="Apple touch icon not found")


@app.get("/login")
@limiter.limit("5/minute")
async def login(request: Request):
    """Initiate GitHub OAuth login flow."""
    session_id = str(uuid.uuid4())
    state = str(uuid.uuid4())
    request.session["session_id"] = session_id
    request.session["oauth_state"] = state

    session = GitHubSessionData(
        user_id=str(uuid.uuid4()),
        session_id=session_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await save_session(session)
    # --- Analytics: increment unique users ---
    await increment_analytics_counter(ANALYTICS_TOTAL_USERS_KEY, session_id)
    logging.info({"message": "Created new session for login", "session_id": session_id})

    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    if not github_client_id:
        logging.error({"message": "GitHub Client ID not configured"})
        raise HTTPException(status_code=500, detail="Authentication service temporarily unavailable")

    params = {
        "client_id": github_client_id,
        "redirect_uri": os.getenv("CALLBACK_URL"),
        "scope": "repo user",
        "state": state,
        "response_type": "code",
    }

    github_auth_url = f"https://github.com/login/oauth/authorize?{urllib.parse.urlencode(params)}"
    logging.info({"message": "Redirecting to GitHub OAuth", "session_id": session_id})
    response = RedirectResponse(github_auth_url)
    set_session_cookie(response, session_id)
    return response


@app.get("/callback")
@limiter.limit("5/minute")
async def callback(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle GitHub OAuth callback."""
    logging.info(
        {
            "message": "OAuth callback received",
            "query_params": dict(request.query_params),
        }
    )

    if error:
        logging.error({"message": "OAuth error from GitHub", "error": error})
        return RedirectResponse(url="/?error=oauth_failed", status_code=302)

    if not code or not state:
        logging.error(
            {
                "message": "Missing required OAuth parameters",
                "code": bool(code),
                "state": bool(state),
            }
        )
        return RedirectResponse(url="/?error=missing_params", status_code=302)

    session_state = request.session.get("oauth_state")
    if not session_state or state != session_state:
        logging.error(
            {
                "message": "Invalid OAuth state",
                "provided_state": state,
                "expected_state": session_state,
            }
        )
        return RedirectResponse(url="/?error=invalid_state", status_code=302)

    session_id = request.session.get("session_id")
    session = await get_session(session_id)
    if not session_id or not session:
        logging.error(
            {
                "message": "Invalid session during OAuth callback",
                "session_id": session_id,
            }
        )
        return RedirectResponse(url="/?error=invalid_session", status_code=302)

    github_client_id = os.getenv("GITHUB_CLIENT_ID")
    github_client_secret = os.getenv("GITHUB_CLIENT_SECRET")
    if not github_client_id or not github_client_secret:
        logging.error({"message": "GitHub OAuth configuration incomplete"})
        return RedirectResponse(url="/?error=config_error", status_code=302)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": github_client_id,
                    "client_secret": github_client_secret,
                    "code": code,
                    "redirect_uri": os.getenv("CALLBACK_URL"),
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            access_token = data.get("access_token")
            if not access_token:
                logging.error({"message": "No access token in OAuth response", "response": data})
                raise HTTPException(status_code=400, detail="Authentication failed")

            g = Github(access_token)
            user = g.get_user()
            session.access_token = access_token
            session.user_id = str(user.id)
            request.session["github_user"] = user.login
            request.session["authenticated"] = True
            await save_session(session)
            logging.info(
                {
                    "message": "User authenticated successfully",
                    "session_id": session_id,
                    "user": user.login,
                }
            )

            request.session.pop("oauth_state", None)
            response = RedirectResponse(url="/", status_code=302)
            set_session_cookie(response, session_id)
            return response
        except httpx.HTTPStatusError as e:
            logging.error(
                {
                    "message": "OAuth token exchange failed",
                    "status_code": e.response.status_code,
                    "error": str(e),
                    "response_text": e.response.text,
                }
            )
            return RedirectResponse(url="/?error=token_exchange_failed", status_code=302)
        except GithubException as e:
            logging.error({"message": "GitHub user validation failed", "error": str(e)})
            return RedirectResponse(url="/?error=user_validation_failed", status_code=302)
        except Exception as e:
            logging.error({"message": "Unexpected OAuth error", "error": str(e)})
            return RedirectResponse(url="/?error=unexpected_error", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    """Log out the user and clear session."""
    session_id = request.session.get("session_id")
    if session_id:
        session = await get_session(session_id)
        if session and session.local_path:
            try:
                await asyncio.to_thread(robust_rmtree, session.local_path)
            except Exception as e:
                logging.warning({"message": "Failed to clean up session files", "error": str(e)})
        await delete_session(session_id)
        logging.info({"message": "User logged out successfully", "session_id": session_id})

    request.session.clear()
    response = RedirectResponse(url="/")
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


async def get_generation_data(session_id: str, generation_id: str) -> Optional[dict]:
    """Retrieve generation data from Redis."""
    if not redis_client:
        return None
    data = await asyncio.to_thread(redis_client.get, f"generation:{session_id}:{generation_id}")
    if not data:
        return None
    try:
        return json.loads(data)
    except Exception as e:
        logging.warning(
            {
                "message": "Invalid generation data in Redis",
                "session_id": session_id,
                "generation_id": generation_id,
                "error": str(e),
            }
        )
        return None


async def save_generation_data(session_id: str, generation_id: str, data: dict, expiry: int = 3600):
    """Save generation data to Redis with expiry."""
    if not redis_client:
        raise RuntimeError("Redis is required for generation management.")
    await asyncio.to_thread(
        redis_client.setex,
        f"generation:{session_id}:{generation_id}",
        expiry,
        json.dumps(data),
    )


async def process_resume_generation(websocket: WebSocket, session_data: GitHubSessionData, generation_id: str):
    """Process resume generation with repository cloning, analysis, and AI generation."""
    repo_url = session_data.repo_url
    job_description = session_data.job_description
    github_token = session_data.github_token
    oauth_token = session_data.access_token
    path = session_data.redirect_url or "/"

    token_to_use = oauth_token or github_token or os.getenv("GITHUB_TOKEN")
    validation_result = await get_cached_repository_validation(repo_url, token_to_use)
    if not validation_result["success"]:
        error_message = validation_result["error_message"]
        if validation_result["error_code"] in ["auth_required", "access_denied"] and not token_to_use:
            error_message += ". Please provide a GitHub token or log in with GitHub."
        logging.error(
            {
                "message": "Repository access validation failed",
                "repo": repo_url,
                "error": error_message,
            }
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": error_message,
                    "generation_id": generation_id,
                }
            )
        )
        await save_generation_data(
            session_data.session_id,
            generation_id,
            {"status": "error", "error": error_message},
        )
        return False

    owner, repo_name = validation_result["owner"], validation_result["repo_name"]

    # --- Fast repo size check (avoid deep API calls) ---
    try:
        g = Github(token_to_use) if token_to_use else Github()
        repo_obj = g.get_repo(f"{owner}/{repo_name}")
        repo_size_mb = repo_obj.size / 1024 if hasattr(repo_obj, "size") else 0
        cache_key = f"large_repo:{owner}/{repo_name}"
        # Check redis cache for large repo flag
        if redis_client:
            cached_large = await asyncio.to_thread(redis_client.get, cache_key)
            if cached_large == "1":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "content": "This repository is too large to process. Large repositories are not supported. If you would like to help support the developer to cover expenses for large repo support, please reach out!",
                            "generation_id": generation_id,
                        }
                    )
                )
                await save_generation_data(
                    session_data.session_id,
                    generation_id,
                    {"status": "error", "error": "Large repository not supported."},
                )
                return False
        if repo_size_mb > 150:  # 150 MB limit for fast pre-check
            if redis_client:
                await asyncio.to_thread(redis_client.setex, cache_key, 86400, "1")  # Cache for 1 day
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "content": f"This repository is too large to process (over 150 MB, {repo_size_mb:.2f} MB). Large repositories are not supported. If you would like to help support the developer to cover expenses for large repo support, please reach out!",
                        "generation_id": generation_id,
                    }
                )
            )
            await save_generation_data(
                session_data.session_id,
                generation_id,
                {"status": "error", "error": "Large repository not supported."},
            )
            return False
    except Exception as e:
        logging.warning(
            {
                "message": "Could not estimate repository size for fast check",
                "error": str(e),
            }
        )

    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "content": f"🔄 Checking for existing repository clone: {repo_url}",
                "generation_id": generation_id,
            }
        )
    )
    await save_generation_data(session_data.session_id, generation_id, {"status": "cloning"})

    local_path = session_data.local_path
    clone_result = None
    if local_path and Path(local_path).exists():
        await websocket.send_text(
            json.dumps(
                {
                    "type": "status",
                    "content": "🔄 Using existing repository clone",
                    "generation_id": generation_id,
                }
            )
        )
        stats = await get_filtered_repo_stats(local_path)
        clone_result = {
            "success": True,
            "local_path": local_path,
            "repo_name": f"{owner}/{repo_name}",
            "repo_size_mb": stats["repo_size_mb"],
            "file_count": stats["file_count"],
        }
    else:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "status",
                    "content": f"🔄 Cloning repository: {repo_url}",
                    "generation_id": generation_id,
                }
            )
        )
        target_dir = Path(f"/tmp/{session_data.session_id}")
        clone_result = await clone_repo_tool(repo_url, str(target_dir), token_to_use)
        local_path = clone_result.get("local_path")
        session_data.local_path = local_path
        await save_session(session_data)

    # --- Strict file count check after clone ---
    if clone_result and clone_result.get("success") and local_path:
        if "file_count" not in clone_result:
            stats = await get_filtered_repo_stats(local_path)
            clone_result["file_count"] = stats["file_count"]
            clone_result["repo_size_mb"] = stats["repo_size_mb"]
        file_count = clone_result["file_count"]
        cache_key = f"large_repo:{owner}/{repo_name}"
        if redis_client:
            cached_large = await asyncio.to_thread(redis_client.get, cache_key)
            if cached_large == "1":
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "content": f"This repository contains {file_count} files, which exceeds the current limit of 100 files. Large repositories are not supported. If you would like to help support the developer to cover expenses for large repo support, please reach out!",
                            "generation_id": generation_id,
                        }
                    )
                )
                await save_generation_data(
                    session_data.session_id,
                    generation_id,
                    {"status": "error", "error": "Large repository not supported."},
                )
                try:
                    await asyncio.to_thread(robust_rmtree, local_path)
                except Exception as e:
                    logging.warning(
                        {
                            "message": "Failed to clean up after large repo abort",
                            "error": str(e),
                        }
                    )
                session_data.local_path = None
                await save_session(session_data)
                return False
        if file_count > 200:
            if redis_client:
                await asyncio.to_thread(redis_client.setex, cache_key, 86400, "1")  # Cache for 1 day
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "content": f"This repository contains {file_count} files, which exceeds the current limit of 100 files. Large repositories are not supported. If you would like to help support the developer to cover expenses for large repo support, please reach out!",
                        "generation_id": generation_id,
                    }
                )
            )
            await save_generation_data(
                session_data.session_id,
                generation_id,
                {"status": "error", "error": "Large repository not supported."},
            )
            # Clean up the cloned repo
            try:
                await asyncio.to_thread(robust_rmtree, local_path)
            except Exception as e:
                logging.warning(
                    {
                        "message": "Failed to clean up after large repo abort",
                        "error": str(e),
                    }
                )
            session_data.local_path = None
            await save_session(session_data)
            return False

    if not clone_result or not clone_result["success"]:
        error_msg = clone_result.get("error", "Unknown cloning error") if clone_result else "Failed to clone repository"
        logging.error(
            {
                "message": "Repository cloning failed",
                "repo": repo_url,
                "error": error_msg,
                "session_id": session_data.session_id,
            }
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": f"Failed to clone repository: {error_msg}",
                    "generation_id": generation_id,
                }
            )
        )
        await save_generation_data(
            session_data.session_id,
            generation_id,
            {"status": "error", "error": error_msg},
        )
        return False

    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "content": "📊 Analyzing repository structure...",
                "generation_id": generation_id,
            }
        )
    )
    await save_generation_data(session_data.session_id, generation_id, {"status": "analyzing"})

    ingest_result = await gitingest_tool(clone_result["local_path"])
    if not ingest_result["success"]:
        error_msg = ingest_result.get("error", "Unknown analysis error")
        logging.error(
            {
                "message": "Repository analysis failed",
                "repo": repo_url,
                "error": error_msg,
                "session_id": session_data.session_id,
            }
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": f"Failed to analyze repository: {error_msg}",
                    "generation_id": generation_id,
                }
            )
        )
        await save_generation_data(
            session_data.session_id,
            generation_id,
            {"status": "error", "error": error_msg},
        )
        return False

    # --- Analytics: increment repos analyzed, repo size, and file count ---
    await increment_analytics_counter(ANALYTICS_TOTAL_REPOS_KEY)
    repo_size_mb = clone_result.get("repo_size_mb", 0)
    file_count = clone_result.get("file_count", 0)
    await increment_repo_size_and_files(repo_size_mb, file_count)

    await websocket.send_text(
        json.dumps(
            {
                "type": "status",
                "content": "📝 Generating resume content with AI...",
                "generation_id": generation_id,
            }
        )
    )
    await save_generation_data(session_data.session_id, generation_id, {"status": "generating"})

    resume_result = await create_resume_tool(
        gitingest_summary=ingest_result["summary"],
        gitingest_tree=ingest_result["tree"],
        gitingest_content=ingest_result["content"],
        project_name=clone_result["repo_name"],
        job_description=job_description,
        websocket=websocket,
        generation_id=generation_id,
    )

    if not resume_result["success"]:
        error_msg = resume_result.get("error", "Unknown generation error")
        logging.error(
            {
                "message": "Resume generation failed",
                "repo": repo_url,
                "error": error_msg,
                "session_id": session_data.session_id,
            }
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": f"Failed to generate resume: {error_msg}",
                    "generation_id": generation_id,
                }
            )
        )
        await save_generation_data(
            session_data.session_id,
            generation_id,
            {"status": "error", "error": error_msg},
        )
        return False

    final_result = {
        "project_title": resume_result["project_title"],
        "tech_stack": resume_result["tech_stack"],
        "bullet_points": [str(bp) for bp in resume_result["bullet_points"]],
        "additional_notes": resume_result.get("additional_notes", ""),
        "future_plans": resume_result.get("future_plans", ""),
        "potential_advancements": resume_result.get("potential_advancements", ""),
        "interview_questions": resume_result.get("interview_questions", []),
        "repo_info": {"name": clone_result["repo_name"]},
    }

    await websocket.send_text(
        json.dumps(
            {
                "type": "complete",
                "content": "Generation complete!",
                "result": final_result,
                "redirect_path": path,
                "generation_id": generation_id,
            }
        )
    )
    await save_generation_data(
        session_data.session_id,
        generation_id,
        {"status": "complete", "result": final_result},
    )
    session_data.status = "complete"
    await save_session(session_data)
    logging.info(
        {
            "message": "Resume generation completed successfully",
            "session_id": session_data.session_id,
            "repo": repo_url,
            "generation_id": generation_id,
        }
    )
    return True


@app.get("/{path:path}", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def dynamic_github_route(request: Request, path: str):
    """Handle dynamic GitHub repository URL routes."""
    session_id = request.session.get("session_id")
    session_data = await get_session(session_id) if session_id else None
    skip_paths = {
        "",
        "health",
        "favicon.ico",
        "favicon-16x16.png",
        "favicon-32x32.png",
        "apple-touch-icon.png",
        "static",
        "ws",
        "login",
        "callback",
        "logout",
        "docs",
        "redoc",
        "openapi.json",
    }

    # Handle root URL and reserved paths
    if path in skip_paths:
        if path == "":
            return await home(request)  # Redirect to home endpoint for root URL
        logging.warning(
            {
                "message": "Access attempt to restricted path",
                "path": path,
                "client_ip": rate_limit_key_func(request),
            }
        )
        raise HTTPException(status_code=404, detail="Not found")

    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        logging.info({"message": "Invalid GitHub URL format", "path": path})
        domain = request.headers.get("host") or request.url.hostname or "this-site"
        return templates.TemplateResponse(
            "index.jinja",
            build_index_context(
                request=request,
                repo_url="",
                job_description="",
                error=f"Invalid GitHub URL format. Expected format: {domain}/username/repository",
                path=f"/{path}",
            ),
        )

    username, repo = sanitize_input(segments[0], 100), sanitize_input(segments[1], 100)
    if (
        not username
        or not repo
        or not re.match(r"^[a-zA-Z0-9_.-]+$", username)
        or not re.match(r"^[a-zA-Z0-9_.-]+$", repo)
    ):
        logging.warning(
            {
                "message": "Invalid username or repository name",
                "username": username,
                "repo": repo,
            }
        )
        return templates.TemplateResponse(
            "index.jinja",
            build_index_context(
                request=request,
                repo_url="",
                job_description="",
                error="Invalid repository name format",
                path=f"/{path}",
            ),
        )

    github_url = f"https://github.com/{username}/{repo}"
    validation_result = await get_cached_repository_validation(
        github_url, session_data.access_token if session_data else None
    )
    if not validation_result["success"]:
        return templates.TemplateResponse(
            "index.jinja",
            build_index_context(
                request=request,
                repo_url=github_url,
                job_description="",
                error=validation_result["error_message"],
                path=f"/{path}",
            ),
        )

    return templates.TemplateResponse(
        "index.jinja",
        build_index_context(
            request=request,
            repo_url=github_url,
            job_description="",
            error=None,
            path=f"/{path}",
        ),
    )


@app.post("/{path:path}", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def dynamic_github_route_post(
    request: Request,
    path: str,
    repo_url: str = Form(...),
    job_description_hidden: str = Form(""),
    github_token: Optional[str] = Form(None),
):
    """Handle POST requests for dynamic GitHub repository URLs."""
    repo_url = sanitize_input(repo_url, 200)
    job_description = sanitize_input(job_description_hidden, 5000)
    github_token = sanitize_input(github_token, 100) if github_token and validate_github_token(github_token) else None

    session_id = request.session.get("session_id")
    session_data = await get_session(session_id) if session_id else None

    validation_result = await get_cached_repository_validation(
        repo_url, github_token or (session_data.access_token if session_data else None)
    )
    is_allowed, error_msg = await enforce_private_repo_auth(validation_result, session_data, github_token)
    if not is_allowed:
        return templates.TemplateResponse(
            "index.jinja",
            build_index_context(
                request=request,
                session_data=session_data,
                repo_url=repo_url,
                job_description=job_description,
                error=error_msg,
                path=f"/{path}",
            ),
        )

    if not session_id or not session_data:
        session_id = str(uuid.uuid4())
        request.session["session_id"] = session_id
        session_data = GitHubSessionData(
            user_id=session_id,
            session_id=session_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            github_token=github_token,
            access_token=None,
            repo_url=repo_url,
            job_description=job_description.strip() or None,
            status="pending",
        )
        # --- Analytics: increment unique users ---
        await increment_analytics_counter(ANALYTICS_TOTAL_USERS_KEY, session_id)
    else:
        session_data.repo_url = repo_url
        session_data.job_description = job_description.strip() or None
        if github_token:
            session_data.github_token = github_token
        session_data.created_at = datetime.now(timezone.utc).isoformat()
        session_data.status = "pending"
        session_data.result = None
        session_data.local_path = None

    dynamic_path_segment = path or "/".join(repo_url.replace("https://github.com/", "").split("/")[:2])
    session_data.redirect_url = f"/{dynamic_path_segment}"
    await save_session(session_data)

    logging.info(
        {
            "message": "Resume generation session initiated",
            "session_id": session_id,
            "is_authenticated": bool(session_data.access_token),
        }
    )
    response = templates.TemplateResponse(
        "index.jinja",
        {
            **build_index_context(
                request,
                session_data,
                repo_url,
                job_description,
                path=f"/{dynamic_path_segment}",
            ),
            "streaming": True,
            "is_public": validation_result.get("is_public", False),
        },
    )
    set_session_cookie(response, session_id)
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the home page."""
    session_id = request.session.get("session_id")
    session_data = await get_session(session_id) if session_id else None
    return templates.TemplateResponse("index.jinja", build_index_context(request, session_data))


@app.post("/", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def generate_resume(
    request: Request,
    repo_url: str = Form(...),
    job_description_hidden: str = Form(""),
    github_token: Optional[str] = Form(None),
):
    """Handle resume generation POST requests."""
    return await dynamic_github_route_post(request, "", repo_url, job_description_hidden, github_token)


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, generation_id: str = Query(...)):
    """Handle WebSocket connections for resume generation."""
    logging.info(
        {
            "message": "WebSocket connection initiated",
            "session_id": session_id,
            "generation_id": generation_id,
        }
    )

    if not re.match(r"^[a-f0-9-]{36}$", session_id) or not re.match(r"^[a-f0-9-]{36}$", generation_id):
        logging.error(
            {
                "message": "Invalid ID format",
                "session_id": session_id,
                "generation_id": generation_id,
            }
        )
        await websocket.close(code=4003, reason="Invalid session or generation ID")
        return

    await websocket.accept()
    session_data = await get_session(session_id)
    if not session_data:
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": "Invalid session ID",
                    "generation_id": generation_id,
                }
            )
        )
        await websocket.close(code=4003)
        return

    existing_generation = await get_generation_data(session_id, generation_id)
    if existing_generation and existing_generation.get("status") == "complete":
        await websocket.send_text(
            json.dumps(
                {
                    "type": "complete",
                    "content": "Generation complete!",
                    "result": existing_generation.get("result"),
                    "redirect_path": session_data.redirect_url or "/",
                    "generation_id": generation_id,
                }
            )
        )
        await websocket.close(code=1000)
        return

    session_data.status = "active"
    await save_session(session_data)

    try:
        success = await process_resume_generation(websocket, session_data, generation_id)
        if not success:
            await websocket.close(code=4002)
    except WebSocketDisconnect:
        logging.warning(
            {
                "message": "WebSocket disconnected by client",
                "session_id": session_id,
                "generation_id": generation_id,
            }
        )
        await save_generation_data(session_id, generation_id, {"status": "disconnected"})
        session_data.status = "disconnected"
        await save_session(session_data)
    except Exception as e:
        logging.error(
            {
                "message": "Unrecoverable WebSocket error",
                "session_id": session_id,
                "generation_id": generation_id,
                "error": str(e),
                "type": type(e).__name__,
            }
        )
        await websocket.send_text(
            json.dumps(
                {
                    "type": "error",
                    "content": f"Unexpected error: {str(e)}",
                    "generation_id": generation_id,
                }
            )
        )
        await save_generation_data(session_id, generation_id, {"status": "error", "error": str(e)})
        session_data.status = "error"
        await save_session(session_data)
        await websocket.close(code=4000)
    finally:
        if session_data.local_path:
            try:
                logging.info(
                    {
                        "message": "Cleaning up local repository files",
                        "session_id": session_id,
                        "path": session_data.local_path,
                    }
                )
                await asyncio.to_thread(robust_rmtree, session_data.local_path)
                session_data.local_path = None
                await save_session(session_data)
            except Exception as e:
                logging.error(
                    {
                        "message": "Failed to cleanup local files",
                        "session_id": session_id,
                        "error": str(e),
                    }
                )
        if session_data.status == "active":
            session_data.status = "complete"
            await save_session(session_data)
        await websocket.close(code=1000)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with custom templates."""
    logging.warning(
        {
            "message": "HTTP exception",
            "status_code": exc.status_code,
            "detail": str(exc.detail),
            "path": request.url.path,
        }
    )
    # Custom error context for template
    error_context = {
        "request": request,
        "error_code": exc.status_code,
        "error_title": exc.detail if hasattr(exc, "detail") and exc.detail else "Error",
        "error_message": str(exc.detail) if hasattr(exc, "detail") and exc.detail else "An error occurred.",
    }
    if exc.status_code == 404:
        # Always render 404.jinja with error context
        return templates.TemplateResponse("404.jinja", error_context, status_code=404)
    elif exc.status_code == 429:
        return templates.TemplateResponse("ratelimit.jinja", error_context, status_code=429)
    return templates.TemplateResponse("500.jinja", error_context, status_code=exc.status_code)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions with a user-friendly error page."""
    logging.error(
        {
            "message": "Unhandled exception",
            "error": str(exc),
            "type": type(exc).__name__,
            "path": request.url.path,
            "method": request.method,
        }
    )
    error_context = {
        "request": request,
        "error_code": 500,
        "error_title": "Internal Server Error",
        "error_message": str(exc) or "An unexpected error occurred.",
    }
    return templates.TemplateResponse("500.jinja", error_context, status_code=500)


@app.route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def fallback_route(request: Request, full_path: str):
    """Handle unmatched routes."""
    logging.warning(
        {
            "message": "Unmatched route accessed",
            "path": full_path,
            "method": request.method,
            "client_ip": rate_limit_key_func(request),
            "user_agent": request.headers.get("User-Agent", ""),
        }
    )
    return templates.TemplateResponse("404.jinja", {"request": request}, status_code=404)
