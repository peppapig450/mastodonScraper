import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NotRequired, TypedDict, TypeVar, assert_type
from urllib.parse import quote, urlencode

import aiohttp
import backoff
from aiohttp import ClientTimeout

import structlog

logger = structlog.get_logger()

# Type definitions
T = TypeVar("T")


class MastodonPost(TypedDict):
    """Type definition for Mastodon post structure."""

    id: str
    content: str
    created_at: str
    visibility: str
    account: dict[str, Any]
    mentions: list[dict[str, Any]]
    media_attachments: list[dict[str, Any]]
    tags: NotRequired[list[dict[str, str]]]


class MastodonConfig:
    """Configuration settings for Mastodon API interactions."""

    def __init__(
        self,
        *,  # Enforce keyword arguments
        instance_url: str,
        request_timeout: int = 30,
        rate_limit_requests: int = 300,
        rate_limit_period: int = 300,
        max_retries: int = 3,
        batch_size: int = 40,
    ) -> None:
        self.instance_url = instance_url
        self.request_timeout = request_timeout
        self.rate_limit_requests = rate_limit_requests
        self.rate_limit_period = rate_limit_period
        self.max_retries = max_retries
        self.batch_size = batch_size

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"instance_url={self.instance_url!r}, "
            f"request_timeout={self.request_timeout})"
        )


class RateLimiter:
    """Implements rate limiting for API requests."""

    def __init__(self, max_requests: int, period: int) -> None:
        self.max_requests = max_requests
        self.period = period
        self.requests: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait if necessary to maintain rate limits with proper async locking."""
        async with self._lock:  # Thread-safe handling of the requests list
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


class MastodonAPIError(Exception):
    """Custom exception for Mastodon API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code:
            return f"{super().__str__()} (Status: {self.status_code})"
        return super().__str__()


class MastodonScraper:
    """Handles fetching and processing of Mastodon posts."""

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
        self, session: aiohttp.ClientSession, url: str
    ) -> dict[str, Any]:
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
        """Get user ID from username using the public API."""
        safe_username = quote(username)
        url = f"{self.config.instance_url}/api/v1/accounts/search?q={safe_username}"
        
        async with aiohttp.ClientSession() as session:
            try:
                accounts = await self._make_request(session, url)
                return next(
                    (account['id'] for account in accounts if account['acct'] == username), #type: ignore
                    None
                )
            except Exception as e:
                logger.error("user_id_fetch_error", error=str(e), username=username)
                raise MastodonAPIError(f"Failed to fetch user ID: {e}")
            
    async def fetch_posts_batch(
        self,
        session: aiohttp.ClientSession,
        user_id: str,
        max_id: str | None = None
    ) -> list[MastodonPost]:
        """Fetch a single batch of posts."""
        params = {
            "limit": self.config.batch_size,
            **({"max_id": max_id} if max_id is not None else {})
        }
        
        # Build the URL using urlencode
        base_url = f"{self.config.instance_url}/api/v1/accounts/{user_id}/statuses"
        url = f"{base_url}?{urlencode(params)}"
        
        return await self._make_request(session, url) #type: ignore
    
    async def scrape_user_posts(self, user_id: str) -> list[MastodonPost]:
        """Fetch all public posts from a user by their user ID."""
        all_posts: list[MastodonPost] = []
        max_id: str | None = None
        
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    batch = await self.fetch_posts_batch(session, user_id, max_id)
                    if not batch:
                        break

                    all_posts.extend(batch)
                    max_id = batch[-1]['id']
                    
                    logger.info(
                        "posts_fetched",
                        batch_size=len(batch),
                        total_posts=len(all_posts)
                    )
                except Exception as e:
                    logger.error("batch_fetch_error", error=str(e))
                    break
                
        return all_posts
    
def save_posts(posts: list[MastodonPost], username: str) -> Path:
    """Save posts to a JSON file."""
    output_dir = Path("mastodon_data")
    output_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = output_dir / f"{username}_posts_{timestamp}.json"
    
    filename.write_text(
        json.dumps(posts, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    
    return filename

async def main() -> None:
    import sys
    match len(sys.argv):
        case 3:
            instance_url, username = sys.argv[1:]
        case _:
            print("Usage: python script.py <instance_url> <username>")
            sys.exit(1)
            
    config = MastodonConfig(instance_url=instance_url)
    scraper = MastodonScraper(config)
    
    try:
        if user_id := await scraper.get_user_id(username):
            logger.info("user_found", user_id=user_id)
            posts = await scraper.scrape_user_posts(user_id)
            
            if posts:
                output_file = save_posts(posts, username)
                logger.info(
                    "scraping_complete",
                    post_count=len(posts),
                    output_file=str(output_file)
                )
            else:
                logger.info("no_posts_found", username=username)
        else:
            logger.error("user_not_found", username=username)
            
    except MastodonAPIError as e:
        logger.error("api_error", error=str(e))
    except Exception as e:
        logger.error("unexpected_error", error=str(e))
        raise

if __name__ == "__main__":
    asyncio.run(main(), debug=True)          