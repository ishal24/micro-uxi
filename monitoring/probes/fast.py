from __future__ import annotations

from monitoring.probes.common import ping_once, read_operstate, resolve_dns, sample_header


class FastProbe:
    def __init__(self, config: dict):
        self.config = config
        self.device_cfg = config["device"]
        self.probe_cfg = config["fast_probe"]
        self._seq = 0

    def collect(self) -> dict:
        self._seq += 1

        iface = self.device_cfg["iface"]
        wifi_up = read_operstate(iface)
        ping = ping_once(
            self.probe_cfg["ping_target"],
            int(self.probe_cfg.get("ping_timeout_sec", 1)),
        )

        resolver = self.probe_cfg.get("dns_resolver")
        dns = [
            resolve_dns(
                target["name"],
                target.get("scope", "unknown"),
                float(self.probe_cfg.get("dns_timeout_sec", 2.0)),
                resolver=resolver,
            )
            for target in self.probe_cfg.get("targets", [])
        ]
        dns_all_ok = bool(dns) and all(entry["success"] for entry in dns)

        sample = sample_header(self.device_cfg, "fast", self._seq)
        sample.update(
            {
                "wifi": {
                    "wifi_up": wifi_up,
                    "wifi_connected": wifi_up,
                },
                "ping": ping,
                "dns": dns,
                "connectivity_ok": bool(wifi_up) and ping["success"] and dns_all_ok,
            }
        )
        return sample

