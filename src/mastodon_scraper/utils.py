import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


def save_json(
    data: Any, filename: str | Path, directory: Path = Path("mastodon_data")
) -> Path:
    """Save data to a JSON file with proper error handling."""
    directory.mkdir(exist_ok=True, parents=True)

    if isinstance(filename, str):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = directory / f"{filename}_{timestamp}.json"

    try:
        filename.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("file_saved", path=str(filename))
        return filename
    except Exception as e:
        logger.error("save_error", error=str(e), path=str(filename))
        raise
