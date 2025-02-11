from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator, Literal
from urllib.parse import quote

import aiohttp
import backoff
import structlog
from aiohttp import ClientTimeout

from .config import MastodonConfig
from .models import MastodonPost, Timeline, TimelineType

logger = structlog.get_logger()


class MastodonAPIError(Exception):
    """Custom exception for Mastodon API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code:
            return f"{super().__str__()} (Status: {self.status_code})"
        return super().__str__()


class RateLimiter:
    """Rate limiting for API requests using async locking."""

    def __init__(self, max_requests: int, period: int) -> None:
        self.max_requests = max_requests
        self.period = period
        self.requests: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to maintain rate limits."""
        async with self._lock:
            now = datetime.now()
            if cutoff := now - timedelta(seconds=self.period):
                self.requests = [
                    req_time for req_time in self.requests if req_time > cutoff
                ]

            if len(self.requests) >= self.max_requests:
                if oldest := min(self.requests, default=None):
                    sleep_time = (
                        oldest + timedelta(seconds=self.period) - now
                    ).total_seconds()
                    if sleep_time > 0:
                        logger.debug("rate_limit_sleep", duration=sleep_time)
                        await asyncio.sleep(sleep_time)

            self.requests.append(now)


class MastodonScraper:
    """Asynchronous Mastodon content scraper with improved error handling."""

    def __init__(self, config: MastodonConfig) -> None:
        self.config = config
        self.rate_limiter = RateLimiter(
            config.rate_limit_requests, config.rate_limit_period
        )
        self.timeout = ClientTimeout(total=config.request_timeout)

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=3,
        logger=logger,
    )
    async def _make_request(
        self, session: aiohttp.ClientSession, url: str, params: dict | None = None
    ) -> dict:
        """Make an HTTP request with retry and rate limiting."""
        await self.rate_limiter.acquire()

        async with session.get(url, timeout=self.timeout) as response:
            match response.status:
                case 200:
                    return await response.json()
                case 404:
                    raise MastodonAPIError("Resource not found", 404)
                case _:
                    raise MastodonAPIError(
                        f"API request failed with status {response.status}",
                        response.status,
                    )

    async def get_user_id(self, username: str) -> str | None:
        """Get user ID from username."""
        safe_username = quote(username)
        url = f"{self.config.instance_url}/api/v1/accounts/search"

        async with aiohttp.ClientSession() as session:
            try:
                accounts = await self._make_request(
                    session, url, params={"q": safe_username}
                )
                return next(
                    (
                        account["id"]
                        for account in accounts
                        if account["acct"] == username
                    ),
                    None,
                )
            except Exception as e:
                logger.error("user_id_fetch_error", error=str(e), username=username)
                raise MastodonAPIError(f"Failed to fetch user ID: {e}") from e

    async def fetch_timeline(
        self,
        timeline_type: TimelineType,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> Timeline:
        """Fetch posts from various timeline types."""
        match timeline_type:
            case TimelineType.USER if user_id is None:
                raise ValueError("user_id is required for user timeline")
            case TimelineType.USER:
                base_url = (
                    f"{self.config.instance_url}/api/v1/accounts/{user_id}/statuses"
                )
            case _:
                base_url = (
                    f"{self.config.instance_url}/api/v1/timelines/{timeline_type}"
                )

        params = {"limit": limit or self.config.batch_size}
        posts: list[MastodonPost] = []

        async with aiohttp.ClientSession() as session:
            while True:
                batch = await self._make_request(session, base_url, params)
                if not batch:
                    break

                posts.extend(batch)
                if len(posts) >= (limit or float("inf")):
                    break

                params["max_id"] = batch[-1]["id"]

        return {
            "posts": posts[:limit] if limit else posts,
            "last_updated": datetime.now(),
            "timeline_type": timeline_type,
        }

    async def stream_posts(
        self, user_id: str, batch_size: int | None = None
    ) -> AsyncIterator[list[MastodonPost]]:
        """Stream user posts in batches."""
        max_id: str | None = None
        batch_size = batch_size or self.config.batch_size

        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    url = (
                        f"{self.config.instance_url}/api/v1/accounts/{user_id}/statuses"
                    )
                    params = {"limit": batch_size}
                    if max_id:
                        params["max_id"] = max_id  # type: ignore

                    batch = await self._make_request(session, url, params)
                    if not batch:
                        break

                    yield batch  # type: ignore
                    max_id = batch[-1]["id"]

                except Exception as e:
                    logger.error("batch_fetch_error", error=str(e))
                    break
