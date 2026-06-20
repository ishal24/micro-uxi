from __future__ import annotations

from probe.probe_common import (
    collect_network_details,
    collect_wifi_details,
    measure_http,
    ping_batch,
    resolve_dns_matrix,
    sample_header,
)


class TelemetryProbe:
    def __init__(self, config: dict):
        self.config = config
        self.device_cfg = config["device"]
        self.targets_cfg = config["targets"]
        self._seq = 0

    def collect(self) -> dict:
        self._seq += 1

        sample = sample_header(self.device_cfg, "telemetry", self._seq)
        sample["wifi"] = collect_wifi_details(self.device_cfg["iface"])
        sample["network"] = collect_network_details(self.device_cfg["iface"])
        sample["ping"] = ping_batch(
            self.targets_cfg["ping_target"],
            int(self.targets_cfg.get("telemetry_ping_count", 5)),
            float(self.targets_cfg.get("telemetry_ping_interval_sec", 0.2)),
            int(self.targets_cfg.get("telemetry_ping_timeout_sec", 10)),
        )
        sample["dns"] = resolve_dns_matrix(
            self.targets_cfg.get("dns_targets", []),
            float(self.targets_cfg.get("telemetry_dns_timeout_sec", 5)),
            self.targets_cfg.get("dns_resolvers", ["system"]),
        )
        sample["http"] = [
            measure_http(
                target["url"],
                target.get("scope", "unknown"),
                int(self.targets_cfg.get("http_connect_timeout_sec", 5)),
                int(self.targets_cfg.get("http_max_time_sec", 15)),
                int(target.get("expected_status_min", 200)),
                int(target.get("expected_status_max", 399)),
            )
            for target in self.targets_cfg.get("http_targets", [])
        ]
        return sample
