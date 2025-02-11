from datetime import datetime
from enum import StrEnum
from typing import Any, NotRequired, TypedDict


class TimelineType(StrEnum):
    """Enumeration of valid timeline types."""

    HOME = "home"
    PUBLIC = "public"
    LOCAL = "local"
    USER = "user"


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


class Timeline(TypedDict):
    """Type definition for timeline data."""

    posts: list[MastodonPost]
    last_updated: datetime
    timeline_type: TimelineType
