from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(slots=True)
class ConformalConfig:
    window_size: int = 400
    confidence: float = 0.99
    minimum_samples: int = 25
    floor_margin_m: float = 0.20
    ceiling_margin_m: float = 2.50


@dataclass(slots=True)
class ConformalReport:
    calibrated: bool
    sample_count: int
    quantile_error_m: float
    required_extra_margin_m: float
    confidence: float
    empirical_coverage: float


class OnlineConformalRiskCalibrator:
    """Distribution-free online residual calibration for safety margins."""

    def __init__(self, config: ConformalConfig | None = None) -> None:
        self.config = config or ConformalConfig()
        self._residuals: deque[float] = deque(maxlen=self.config.window_size)

    def observe(self, predicted_xy: tuple[float, float], measured_xy: tuple[float, float]) -> None:
        error = math.hypot(predicted_xy[0] - measured_xy[0], predicted_xy[1] - measured_xy[1])
        if math.isfinite(error):
            self._residuals.append(max(0.0, error))

    def reset(self) -> None:
        self._residuals.clear()

    def report(self) -> ConformalReport:
        count = len(self._residuals)
        if count < self.config.minimum_samples:
            return ConformalReport(False, count, 0.0, self.config.floor_margin_m, self.config.confidence, 0.0)
        ordered = sorted(self._residuals)
        rank = math.ceil((count + 1) * self.config.confidence) - 1
        rank = max(0, min(rank, count - 1))
        quantile = ordered[rank]
        margin = min(self.config.ceiling_margin_m, max(self.config.floor_margin_m, quantile))
        coverage = sum(1 for value in ordered if value <= margin) / count
        return ConformalReport(True, count, quantile, margin, self.config.confidence, coverage)
