from __future__ import annotations

from probe.probe_common import ping_once, read_operstate, resolve_dns, sample_header


class FastProbe:
    def __init__(self, config: dict):
        self.config = config
        self.device_cfg = config["device"]
        self.targets_cfg = config["monitoring"]["targets"]
        self._seq = 0

    def collect(self) -> dict:
        self._seq += 1

        iface = self.device_cfg["iface"]
        wifi_up = read_operstate(iface)
        ping = ping_once(
            self.targets_cfg["ping_target"],
            int(self.targets_cfg.get("ping_timeout_sec", 1)),
        )

        dns = [
            resolve_dns(
                target["name"],
                target.get("scope", "unknown"),
                float(self.targets_cfg.get("dns_timeout_sec", 2.0)),
                resolver=self.targets_cfg.get("dns_resolver"),
            )
            for target in self.targets_cfg.get("dns_targets", [])
        ]

        sample = sample_header(self.device_cfg, "fast", self._seq)
        sample.update(
            {
                "wifi": {
                    "wifi_up": wifi_up,
                    "wifi_connected": wifi_up,
                },
                "ping": ping,
                "dns": dns,
                "connectivity_ok": bool(wifi_up) and ping["success"] and all(item["success"] for item in dns),
            }
        )
        return sample
