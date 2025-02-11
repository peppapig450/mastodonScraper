import asyncio
from pathlib import Path
from typing import Optional

import click
import structlog

from .config import MastodonConfig
from .models import TimelineType
from .scraper import MastodonScraper
from .utils import save_json

logger = structlog.get_logger()


@click.group()
@click.option(
    "--config",
    type=click.Path(exists=True, path_type=Path),
    help="Path to TOML config file",
)
@click.option("--instance", help="Mastodon instance URL")
@click.pass_context
def cli(ctx: click.Context, config: Optional[Path], instance: Optional[str]) -> None:
    """Mastodon content scraping tool."""
    if config:
        ctx.obj = MastodonConfig.from_toml(config)
    elif instance:
        ctx.obj = MastodonConfig(instance_url=instance)
    else:
        raise click.UsageError("Either --config or --instance must be provided")


@cli.command()
@click.argument("username")
@click.option("--limit", type=int, help="Maximum number of posts to fetch")
@click.option(
    "--output", type=click.Path(path_type=Path), help="Output directory for saved data"
)
@click.pass_obj
def user(
    config: MastodonConfig, username: str, limit: Optional[int], output: Optional[Path]
) -> None:
    """Fetch posts fron a specific user."""

    async def _fetch_user() -> None:
        scraper = MastodonScraper(config)
        try:
            if user_id := await scraper.get_user_id(username):
                logger.info("user_found", user_id=user_id)
                timeline = await scraper.fetch_timeline(
                    TimelineType.USER, user_id, limit
                )

                if timeline["posts"]:
                    save_json(
                        timeline,
                        filename=f"{username}_posts",
                        directory=output or Path("mastodon_data"),
                    )
                else:
                    logger.info("no_posts_found", username=username)
        except Exception as e:
            logger.error("fetch_error", error=str(e))
            raise click.ClickException(str(e)) from e

    asyncio.run(_fetch_user())


@cli.command()
@click.argument("timeline_type", type=click.Choice([t.value for t in TimelineType]))
@click.option("--limit", type=int, help="Maximum number of posts to fetch")
@click.option(
    "--output", type=click.Path(path_type=Path), help="Output directory for saved data"
)
@click.pass_obj
def timeline(
    config: MastodonConfig,
    timeline_type: str,
    limit: Optional[int],
    output: Optional[Path],
) -> None:
    """Fetch posts from a specified timeline."""

    async def _fetch_timeline() -> None:
        scraper = MastodonScraper(config)
        try:
            # Convert string to TimelineType enum
            timeline_enum = TimelineType(timeline_type)
            timeline_data = await scraper.fetch_timeline(timeline_enum, limit=limit)
            if timeline_data["posts"]:
                save_json(
                    timeline_data,
                    filename=f"{timeline_type}_timeline",
                    directory=output or Path("mastodon_data"),
                )
            else:
                logger.info("no_posts_found", timeline=timeline_type)

        except Exception as e:
            logger.error("fetch_error", error=str(e))
            raise click.ClickException(str(e)) from e

    asyncio.run(_fetch_timeline())


if __name__ == "__main__":
    cli()
