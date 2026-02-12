import sys
from pathlib import Path

from loguru import logger


def setup_logging(
    level: str = "INFO",
    retention_days: int = 30,
    per_account_logs: bool = True,
    log_dir: str = "data/logs",
) -> None:
    """Configure loguru for the application."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console handler
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # Main log file (rotated daily)
    logger.add(
        str(log_path / "automation_{time:YYYY-MM-DD}.log"),
        level=level,
        rotation="00:00",
        retention=f"{retention_days} days",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        encoding="utf-8",
    )


def get_account_logger(account_name: str, log_dir: str = "data/logs"):
    """Return a logger bound to a specific account, writing to its own file."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    account_logger = logger.bind(account=account_name)
    logger.add(
        str(log_path / f"{account_name}_{{time:YYYY-MM-DD}}.log"),
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        filter=lambda record: record["extra"].get("account") == account_name,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        encoding="utf-8",
    )
    return account_logger
