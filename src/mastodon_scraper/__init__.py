"""
Mastodon Scraper - A modern Python tool for scraping Mastodon content.
"""

from .config import MastodonConfig
from .models import MastodonPost, Timeline, TimelineType
from .scraper import MastodonScraper

__version__ = "0.1.0"
__all__ = [
    "MastodonScraper",
    "MastodonConfig",
    "MastodonPost",
    "Timeline",
    "TimelineType",
]
