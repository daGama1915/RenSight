"""
utils/logger.py
----------------
Logging configuration helpers.
"""

import logging
import sys


def setup_logging(verbose: bool = False) -> None:
    """Configure the root logger for console output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level   = level,
        format  = "%(levelname)-8s %(name)s — %(message)s",
        stream  = sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
