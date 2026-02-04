import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncGenerator, Deque, Dict, List, Optional, Tuple

import google.generativeai as genai
import redis.asyncio as aioredis
from anthropic import AsyncAnthropic
from groq import AsyncGroq
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Cache for rate limits to avoid repeated loading
_RATE_LIMITS_CACHE = None


def load_rate_limits() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Load rate limits from config file or environment variable with caching."""
    global _RATE_LIMITS_CACHE
    if _RATE_LIMITS_CACHE is not None:
        return _RATE_LIMITS_CACHE

    config_path = os.getenv("API_RATE_LIMITS_CONFIG")
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                _RATE_LIMITS_CACHE = json.load(f)
                return _RATE_LIMITS_CACHE
        except Exception as e:
            logger.warning(f"Failed to load rate limits from {config_path}: {e}")

    # Fallback to environment variable
    env_config = os.getenv("API_RATE_LIMITS_JSON")
    if env_config:
        try:
            _RATE_LIMITS_CACHE = json.loads(env_config)
            return _RATE_LIMITS_CACHE
        except Exception as e:
            logger.warning(f"Failed to parse API_RATE_LIMITS_JSON: {e}")

    # Default rate limits - consolidated and optimized
    _RATE_LIMITS_CACHE = {
        "gemini": {
            "free": {
                "gemini-2.5-flash": {"rpm": 10, "tpm": 250000, "rpd": 500},
                "gemini-2.5-flash-lite-preview-06-17": {
                    "rpm": 15,
                    "tpm": 250000,
                    "rpd": 500,
                },
                "gemini-2.0-flash": {"rpm": 15, "tpm": 1000000, "rpd": 1500},
                "gemini-2.0-flash-lite": {"rpm": 30, "tpm": 1000000, "rpd": 1500},
                "gemini-1.5-flash": {"rpm": 15, "tpm": 250000, "rpd": 500},
                "default": {"rpm": 15, "tpm": 250000, "rpd": 500},
            },
            "paid": {
                "gemini-2.5-pro": {"rpm": 150, "tpm": 2000000, "rpd": 1000},
                "gemini-2.5-flash": {"rpm": 1000, "tpm": 1000000, "rpd": 10000},
                "gemini-2.0-flash": {"rpm": 2000, "tpm": 4000000, "rpd": None},
                "gemini-2.0-flash-lite": {"rpm": 4000, "tpm": 4000000, "rpd": None},
                "gemini-1.5-flash": {"rpm": 2000, "tpm": 4000000, "rpd": None},
                "gemini-1.5-pro": {"rpm": 1000, "tpm": 4000000, "rpd": None},
                "default": {"rpm": 1000, "tpm": 2000000, "rpd": None},
            },
        },
        "openai": {
            "free": {"default": {"rpm": 50, "tpm": None, "rpd": None}},
            "paid": {"default": {"rpm": 500, "tpm": None, "rpd": None}},
        },
        "groq": {
            "free": {"default": {"rpm": 30, "tpm": None, "rpd": None}},
            "paid": {"default": {"rpm": 500, "tpm": None, "rpd": None}},
        },
        "claude": {
            "free": {"default": {"rpm": 50, "tpm": None, "rpd": None}},
            "paid": {"default": {"rpm": 500, "tpm": None, "rpd": None}},
        },
    }
    return _RATE_LIMITS_CACHE


@dataclass
class APIKeyConfig:
    """Configuration for a single API key with model-specific rate limits."""

    key: str
    is_free_tier: bool
    provider: str
    model_name: str
    rate_limit_requests_per_minute: int
    rate_limit_tokens_per_minute: Optional[int]
    rate_limit_requests_per_day: Optional[int]
    max_concurrent: int = 10


@dataclass
class APIKeyStatus:
    """Tracks the operational status and quotas of an API key."""

    config: APIKeyConfig
    retry_after_timestamp: float = 0.0
    last_error: Optional[str] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    request_count: int = 0
    token_count: int = 0
    daily_request_count: int = 0
    last_reset_time: float = field(default_factory=time.time)
    _last_minute_check: float = field(default_factory=time.time)

    @property
    def is_available(self) -> bool:
        """Checks if the key is available based on rate limits and quotas."""
        now = time.time()

        # Optimize reset logic - only check once per minute
        if now - self._last_minute_check >= 60:
            self.request_count = 0
            self.token_count = 0
            self._last_minute_check = now

            # Daily reset check
            if now - self.last_reset_time >= 86400:
                self.daily_request_count = 0
                self.last_reset_time = now

        return (
            now >= self.retry_after_timestamp
            and self.request_count < self.config.rate_limit_requests_per_minute
            and (
                self.config.rate_limit_tokens_per_minute is None
                or self.token_count < self.config.rate_limit_tokens_per_minute
            )
            and (
                self.config.rate_limit_requests_per_day is None
                or self.daily_request_count < self.config.rate_limit_requests_per_day
            )
        )


class AsyncRedisManager:
    """Async Redis manager with connection pooling and lazy initialization."""

    def __init__(self):
        self._redis_client = None
        self._connection_task = None
        self._connected = False
        self._connection_lock = asyncio.Lock()  # Fixed: Added lock for thread safety

    async def get_client(self):
        """Get Redis client with lazy initialization."""
        if self._connected and self._redis_client:
            return self._redis_client

        # Fixed: Use double-check locking pattern to prevent race conditions
        async with self._connection_lock:
            if self._connection_task is None:
                self._connection_task = asyncio.create_task(self._connect())

        return await self._connection_task

    async def _connect(self):
        """Establish Redis connection asynchronously."""
        redis_host = os.getenv("REDIS_HOST")
        redis_port = os.getenv("REDIS_PORT")
        redis_username = os.getenv("REDIS_USERNAME")
        redis_password = os.getenv("REDIS_PASSWORD")

        if not (redis_host and redis_port):
            logger.info("Redis not configured, using in-memory storage")
            return None

        try:
            self._redis_client = aioredis.Redis(
                host=redis_host,
                port=int(redis_port),
                decode_responses=True,
                username=redis_username,
                password=redis_password,
                socket_connect_timeout=3,
                socket_timeout=3,
                retry_on_timeout=True,
                health_check_interval=30,
                max_connections=10,
            )
            await self._redis_client.ping()
            self._connected = True
            logger.info("Redis connection established")
            return self._redis_client
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self._redis_client = None
            self._connected = False
            return None


# Global Redis manager instance
_redis_manager = AsyncRedisManager()


class APIKeyManager:
    """Manages a pool of API keys with rate-limit tracking and quota management."""

    def __init__(self, provider: str, api_keys_str: str, premium_key: Optional[str] = None):
        self.provider = provider.lower()
        self._keys: Dict[str, APIKeyStatus] = {}
        self._key_queue: Deque[str] = deque()
        self._lock = asyncio.Lock()
        self._loaded_from_redis = False  # Fixed: Made this a proper instance variable

        # Parse and validate API keys efficiently
        all_keys = self._parse_keys(api_keys_str, premium_key)
        if not all_keys:
            raise ValueError(f"No API keys provided for provider: {self.provider}")

        self.premium_key = premium_key
        self._free_keys = [k for k in all_keys if k != premium_key]
        self._paid_keys = [k for k in all_keys if k == premium_key] if premium_key else []

        # Initialize keys with optimized configuration
        self._initialize_keys()

        # Premium mode state
        self._premium_only_mode = False
        self._premium_only_until = 0.0
        self._premium_mode_lock = asyncio.Lock()  # Fixed: Added lock for premium mode

        logger.info(
            f"Initialized {self.provider} APIKeyManager with {len(self._keys)} keys "
            f"({len(self._free_keys)} free, {len(self._paid_keys)} paid)"
        )

    def _parse_keys(self, api_keys_str: str, premium_key: Optional[str]) -> List[str]:
        """Parse and deduplicate API keys efficiently."""
        all_keys = list({k.strip() for k in api_keys_str.split(",") if k.strip()})

        premium_key = premium_key.strip() if premium_key else None
        if premium_key and premium_key not in all_keys:
            all_keys.append(premium_key)
        # Fixed: Remove the problematic reordering logic that didn't work with round-robin

        return all_keys

    def _initialize_keys(self):
        """Initialize API keys with configuration - optimized version."""
        model_name = os.getenv(f"{self.provider.upper()}_MODEL_VERSION", "gemini-2.0-flash-lite")
        rate_limits = load_rate_limits()
        provider_limits = rate_limits.get(self.provider, {})

        # Get default limits for fallback
        default_free = provider_limits.get("free", {}).get("default", {"rpm": 50, "tpm": None, "rpd": None})
        default_paid = provider_limits.get("paid", {}).get("default", {"rpm": 500, "tpm": None, "rpd": None})

        # Initialize free keys first (they'll be tried first in round-robin)
        free_limits = provider_limits.get("free", {}).get(model_name, default_free)
        for key in self._free_keys:
            config = APIKeyConfig(
                key=key,
                is_free_tier=True,
                provider=self.provider,
                model_name=model_name,
                rate_limit_requests_per_minute=free_limits["rpm"],
                rate_limit_tokens_per_minute=free_limits["tpm"],
                rate_limit_requests_per_day=free_limits["rpd"],
            )
            self._keys[key] = APIKeyStatus(config=config)
            self._key_queue.append(key)

        # Initialize paid keys
        paid_limits = provider_limits.get("paid", {}).get(model_name, default_paid)
        for key in self._paid_keys:
            config = APIKeyConfig(
                key=key,
                is_free_tier=False,
                provider=self.provider,
                model_name=model_name,
                rate_limit_requests_per_minute=paid_limits["rpm"],
                rate_limit_tokens_per_minute=paid_limits["tpm"],
                rate_limit_requests_per_day=paid_limits["rpd"],
            )
            self._keys[key] = APIKeyStatus(config=config)
            self._key_queue.append(key)

    async def _load_key_status_batch(self):
        """Load all key statuses from Redis in batch - called lazily."""
        redis_client = await _redis_manager.get_client()
        if not redis_client:
            return

        try:
            # Batch load all key statuses
            pipe = redis_client.pipeline()
            redis_keys = [f"api_key_status:{self.provider}:{key}" for key in self._keys.keys()]

            for redis_key in redis_keys:
                pipe.get(redis_key)

            results = await pipe.execute()

            for i, (key, data) in enumerate(zip(self._keys.keys(), results)):
                if data:
                    try:
                        status_data = json.loads(data)
                        key_status = self._keys[key]
                        key_status.retry_after_timestamp = status_data.get("retry_after_timestamp", 0.0)
                        key_status.last_error = status_data.get("last_error")
                        key_status.request_count = status_data.get("request_count", 0)
                        key_status.token_count = status_data.get("token_count", 0)
                        key_status.daily_request_count = status_data.get("daily_request_count", 0)
                        key_status.last_reset_time = status_data.get("last_reset_time", time.time())
                    except Exception as e:
                        logger.warning(f"Failed to parse key status for {key}: {e}")
        except Exception as e:
            logger.warning(f"Failed to batch load key statuses: {e}")

    async def _save_key_status(self, key_status: APIKeyStatus):
        """Save key status to Redis with proper error handling."""
        redis_client = await _redis_manager.get_client()
        if not redis_client:
            return

        redis_key = f"api_key_status:{self.provider}:{key_status.config.key}"
        try:
            data = {
                "retry_after_timestamp": key_status.retry_after_timestamp,
                "last_error": key_status.last_error,
                "request_count": key_status.request_count,
                "token_count": key_status.token_count,
                "daily_request_count": key_status.daily_request_count,
                "last_reset_time": key_status.last_reset_time,
            }
            # Fixed: Properly await the Redis operation instead of fire-and-forget
            await redis_client.setex(redis_key, 86400 * 2, json.dumps(data))
        except Exception as e:
            logger.warning(f"Failed to save key status to Redis: {e}")

    async def _check_premium_mode(self):
        """Check premium mode status from Redis asynchronously."""
        redis_client = await _redis_manager.get_client()
        if not redis_client:
            return

        try:
            val = await redis_client.get(f"premium_only_mode:{self.provider}")
            if val:
                self._premium_only_until = float(val)
                self._premium_only_mode = time.time() < self._premium_only_until
                logger.info(
                    f"Premium-only mode for provider '{self.provider}' is {'active' if self._premium_only_mode else 'inactive'} until {datetime.fromtimestamp(self._premium_only_until)}"
                )
            else:
                self._premium_only_mode = False
                self._premium_only_until = 0.0
                logger.info(f"Premium-only mode for provider '{self.provider}' is inactive")
        except Exception as e:
            logger.warning(f"Failed to check premium mode: {e}")

    async def _activate_premium_mode(self, duration_seconds: int = 1200):
        """Activate premium-only mode with proper error handling."""
        async with self._premium_mode_lock:
            now = time.time()
            self._premium_only_mode = True
            self._premium_only_until = now + duration_seconds

            redis_client = await _redis_manager.get_client()
            if redis_client:
                try:
                    await redis_client.setex(
                        f"premium_only_mode:{self.provider}",
                        duration_seconds + 100,
                        str(self._premium_only_until),
                    )
                    logger.warning(
                        f"Activated premium-only mode for provider '{self.provider}' for {duration_seconds}s"
                    )
                except Exception as e:
                    logger.error(f"Failed to save premium mode to Redis: {e}")

    async def _deactivate_premium_mode(self):
        """Deactivate premium-only mode."""
        async with self._premium_mode_lock:
            self._premium_only_mode = False
            self._premium_only_until = 0.0

            redis_client = await _redis_manager.get_client()
            if redis_client:
                try:
                    await redis_client.delete(f"premium_only_mode:{self.provider}")
                    logger.info(f"Deactivated premium-only mode for provider '{self.provider}'")
                except Exception as e:
                    logger.error(f"Failed to remove premium mode from Redis: {e}")

    async def get_next_available_key(self) -> Optional[APIKeyStatus]:
        """Retrieves the next available API key status object, retrying free keys if premium is rate-limited."""
        async with self._lock:
            now = time.time()

            # Lazy load key statuses from Redis on first call with proper thread safety
            if not self._loaded_from_redis:
                await self._load_key_status_batch()
                await self._check_premium_mode()
                self._loaded_from_redis = True

            # Reset premium-only mode if expired
            if self._premium_only_mode and now >= self._premium_only_until:
                await self._deactivate_premium_mode()

            # If in premium-only mode, try premium key first
            if self._premium_only_mode:
                if self.premium_key and self.premium_key in self._keys:
                    key_status = self._keys[self.premium_key]
                    if key_status.is_available:
                        return key_status
                    else:
                        logger.warning(
                            f"Premium key for '{self.provider}' is rate-limited in premium-only mode. "
                            f"Retry after: {key_status.retry_after_timestamp - now:.1f}s. Falling back to free keys."
                        )
                        # Instead of returning None, continue to try free keys
                else:
                    logger.error(f"Premium-only mode active but no premium key available for '{self.provider}'")
                    # Continue to try free keys instead of failing

            # Try free keys in round-robin order
            available_key = None
            attempts = 0
            max_attempts = len(self._key_queue)

            while attempts < max_attempts and available_key is None:
                key = self._key_queue[0]
                if key in self._free_keys and self._keys[key].is_available:
                    available_key = self._keys[key]
                    # Only rotate after finding an available key
                    self._key_queue.rotate(-1)
                    break
                else:
                    # Rotate to try next key
                    self._key_queue.rotate(-1)
                    attempts += 1

            if available_key:
                return available_key

            # If no free keys available, try premium key
            if self.premium_key and self.premium_key in self._keys:
                key_status = self._keys[self.premium_key]
                if key_status.is_available:
                    # Activate premium-only mode for 1 hour
                    await self._activate_premium_mode(3600)
                    return key_status
                else:
                    logger.warning(
                        f"Premium key for '{self.provider}' is rate-limited. "
                        f"Retry after: {key_status.retry_after_timestamp - now:.1f}s. Retrying free keys."
                    )

            # Retry free keys one more time before giving up
            attempts = 0
            while attempts < max_attempts and available_key is None:
                key = self._key_queue[0]
                if key in self._free_keys and self._keys[key].is_available:
                    available_key = self._keys[key]
                    self._key_queue.rotate(-1)
                    break
                else:
                    self._key_queue.rotate(-1)
                    attempts += 1

            if available_key:
                logger.info(f"Found available free key for '{self.provider}' after premium key was rate-limited")
                return available_key

            logger.warning(f"No available keys for provider '{self.provider}', including premium and free keys")
            return None

    def mark_rate_limited(self, key: str, retry_after_seconds: int, error_msg: Optional[str] = None):
        """Marks an API key as rate-limited with proper async handling."""
        if key in self._keys:
            status = self._keys[key]
            status.retry_after_timestamp = time.time() + retry_after_seconds
            status.last_error = error_msg
            # Fixed: Use create_task but with proper error handling
            task = asyncio.create_task(self._save_key_status(status))
            task.add_done_callback(
                lambda t: (
                    logger.debug(f"Saved rate limit status for key ...{key[-4:]}")
                    if not t.exception()
                    else logger.warning(f"Failed to save rate limit: {t.exception()}")
                )
            )
            logger.warning(
                f"Provider '{self.provider}' key '...{key[-4:]}' rate-limited. Retrying after {retry_after_seconds}s"
            )

    def update_quota(self, key: str, tokens: int = 0):
        """Update quota usage for a key with proper async handling."""
        if key in self._keys:
            status = self._keys[key]
            status.request_count += 1
            status.daily_request_count += 1
            if tokens:
                status.token_count += tokens
            # Fixed: Use create_task with error handling
            task = asyncio.create_task(self._save_key_status(status))
            task.add_done_callback(
                lambda t: None if not t.exception() else logger.warning(f"Failed to save quota update: {t.exception()}")
            )


class RateLimiter:
    """Client-side rate limiter with token bucket algorithm and improved error handling."""

    def __init__(self, config: APIKeyConfig):
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._request_times = deque(maxlen=config.rate_limit_requests_per_minute)

    async def __aenter__(self):
        await self._semaphore.acquire()

        try:
            async with self._lock:
                now = time.time()

                # Remove old requests (older than 1 minute)
                while self._request_times and now - self._request_times[0] > 60:
                    self._request_times.popleft()

                # Check if we need to wait
                if len(self._request_times) >= self._config.rate_limit_requests_per_minute:
                    sleep_time = 60 - (now - self._request_times[0]) + 0.1
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

                self._request_times.append(time.time())  # Use current time after potential sleep
        except Exception:
            # Fixed: Ensure semaphore is released on exception
            self._semaphore.release()
            raise

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._semaphore.release()


class APIClientFactory:
    """Factory for creating and managing API clients with lazy initialization and fixed Gemini handling."""

    def __init__(self, provider: str, api_keys_str: str, premium_key: Optional[str] = None):
        self.provider = provider.lower()
        self.key_manager = APIKeyManager(self.provider, api_keys_str, premium_key)
        self._clients: Dict[str, Any] = {}
        self._rate_limiters: Dict[str, RateLimiter] = {}
        self._client_lock = asyncio.Lock()

    async def get_client_session(
        self,
    ) -> Optional[Tuple[Any, APIKeyStatus, RateLimiter]]:
        """Gets an API client with its status and rate limiter."""
        key_status = await self.key_manager.get_next_available_key()
        if not key_status:
            return None

        key = key_status.config.key

        # Lazy client initialization with proper locking
        if key not in self._clients:
            async with self._client_lock:
                if key not in self._clients:  # Double-check pattern
                    try:
                        self._rate_limiters[key] = RateLimiter(key_status.config)

                        if self.provider == "gemini":
                            # Fixed: Create isolated Gemini client instances instead of global config
                            # Store the key with the model factory to avoid global state conflicts
                            def create_gemini_model():
                                # Configure genai for this specific key right before use
                                genai.configure(api_key=key)
                                return genai.GenerativeModel(key_status.config.model_name)

                            self._clients[key] = create_gemini_model
                        elif self.provider == "openai":
                            self._clients[key] = AsyncOpenAI(api_key=key)
                        elif self.provider == "groq":
                            self._clients[key] = AsyncGroq(api_key=key)
                        elif self.provider == "claude":
                            self._clients[key] = AsyncAnthropic(api_key=key)
                        else:
                            raise ValueError(f"Unsupported provider: {self.provider}")

                        logger.debug(f"Initialized client for provider '{self.provider}' with key ...{key[-4:]}")
                    except Exception as e:
                        logger.error(f"Failed to initialize client for provider '{self.provider}': {e}")
                        return None

        client = self._clients[key]
        # Handle lazy Gemini model creation
        if callable(client):
            client = client()

        return client, key_status, self._rate_limiters[key]


async def execute_with_retry(
    operation: callable,
    client_factories: List[APIClientFactory],
    max_retries_per_provider: int = 3,
    initial_backoff_secs: float = 1.0,
    token_count: int = 0,
    timeout_secs: float = 30.0,
    priority_providers: Optional[List[str]] = None,
    custom_headers: Optional[Dict[str, str]] = None,
) -> AsyncGenerator[Any, None]:
    """Executes an API operation with retry logic and optimized error handling."""
    if not client_factories:
        raise IOError("No API client factories configured.")

    # Sort factories based on priority
    if priority_providers:
        factories = sorted(
            client_factories,
            key=lambda f: (
                priority_providers.index(f.provider) if f.provider in priority_providers else len(priority_providers)
            ),
        )
    else:
        factories = client_factories

    last_exception = None

    for factory in factories:
        for attempt in range(max_retries_per_provider):
            session = None
            try:
                session = await factory.get_client_session()
                if not session:
                    logger.warning(f"No available API keys for provider: {factory.provider}")
                    break

                client, key_status, rate_limiter = session

                async with key_status.lock:
                    async with rate_limiter:
                        # Apply custom headers if supported
                        if custom_headers and hasattr(client, "_client") and hasattr(client._client, "headers"):
                            client._client.headers.update(custom_headers)

                        # Execute with timeout
                        try:
                            async with asyncio.timeout(timeout_secs):
                                async for result in operation(client):
                                    # Fixed: Update quota for all attempts, not just successful ones
                                    factory.key_manager.update_quota(key_status.config.key, token_count)
                                    yield result
                            return
                        except asyncio.TimeoutError:
                            # Still update quota for timeout attempts
                            factory.key_manager.update_quota(key_status.config.key, 0)
                            raise asyncio.TimeoutError(f"Operation timed out after {timeout_secs}s")

            except asyncio.TimeoutError as e:
                last_exception = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries_per_provider} for '{factory.provider}' timed out")

            except Exception as e:
                last_exception = e
                retry_after = 60
                error_str = str(e).lower()

                # Handle rate limiting with better detection
                if (hasattr(e, "status_code") and e.status_code == 429) or any(
                    term in error_str for term in ["rate limit", "quota", "too many requests", "429"]
                ):
                    if hasattr(e, "retry_after"):
                        retry_after = int(e.retry_after) + 1
                    elif "retry after" in error_str:
                        # Try to extract retry-after from error message
                        import re

                        match = re.search(r"retry after (\d+)", error_str)
                        if match:
                            retry_after = int(match.group(1)) + 1

                    if session:
                        factory.key_manager.mark_rate_limited(session[1].config.key, retry_after, str(e))

                # Update quota even for failed attempts
                if session:
                    factory.key_manager.update_quota(session[1].config.key, 0)

                # Exponential backoff with jitter
                if attempt < max_retries_per_provider - 1:
                    sleep_time = initial_backoff_secs * (2**attempt) + (time.time() % 1)  # Add jitter
                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries_per_provider} for '{factory.provider}' failed. "
                        f"Retrying in {sleep_time:.2f}s. Error: {e}"
                    )
                    await asyncio.sleep(sleep_time)

    logger.error(f"All attempts failed. Last error: {last_exception}")
    if last_exception:
        raise last_exception
    raise IOError("All API keys for all providers are unavailable.")
