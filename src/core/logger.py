import sys
from pathlib import Path

from loguru import logger

_logging_configured = False


def setup_logging(
    level: str = "INFO",
    retention_days: int = 30,
    per_account_logs: bool = True,
    log_dir: str = "data/logs",
    quiet: bool = False,
) -> None:
    """Configure loguru for the application.

    Safe to call from a background thread — only the first invocation
    removes and re-adds handlers; subsequent calls are no-ops.
    """
    global _logging_configured
    if _logging_configured:
        return
    _logging_configured = True

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console handler (skip when quiet mode is enabled)
    if not quiet:
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


_account_handler_ids: dict[str, int] = {}


def get_account_logger(account_name: str, log_dir: str = "data/logs",
                       retention_days: int = 30):
    """Return a logger bound to a specific account, writing to its own file.

    Only registers a new handler the first time per account name to avoid
    duplicate log entries when called repeatedly (e.g. after auto-recovery).
    """
    if account_name in _account_handler_ids:
        return logger.bind(account=account_name)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    account_logger = logger.bind(account=account_name)
    handler_id = logger.add(
        str(log_path / f"{account_name}_{{time:YYYY-MM-DD}}.log"),
        level="DEBUG",
        rotation="00:00",
        retention=f"{retention_days} days",
        filter=lambda record, _name=account_name: record["extra"].get("account") == _name,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
        encoding="utf-8",
    )
    _account_handler_ids[account_name] = handler_id
    return account_logger
