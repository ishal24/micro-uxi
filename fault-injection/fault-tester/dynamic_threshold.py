from __future__ import annotations

from collections import deque
from statistics import median
from typing import Any


MAD_SCALE = 1.4826


class RollingMadThreshold:
    def __init__(
        self,
        static_threshold: float,
        window_samples: int,
        min_samples: int,
        k: float,
        enabled: bool = True,
    ) -> None:
        self.static_threshold = float(static_threshold)
        self.window_samples = max(1, int(window_samples))
        self.min_samples = max(1, int(min_samples))
        self.k = float(k)
        self.enabled = bool(enabled)
        self.samples: deque[float] = deque(maxlen=self.window_samples)

    def threshold(self) -> dict[str, Any]:
        if not self.enabled or len(self.samples) < self.min_samples:
            return {
                "value": self.static_threshold,
                "mode": "static",
                "median": None,
                "mad": None,
                "sample_count": len(self.samples),
            }

        sample_values = list(self.samples)
        med = float(median(sample_values))
        scaled_mad = float(MAD_SCALE * median(abs(value - med) for value in sample_values))
        dyn_threshold = max(self.static_threshold, med + self.k * scaled_mad)
        return {
            "value": dyn_threshold,
            "mode": "dynamic",
            "median": med,
            "mad": scaled_mad,
            "sample_count": len(self.samples),
        }

    def evaluate(self, value: float, update: bool = True) -> dict[str, Any]:
        info = self.threshold()
        numeric_value = float(value)
        if update:
            self.samples.append(numeric_value)
        return {
            **info,
            "exceeded": numeric_value >= info["value"],
            "observed": numeric_value,
        }

    def describe(self, label: str = "dyn_thr") -> str:
        info = self.threshold()
        if label == "dyn_thr":
            base_label = "base"
            mode_label = "mode"
            sample_label = "n"
        else:
            prefix = label.removesuffix("_dyn_thr")
            base_label = f"{prefix}_base"
            mode_label = f"{prefix}_mode"
            sample_label = f"{prefix}_n"
        return (
            f"{label}={info['value']:.1f}ms "
            f"{base_label}={self.static_threshold:.1f}ms "
            f"{mode_label}={info['mode']} "
            f"{sample_label}={info['sample_count']}/{self.min_samples}"
        )


def make_dynamic_threshold(
    cfg: dict[str, Any],
    event_key: str,
    metric_key: str,
    static_threshold: float,
) -> RollingMadThreshold:
    dynamic_cfg = cfg.get("dynamic_thresholds", {})
    metric_cfg = (dynamic_cfg.get("events", {}).get(event_key, {}) or {}).get(metric_key, {})
    enabled = bool(dynamic_cfg.get("enabled", False) and metric_cfg)
    return RollingMadThreshold(
        static_threshold=static_threshold,
        window_samples=metric_cfg.get("window_samples", 1),
        min_samples=metric_cfg.get("min_samples", 1),
        k=metric_cfg.get("k", 0),
        enabled=enabled,
    )
