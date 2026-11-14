"""Basic runtime performance metrics and event counters."""

from dataclasses import dataclass, field


@dataclass
class MetricsCollector:
    """Lightweight in-memory metrics tracker for local development."""

    counters: dict[str, int] = field(default_factory=dict)
    timers: dict[str, float] = field(default_factory=dict)

    def increment(self, metric_name: str, value: int = 1) -> None:
        """Increment a named counter."""
        self.counters[metric_name] = self.counters.get(metric_name, 0) + value

    def record_time(self, metric_name: str, duration_seconds: float) -> None:
        """Record elapsed time in seconds."""
        self.timers[metric_name] = duration_seconds


metrics = MetricsCollector()
