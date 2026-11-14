"""Lightweight execution tracing helper for pipeline steps."""

import time
from collections.abc import Generator
from contextlib import contextmanager

from change_lens.observability.logging_config import logger


@contextmanager
def trace_step(step_name: str) -> Generator[None, None, None]:
    """Context manager for tracing duration of scientific pipeline execution steps."""
    logger.info("Starting pipeline step: %s", step_name)
    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start_time
        logger.info("Completed pipeline step: %s in %.4f seconds", step_name, elapsed)
