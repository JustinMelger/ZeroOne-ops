"""Logging helpers.

This module centralizes logging configuration for the CLI entrypoint and
runtime services.
"""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure process-wide logging.

    Args:
        level: Logging level name such as ``"INFO"`` or ``"DEBUG"``.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
