"""Logging configuration for SPHEREx Change Lens.

NOTE: This module is named logging_config.py to prevent shadowing
the Python standard library 'logging' package.
"""

import logging
import sys
from typing import Optional


def configure_logging(log_level: Optional[str] = None) -> None:
    """Configure structured console logging for application and pipelines."""
    level = (log_level or "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


logger = logging.getLogger("change_lens")
