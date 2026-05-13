from __future__ import annotations

import argparse
import copy
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from monitoring.config import load_config
from monitoring.detector import EventDetector
from monitoring.evidence import EvidenceManager
from monitoring.probes import FastProbe, TelemetryProbe, ThroughputProbe
from monitoring.stream import SampleStreamer
from monitoring.utils import append_jsonl, safe_mkdir


def parse_duration(value: str) -> float | None:
    raw = value.strip().lower()
    if raw in {"0", "inf", "indefinite", "forever"}:
        return None
    if raw.endswith("h"):
        return float(raw[:-1]) * 3600
    if raw.endswith("m"):
        return float(raw[:-1]) * 60
    if raw.endswith("s"):
        return float(raw[:-1])
    return float(raw)


@dataclass
class WorkerSpec:
    name: str
    interval_sec: float
    probe: object


@dataclass
class RunOptions:
    mode: str
    fast_interval_sec: float
    telemetry_interval_sec: float
    throughput_interval_sec: float
    output_dir: str | None
    duration_raw: str
    detection_mode: str
    stream_enabled: bool
    stream_host: str | None
    stream_port: int | None
    stream_api_key: str | None


class MonitorController:
    def __init__(self, config: dict):
        self.config = config
        self.output_enabled = bool(config.get("output", {}).get("enabled", False))
        self.output_dir = safe_mkdir(config["output"]["output_dir"]) if self.output_enabled else None
        self.run_id = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        self.detector = EventDetector(config, self.run_id)
        self.evidence = EvidenceManager(config, self.run_id)
        self.streamer = SampleStreamer(config, self._print)
        self.sample_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.print_lock = threading.Lock()
        self.sample_counts = {"fast": 0, "telemetry": 0, "throughput": 0}
        self.event_count = 0
        self.raw_dir = safe_mkdir(self.output_dir / "samples") if self.output_enabled else None
        self.event_log_path = (self.output_dir / f"events_{self.run_id}.jsonl") if self.output_enabled else None
        self.sample_paths = (
            {
                "fast": self.raw_dir / f"fast_{self.run_id}.jsonl",
                "telemetry": self.raw_dir / f"telemetry_{self.run_id}.jsonl",
                "throughput": self.raw_dir / f"throughput_{self.run_id}.jsonl",
            }
            if self.output_enabled
            else {}
        )

    def build_workers(self) -> list[WorkerSpec]:
        workers: list[WorkerSpec] = []
        sched = self.config["scheduler"]
        if self.config.get("fast_probe", {}).get("enabled", True):
            workers.append(
                WorkerSpec(
                    name="fast",
                    interval_sec=float(sched.get("fast_interval_sec", 2)),
                    probe=FastProbe(self.config),
                )
            )
        if self.config.get("telemetry_probe", {}).get("enabled", True):
            workers.append(
                WorkerSpec(
                    name="telemetry",
                    interval_sec=float(sched.get("telemetry_interval_sec", 30)),
                    probe=TelemetryProbe(self.config),
                )
            )
        if self.config.get("throughput_probe", {}).get("enabled", False):
            workers.append(
                WorkerSpec(
                    name="throughput",
                    interval_sec=float(sched.get("throughput_interval_sec", 300)),
                    probe=ThroughputProbe(self.config),
                )
            )
        return workers

    def _worker_loop(self, spec: WorkerSpec) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                sample = spec.probe.collect()
                self.sample_queue.put(sample)
            except Exception as exc:  # pragma: no cover - target-runtime dependent
                self._print(f"[{spec.name.upper()} ERROR] {exc}")

            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, spec.interval_sec - elapsed))

    def process_sample(self, sample: dict, print_sample_line: bool = True) -> None:
        probe_type = sample["probe_type"]
        self.sample_counts[probe_type] += 1
        if self.output_enabled:
            append_jsonl(self.sample_paths[probe_type], sample)
        self.streamer.enqueue(sample)

        notices = self.detector.handle_sample(sample)
        self.evidence.capture(sample, notices)

        if notices:
            for notice in notices:
                event = notice["event"]
                if notice["kind"] == "started":
                    self.event_count += 1
                if self.output_enabled:
                    append_jsonl(self.event_log_path, {"kind": notice["kind"], "event": event})
            self._print_notices(notices)
        elif print_sample_line:
            self._print_sample_line(sample)

    def run(self, duration_sec: float | None = None) -> None:
        workers = self.build_workers()
        threads = [
            threading.Thread(target=self._worker_loop, args=(worker,), daemon=True, name=worker.name)
            for worker in workers
        ]

        self._print_banner(workers, duration_sec)
        self.streamer.start()
        for thread in threads:
            thread.start()

        started = time.monotonic()
        deadline = started + duration_sec if duration_sec else None

        try:
            while not self.stop_event.is_set():
                if deadline and time.monotonic() >= deadline:
                    self._print("[i] Target duration reached.")
                    break
                try:
                    sample = self.sample_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.process_sample(sample)
        except KeyboardInterrupt:
            self._print("[!] Stopped by user.")
        finally:
            self.stop_event.set()
            for thread in threads:
                thread.join(timeout=10)
            self.streamer.stop()

            remaining = self.detector.force_close_all()
            if remaining:
                for notice in remaining:
                    if self.output_enabled:
                        append_jsonl(self.event_log_path, {"kind": notice["kind"], "event": notice["event"]})
                self.evidence.force_flush(remaining)
            else:
                self.evidence.force_flush([])
            self._print_summary(time.monotonic() - started)

    def run_once(self, mode: str) -> dict:
        self.streamer.start()
        probe_map = {
            "once-fast": FastProbe,
            "once-telemetry": TelemetryProbe,
            "once-throughput": ThroughputProbe,
        }
        try:
            if mode == "once-all":
                samples = []
                samples.append(FastProbe(self.config).collect())
                samples.append(TelemetryProbe(self.config).collect())
                if self.config.get("throughput_probe", {}).get("enabled", False):
                    samples.append(ThroughputProbe(self.config).collect())
                else:
                    self._print("[INFO] Throughput probe disabled in config, skipped in once-all.")
                for sample in samples:
                    print(json.dumps(sample, indent=2))
                    self.process_sample(sample, print_sample_line=False)
                remaining = self.detector.force_close_all()
                if remaining:
                    for notice in remaining:
                        if self.output_enabled:
                            append_jsonl(self.event_log_path, {"kind": notice["kind"], "event": notice["event"]})
                    self.evidence.force_flush(remaining)
                else:
                    self.evidence.force_flush([])
                return {"samples": samples}

            probe_cls = probe_map[mode]
            sample = probe_cls(self.config).collect()
            print(json.dumps(sample, indent=2))
            self.process_sample(sample, print_sample_line=False)
            remaining = self.detector.force_close_all()
            if remaining:
                for notice in remaining:
                    if self.output_enabled:
                        append_jsonl(self.event_log_path, {"kind": notice["kind"], "event": notice["event"]})
                self.evidence.force_flush(remaining)
            else:
                self.evidence.force_flush([])
            return sample
        finally:
            self.streamer.stop()

    def _print_banner(self, workers: list[WorkerSpec], duration_sec: float | None) -> None:
        duration_label = (
            f"{duration_sec:.0f}s ({duration_sec / 60:.1f} min)"
            if duration_sec
            else "indefinite (Ctrl+C to stop)"
        )
        with self.print_lock:
            print("=" * 72)
            print("  Micro-UXI Monitoring Rewrite")
            print("=" * 72)
            print(f"  Run ID      : {self.run_id}")
            print(f"  Device      : {self.config['device']['device_id']} @ {self.config['device'].get('site_name', '?')}")
            print(f"  Interface   : {self.config['device']['iface']}")
            print(f"  Duration    : {duration_label}")
            print(f"  Detection   : {self.config['detector'].get('detection_mode', 'static')}")
            print(f"  Output dir  : {self.output_dir.resolve() if self.output_enabled else 'disabled'}")
            stream_stats = self.streamer.stats()
            print(f"  Stream      : {stream_stats['url'] if stream_stats['enabled'] else 'disabled'}")
            for worker in workers:
                print(f"  {worker.name:<11}: every {worker.interval_sec:g}s")
            print("=" * 72)

    def _print(self, message: str) -> None:
        with self.print_lock:
            print(message, flush=True)

    def _print_notices(self, notices: list[dict]) -> None:
        with self.print_lock:
            for notice in notices:
                event = notice["event"]
                scope = event.get("affected_scope", "unknown")
                if notice["kind"] == "started":
                    print(
                        f"[EVENT START] {event['event_type']} "
                        f"scope={scope} severity={event.get('severity')} "
                        f"reason={event.get('trigger_reason')}",
                        flush=True,
                    )
                else:
                    print(
                        f"[EVENT END]   {event['event_type']} "
                        f"scope={scope} reason={event.get('recovery_reason')}",
                        flush=True,
                    )

    def _print_sample_line(self, sample: dict) -> None:
        probe_type = sample["probe_type"]
        ts = sample["ts"][11:19]

        if probe_type == "fast":
            if not self.config["output"].get("print_fast_normal", False):
                ping_ok = bool(sample.get("ping", {}).get("success"))
                dns_ok = all(row.get("success") for row in sample.get("dns", [])) if sample.get("dns") else True
                if ping_ok and dns_ok and bool(sample.get("connectivity_ok")):
                    return
            wifi_up = "UP" if sample.get("wifi", {}).get("wifi_up") else "DOWN"
            ping = sample.get("ping", {})
            ping_str = f"{ping.get('rtt_ms'):.1f}ms" if ping.get("rtt_ms") is not None else "FAIL"
            dns_str = ", ".join(
                f"{row['target']}={'OK' if row.get('success') else row.get('status')}"
                for row in sample.get("dns", [])
            )
            self._print(f"[FAST] {ts} wifi={wifi_up} ping={ping_str} dns={dns_str}")
            return

        if probe_type == "telemetry":
            wifi = sample.get("wifi", {})
            ping = sample.get("ping", {})
            rtt = ping.get("rtt_avg_ms")
            loss = ping.get("loss_pct")
            self._print(
                f"[TELEMETRY] {ts} wifi={'UP' if wifi.get('wifi_connected') else 'DOWN'} "
                f"rssi={wifi.get('wifi_rssi_dbm')} rtt={rtt}ms loss={loss}%"
            )
            return

        if probe_type == "throughput":
            summary = sample.get("summary", {})
            dl = ((summary.get("download") or {}).get("throughput_total_mbps") or {}).get("avg")
            ul = ((summary.get("upload") or {}).get("upload_throughput_total_mbps") or {}).get("avg")
            self._print(f"[THROUGHPUT] {ts} dl_avg={dl}Mbps ul_avg={ul}Mbps")

    def _print_summary(self, elapsed_sec: float) -> None:
        with self.print_lock:
            print("=" * 72)
            print("  Session complete")
            print("=" * 72)
            print(f"  Elapsed      : {elapsed_sec:.1f}s ({elapsed_sec / 60:.1f} min)")
            print(f"  Events fired : {self.event_count}")
            for probe_type, count in self.sample_counts.items():
                print(f"  {probe_type:<12}: {count}")
            if self.output_enabled:
                print(f"  Samples      : {self.raw_dir.resolve()}")
                print(f"  Event log    : {self.event_log_path.resolve()}")
            else:
                print("  Output       : disabled")
            if self.streamer.enabled:
                stats = self.streamer.stats()
                print(
                    "  Stream       : "
                    f"sent={stats['sent']} failed={stats['failed']} dropped={stats['dropped']}"
                )
            print("=" * 72)


