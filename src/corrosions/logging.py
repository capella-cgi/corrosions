import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger


# Retention periods for log files.
_GENERAL_LOG_RETENTION = "30 days"
_ERROR_LOG_RETENTION = "90 days"

_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
)

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)

load_dotenv(override=True)

logger.remove()


def _configure_handlers(log_dir: Path, console_level: str = "INFO") -> None:
    """Remove all existing handlers and re-add console + file handlers.

    Centralises handler configuration so that module-level setup,
    ``set_log_level()``, and ``set_log_directory()`` all share the same
    retention periods and formats.

    Args:
        log_dir (Path): Directory that will receive the log files.
        console_level (str): Minimum level for the console sink. Defaults to
            ``"INFO"``.

    Returns:
        None
    """
    logger.remove()

    logger.add(
        sys.stderr,
        format=_CONSOLE_FORMAT,
        level=console_level.upper(),
        colorize=True,
    )

    logger.add(
        log_dir / "corrosions_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention=_GENERAL_LOG_RETENTION,
        compression="zip",
        format=_FILE_FORMAT,
        level="DEBUG",
        enqueue=True,
    )

    logger.add(
        log_dir / "errors_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention=_ERROR_LOG_RETENTION,
        compression="zip",
        format=_FILE_FORMAT,
        level="ERROR",
        enqueue=True,
    )


_log_dir: Path = Path.cwd() / "logs"

# Only configure handlers when ENABLE_LOG=true (env var inherited by workers).
if os.environ.get("ENABLE_LOG", "false").lower() == "true":
    _log_dir.mkdir(parents=True, exist_ok=True)
    _configure_handlers(_log_dir)


def set_log_level(level: str) -> None:
    """Change the console log level dynamically.

    Removes all existing handlers and re-adds them with the new console level.
    File handlers retain their original levels (``DEBUG`` and ``ERROR``).

    Args:
        level (str): Minimum level for the console sink — one of ``"DEBUG"``,
            ``"INFO"``, ``"WARNING"``, ``"ERROR"``, or ``"CRITICAL"``.
            Case-insensitive.

    Raises:
        ValueError: If ``level`` is not a recognised loguru level name.

    Returns:
        None
    """
    _configure_handlers(_log_dir, console_level=level)


def set_log_directory(log_dir: Path | str) -> None:
    """Change the log file directory dynamically.

    Args:
        log_dir (Path | str): Absolute or relative path to the new log
            directory. Created automatically if it does not exist.

    Raises:
        PermissionError: If the process lacks permission to create the
            directory.

    Returns:
        None
    """
    global _log_dir
    _log_dir = Path(log_dir).resolve()
    _log_dir.mkdir(parents=True, exist_ok=True)
    _configure_handlers(_log_dir)
    logger.info(f"Log directory changed to: {_log_dir}")


def disable_logging() -> None:
    """Disable all logging output globally.

    Removes all active loguru handlers so no messages are written to the
    console or log files. Call ``enable_logging()`` to restore handlers.

    Returns:
        None
    """
    os.environ["ENABLE_LOG"] = "false"
    logger.remove()


def enable_logging() -> None:
    """Re-enable logging after a previous ``disable_logging()`` call.

    Restores console and file handlers using the current log directory.
    Safe to call even if logging is already active — handlers are replaced
    cleanly by ``_configure_handlers``.

    Returns:
        None
    """
    os.environ["ENABLE_LOG"] = "true"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _configure_handlers(_log_dir)
