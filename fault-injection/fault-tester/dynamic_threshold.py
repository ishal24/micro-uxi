from __future__ import annotations

import math
from typing import Any


class EwmaThreshold:
    def __init__(
        self,
        static_threshold: float,
        warmup_samples: int,
        alpha: float,
        beta: float,
        k: float,
        enabled: bool = True,
    ) -> None:
        self.static_threshold = float(static_threshold)
        self.warmup_samples = max(1, int(warmup_samples))
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.k = float(k)
        self.enabled = bool(enabled)
        self.sample_count = 0
        self.mu: float | None = None
        self.v = 0.0

    def threshold(self) -> dict[str, Any]:
        if not self.enabled:
            return self._state(self.static_threshold, "disabled")
        if self.mu is None or self.sample_count < self.warmup_samples:
            return self._state(float('inf'), "warmup")
        return self._state(self.mu + self.k * math.sqrt(max(self.v, 0.0)), "dynamic")

    def evaluate(self, value: float, update: bool = True) -> dict[str, Any]:
        numeric_value = float(value)
        info = self.threshold()
        exceeded = numeric_value >= info["value"]

        if update and (not self.enabled or not exceeded):
            self._update(numeric_value)

        return {
            **info,
            "exceeded": exceeded,
            "observed": numeric_value,
        }

    def describe(self, label: str = "dyn_thr") -> str:
        info = self.threshold()
        if label == "dyn_thr":
            base_label = "base"
            mode_label = "mode"
            sample_label = "n"
            mu_label = "mu"
            std_label = "std"
        else:
            prefix = label.removesuffix("_dyn_thr")
            base_label = f"{prefix}_base"
            mode_label = f"{prefix}_mode"
            sample_label = f"{prefix}_n"
            mu_label = f"{prefix}_mu"
            std_label = f"{prefix}_std"

        mu_value = "NA" if info["mu"] is None else f"{info['mu']:.1f}ms"
        return (
            f"{label}={info['value']:.1f}ms "
            f"{base_label}={self.static_threshold:.1f}ms "
            f"{mode_label}={info['mode']} "
            f"{sample_label}={info['sample_count']}/{self.warmup_samples} "
            f"{mu_label}={mu_value} "
            f"{std_label}={info['std']:.1f}ms"
        )

    def _update(self, value: float) -> None:
        if self.mu is None:
            self.mu = value
            self.v = 0.0
            self.sample_count = 1
            return

        prev_mu = self.mu
        self.mu = self.alpha * value + (1 - self.alpha) * prev_mu
        self.v = self.beta * ((value - prev_mu) ** 2) + (1 - self.beta) * self.v
        self.sample_count += 1

    def _state(self, threshold_value: float, mode: str) -> dict[str, Any]:
        return {
            "value": float(threshold_value),
            "mode": mode,
            "mu": self.mu,
            "variance": self.v,
            "std": math.sqrt(max(self.v, 0.0)),
            "sample_count": self.sample_count,
            "alpha": self.alpha,
            "beta": self.beta,
            "k": self.k,
        }


def make_dynamic_threshold(
    cfg: dict[str, Any],
    event_key: str,
    metric_key: str,
    static_threshold: float,
) -> EwmaThreshold:
    dynamic_cfg = cfg.get("dynamic_thresholds", {})
    metric_cfg = (dynamic_cfg.get("events", {}).get(event_key, {}) or {}).get(metric_key, {})
    enabled = bool(dynamic_cfg.get("enabled", False) and metric_cfg)
    return EwmaThreshold(
        static_threshold=static_threshold,
        warmup_samples=metric_cfg.get("warmup_samples", metric_cfg.get("min_samples", 1)),
        alpha=metric_cfg.get("alpha", 0.1),
        beta=metric_cfg.get("beta", 0.1),
        k=metric_cfg.get("k", 3),
        enabled=enabled,
    )
