import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Self


@dataclass(frozen=True)
class MastodonConfig:
    """Configuration settings for Mastodon API interactions."""

    instance_url: str
    request_timeout: int = 30
    rate_limit_requests: int = 300
    rate_limit_period: int = 300
    max_retries: int = 3
    batch_size: int = 40

    @classmethod
    def from_toml(cls, path: Path) -> Self:
        """Create configuration from TOML file."""
        with path.open("rb") as f:
            config_data = tomllib.load(f)
        return cls(**config_data["mastodon"])