def parse_interval(value: str) -> float:
    return parse_duration(value) or 0.0


def _duration_label(value: str) -> str:
    parsed = parse_duration(value)
    if parsed is None:
        return "indefinite"
    return f"{parsed:.0f}s"


def _output_label(output_dir: str | None) -> str:
    return output_dir if output_dir else "none"


def _stream_label(options: RunOptions) -> str:
    if not options.stream_enabled:
        return "disabled"
    host = options.stream_host or "<ip belum diisi>"
    port = options.stream_port if options.stream_port is not None else "<port belum diisi>"
    return f"http://{host}:{port}/api/ingest/sensor"


def _parse_yes_no(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = value.strip().lower()
    if raw in {"y", "yes", "true", "1", "on", "enable", "enabled"}:
        return True
    if raw in {"n", "no", "false", "0", "off", "disable", "disabled"}:
        return False
    raise ValueError("Nilai stream harus yes/no.")


def _parse_stream_port(value: str | int | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port stream harus angka.") from exc
    if port < 1 or port > 65535:
        raise ValueError("Port stream harus di range 1-65535.")
    return port


def build_run_options(config: dict, args) -> RunOptions:
    scheduler = config["scheduler"]
    detector_cfg = config["detector"]
    output_cfg = config["output"]
    stream_cfg = config.get("stream", {})

    fast_interval = parse_interval(args.fast_interval) if args.fast_interval else float(scheduler.get("fast_interval_sec", 5))
    telemetry_interval = parse_interval(args.telemetry_interval) if args.telemetry_interval else float(scheduler.get("telemetry_interval_sec", 30))
    throughput_interval = parse_interval(args.throughput_interval) if args.throughput_interval else float(scheduler.get("throughput_interval_sec", 900))

    output_dir: str | None
    if args.output is None:
        output_dir = None if not output_cfg.get("enabled", False) else output_cfg.get("output_dir")
    else:
        output_dir = None if args.output.strip().lower() in {"none", "off", "disable", "disabled"} else args.output.strip()

    stream_enabled = _parse_yes_no(args.stream, bool(stream_cfg.get("enabled", False)))
    stream_host = args.stream_host or stream_cfg.get("host") or stream_cfg.get("ip") or None
    stream_port = _parse_stream_port(args.stream_port if args.stream_port is not None else stream_cfg.get("port"))
    stream_api_key = args.stream_api_key if args.stream_api_key is not None else stream_cfg.get("api_key")

    return RunOptions(
        mode=args.mode,
        fast_interval_sec=fast_interval,
        telemetry_interval_sec=telemetry_interval,
        throughput_interval_sec=throughput_interval,
        output_dir=output_dir,
        duration_raw=args.duration,
        detection_mode=args.detection_mode or str(detector_cfg.get("detection_mode", "static")),
        stream_enabled=stream_enabled,
        stream_host=stream_host,
        stream_port=stream_port,
        stream_api_key=stream_api_key,
    )


def print_run_plan(config: dict, options: RunOptions) -> None:
    print("=" * 72)
    print("  Planned Run")
    print("=" * 72)
    print(f"  Device      : {config['device']['device_id']} @ {config['device'].get('site_name', '?')}")
    print(f"  Interface   : {config['device']['iface']}")
    print(f"  Mode        : {options.mode}")
    print(f"  Fast freq   : {options.fast_interval_sec:g}s")
    print(f"  Telemetry   : {options.telemetry_interval_sec:g}s")
    print(f"  Throughput  : {options.throughput_interval_sec:g}s")
    print(f"  Duration    : {_duration_label(options.duration_raw)}")
    print(f"  Detection   : {options.detection_mode}")
    print(f"  Output      : {_output_label(options.output_dir)}")
    print(f"  Stream      : {_stream_label(options)}")
    print("=" * 72)


def prompt_edit_options(options: RunOptions) -> RunOptions:
    while True:
        field = input(
            "Ubah apa? [mode/fast/telemetry/throughput/output/duration/detection/stream/done]: "
        ).strip().lower()
        if field in {"done", ""}:
            return options
        if field == "mode":
            value = input("Mode baru [once-fast/once-telemetry/once-throughput/once-all/all]: ").strip()
            if value in {"once-fast", "once-telemetry", "once-throughput", "once-all", "all"}:
                options.mode = value
            else:
                print("Mode tidak valid.")
        elif field == "fast":
            options.fast_interval_sec = parse_interval(input("Fast interval baru (contoh 5s): ").strip())
        elif field == "telemetry":
            options.telemetry_interval_sec = parse_interval(input("Telemetry interval baru (contoh 30s): ").strip())
        elif field == "throughput":
            options.throughput_interval_sec = parse_interval(input("Throughput interval baru (contoh 15m): ").strip())
        elif field == "output":
            value = input("Output dir baru, atau 'none' untuk nonaktif: ").strip()
            options.output_dir = None if value.lower() in {"none", "off", "disable", "disabled"} else value
        elif field == "duration":
            options.duration_raw = input("Duration baru (contoh 10m, 0 untuk indefinite): ").strip()
        elif field == "detection":
            value = input("Detection mode baru [static/dynamic]: ").strip().lower()
            if value in {"static", "dynamic"}:
                options.detection_mode = value
            else:
                print("Detection mode tidak valid.")
        elif field == "stream":
            value = input("Stream ke server? [y/n]: ").strip().lower()
            try:
                options.stream_enabled = _parse_yes_no(value)
            except ValueError as exc:
                print(exc)
                continue
            if options.stream_enabled:
                options.stream_host = input("IP/host server: ").strip()
                try:
                    options.stream_port = _parse_stream_port(input("Port server: ").strip())
                except ValueError as exc:
                    print(exc)
                    options.stream_port = None
                api_key = input("API key server (kosongkan jika tidak ada): ").strip()
                options.stream_api_key = api_key
            else:
                options.stream_host = None
                options.stream_port = None
        else:
            print("Pilihan tidak dikenal.")


def ensure_stream_ready(options: RunOptions) -> RunOptions:
    while options.stream_enabled and not options.stream_host:
        options.stream_host = input("Stream aktif. Isi IP/host server: ").strip()
    while options.stream_enabled and options.stream_port is None:
        try:
            options.stream_port = _parse_stream_port(input("Stream aktif. Isi port server: ").strip())
        except ValueError as exc:
            print(exc)
    return options


def confirm_run_options(config: dict, options: RunOptions) -> RunOptions:
    while True:
        print_run_plan(config, options)
        answer = input("Lanjut run? [y/n]: ").strip().lower()
        if answer == "y":
            return ensure_stream_ready(options)
        if answer == "n":
            options = prompt_edit_options(options)
            continue
        print("Masukkan 'y' atau 'n'.")


def apply_run_options(config: dict, options: RunOptions) -> dict:
    runtime = copy.deepcopy(config)
    runtime["scheduler"]["fast_interval_sec"] = options.fast_interval_sec
    runtime["scheduler"]["telemetry_interval_sec"] = options.telemetry_interval_sec
    runtime["scheduler"]["throughput_interval_sec"] = options.throughput_interval_sec
    runtime["detector"]["detection_mode"] = options.detection_mode
    runtime["output"]["enabled"] = options.output_dir is not None
    if options.output_dir is not None:
        runtime["output"]["output_dir"] = options.output_dir
    runtime.setdefault("stream", {})
    runtime["stream"]["enabled"] = options.stream_enabled
    runtime["stream"]["host"] = options.stream_host or ""
    runtime["stream"]["port"] = options.stream_port
    runtime["stream"]["api_key"] = options.stream_api_key or ""
    return runtime


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean monitoring stack for Micro-UXI")
    parser.add_argument("--config", default=None, help="Optional override config JSON")
    parser.add_argument(
        "--mode",
        default="once-all",
        choices=["once-fast", "once-telemetry", "once-throughput", "once-all", "all"],
    )
    parser.add_argument("--duration", default="0", help="Run duration: 15m / 1h / 0")
    parser.add_argument("--fast-interval", default=None, help="Fast probe interval, example: 5s")
    parser.add_argument("--telemetry-interval", default=None, help="Telemetry interval, example: 30s")
    parser.add_argument("--throughput-interval", default=None, help="Throughput interval, example: 15m")
    parser.add_argument("--output", default=None, help="Output dir, or 'none' to disable file output")
    parser.add_argument("--stream", default=None, help="Stream samples to server: yes/no")
    parser.add_argument("--stream-host", "--stream-ip", dest="stream_host", default=None, help="Server IP/host for stream")
    parser.add_argument("--stream-port", type=int, default=None, help="Server port for stream")
    parser.add_argument("--stream-api-key", default=None, help="Optional API key for stream ingest")
    parser.add_argument(
        "--detection-mode",
        default=None,
        choices=["static", "dynamic"],
        help="Detection mode for thresholded events",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    options = build_run_options(config, args)
    options = confirm_run_options(config, options)
    runtime_config = apply_run_options(config, options)
    controller = MonitorController(runtime_config)

    if options.mode == "all":
        controller.run(parse_duration(options.duration_raw))
    else:
        controller.run_once(options.mode)


if __name__ == "__main__":
    main()
