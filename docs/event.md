# Micro-UXI Fault Injection Scheme README

This document defines the fault injection schemes used to evaluate the Micro-UXI network experience black-box recorder. Each scheme describes a controlled network impairment, its expected user impact, observable metrics, trigger logic, recovery logic, evidence requirements, and ground-truth fields.

The purpose of these schemes is to make evaluation repeatable: each injected fault must have a clear expected symptom, measurable telemetry evidence, and timestamped ground truth so that precision, recall, F1-score, false alarm rate, mean time to detect, and evidence completeness can be evaluated consistently.

---

## 1. General Evaluation Model

Each experimental run should follow the same structure:

1. **Warm-up / baseline phase**
   The network is left in normal condition so the probe can observe baseline values.

2. **Fault injection phase**
   A controlled impairment is injected. The injector must record `fault_start_ts`, `fault_end_ts`, `scenario_id`, and parameters.

3. **Event detection phase**
   Micro-UXI evaluates telemetry and triggers an event if the scheme-specific condition is met for a required number of samples.

4. **Post-event / recovery phase**
   The impairment is removed. The event is closed only after recovery conditions are met.

5. **Evidence export phase**
   The system stores telemetry, event metadata, diagnostic snapshots, and pre/event/post windows.

---

## 2. Common Event Fields

Each detected event should use a consistent event metadata structure.

```json
{
  "event_id": "evt-...",
  "run_id": "run-...",
  "scenario_id": "S1_DNS_DEGRADED",
  "event_type": "DNS_DEGRADED",
  "affected_scope": "internal | external | all | unknown",
  "affected_targets": ["portal.its.ac.id"],
  "severity": "low | medium | high",
  "ts_start": "2026-...",
  "ts_end": "2026-...",
  "trigger_reason": "max_dns_latency_ms=720 >= threshold=300",
  "recovery_reason": "dns_latency_ms back under threshold for K seconds"
}
```

### Affected Scope

For DNS and HTTP-related schemes, targets should be grouped by scope:

* `internal`: organization/campus-owned services, for example `portal.its.ac.id`, `classroom.its.ac.id`.
* `external`: public internet or SaaS services, for example `google.com`, `youtube.com`, `drive.google.com`, `atlassian.net`.
* `all`: both internal and external targets are affected.
* `unknown`: insufficient evidence to classify scope.

The event name should remain stable. For example, use `DNS_DEGRADED` as the event type and store whether the affected scope is `internal`, `external`, or `all` as event metadata.

---

## 3. Common Metrics

The following metrics are used across schemes.

| Metric                         | Meaning                                                       | Typical Source                                      |
| ------------------------------ | ------------------------------------------------------------- | --------------------------------------------------- |
| `wifi_up` / `wifi_connected`   | Whether the Wi-Fi interface/link appears up                   | `fast_probe.py`, `telemetry_probe.py`               |
| `wifi_rssi_dbm`                | Wi-Fi signal strength                                         | `telemetry_probe.py`, `throughput_probe.py` context |
| `wifi_bssid`                   | Access point BSSID                                            | `telemetry_probe.py`, `throughput_probe.py` context |
| `ping.success`                 | Whether ICMP reachability test succeeded                      | `fast_probe.py`                                     |
| `ping.rtt_ms`                  | Single fast-probe ping RTT                                    | `fast_probe.py`                                     |
| `rtt_avg_ms`                   | Average RTT from multi-packet telemetry ping                  | `telemetry_probe.py`                                |
| `loss_pct`                     | Packet loss percentage from telemetry ping                    | `telemetry_probe.py`                                |
| `dns_success`                  | Whether DNS resolution succeeded                              | `fast_probe.py`, `telemetry_probe.py`               |
| `dns_latency_ms`               | DNS resolution latency                                        | `fast_probe.py`, `telemetry_probe.py`               |
| `http_dns_ms`                  | DNS phase duration in HTTP/curl check                         | `telemetry_probe.py`, `throughput_probe.py`         |
| `http_connect_ms`              | TCP connect checkpoint/duration depending on implementation   | `telemetry_probe.py`, `throughput_probe.py`         |
| `http_tls_ms`                  | TLS handshake checkpoint/duration depending on implementation | `telemetry_probe.py`, `throughput_probe.py`         |
| `http_ttfb_ms`                 | Time to first byte                                            | `telemetry_probe.py`, `throughput_probe.py`         |
| `http_total_ms`                | Total HTTP transaction duration                               | `telemetry_probe.py`, `throughput_probe.py`         |
| `throughput_total_mbps`        | End-to-end download throughput                                | `throughput_probe.py`                               |
| `upload_throughput_total_mbps` | End-to-end upload throughput                                  | `throughput_probe.py`                               |

---

# S1 — DNS_DEGRADED

## Description

`DNS_DEGRADED` is a condition where DNS resolution still succeeds, but DNS latency becomes abnormally high compared with the normal baseline or a configured threshold. This is not a full DNS outage. The defining characteristic is successful but slow DNS resolution.

This scheme is used to evaluate whether Micro-UXI can detect degraded name resolution before it becomes a total timeout or connectivity failure.

## Fault Injection Method

Inject artificial delay into DNS traffic.

Example parameters:

```yaml
scenario_id: S1_DNS_DEGRADED
fault_type: dns_delay
target_scope: internal | external | all
injected_delay_ms: 200-800
duration_sec: 30-120
```

Possible implementation approaches:

* Add delay to UDP/TCP port 53 traffic using traffic control on the fault injection laptop/router.
* Delay DNS responses for selected domains only.
* Delay internal domains and external domains separately when testing scope classification.

## User Impact

Users may still be connected to Wi-Fi and the internet, but opening a new website or application feels slow because name resolution takes longer before the actual connection starts.

Typical symptoms:

* First page load feels delayed.
* Applications that frequently resolve hostnames feel sluggish.
* Already-established connections may continue normally.

## Expected Observable Symptoms

Expected telemetry pattern:

* `wifi_up == true`
* `ping.success == true`
* `dns_success == true`
* `dns_latency_ms` increases beyond threshold or baseline deviation
* HTTP total time may increase if the HTTP check includes DNS resolution

## Trigger Logic

### Primary Metrics

| Metric           | Required Condition                                          | Source                                |
| ---------------- | ----------------------------------------------------------- | ------------------------------------- |
| `dns_latency_ms` | `>= dns_latency_threshold_ms` or exceeds baseline deviation | `fast_probe.py`, `telemetry_probe.py` |
| `dns_success`    | `true`                                                      | `fast_probe.py`, `telemetry_probe.py` |

### Supporting Metrics

| Metric           | Purpose                                                | Source            |
| ---------------- | ------------------------------------------------------ | ----------------- |
| `wifi_up`        | Ensures the event is not caused by Wi-Fi disconnection | `fast_probe.py`   |
| `ping.success`   | Ensures IP connectivity is still alive                 | `fast_probe.py`   |
| `affected_scope` | Distinguishes internal vs external DNS degradation     | DNS target config |

### Recommended Rule

```text
Trigger DNS_DEGRADED when:
  wifi_up == true
  ping.success == true
  dns_success_ratio(scope) >= minimum_success_ratio
  max_dns_latency_ms(scope) >= dns_latency_threshold_ms
  condition holds for N consecutive samples
```

Example threshold:

```yaml
dns_latency_threshold_ms: 300
confirm_consecutive: 2
minimum_success_ratio: 1.0
```

### Baseline-Aware Rule

```text
Trigger DNS_DEGRADED when:
  dns_success == true
  dns_latency_ms >= rolling_median_dns_latency + k * MAD_dns_latency
  condition holds for N consecutive samples
```

## Recovery Logic

```text
Recover when:
  dns_success_ratio(scope) >= minimum_success_ratio
  max_dns_latency_ms(scope) < dns_latency_threshold_ms
  condition holds for K seconds or K samples
```

## Evidence to Record

* DNS samples from pre-event, event, and post-event windows.
* Internal/external target classification.
* Resolver used.
* Wi-Fi snapshot: SSID, BSSID, RSSI, bitrate, frequency.
* Network snapshot: IP, gateway, DNS resolver.
* HTTP timing snapshot if HTTP latency also increases.

## Ground Truth Fields

```yaml
scenario_id: S1_DNS_DEGRADED
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_domains: [...]
injected_delay_ms: ...
dns_protocol: udp | tcp | both
```

## Notes / Caveats

* Slow DNS can be caused by resolver overload, DNS forwarding delay, wireless delay, or upstream path delay.
* If DNS fails entirely, classify as S2 rather than S1.
* If ping also fails, classify as connectivity or packet-loss-related instead of DNS-only degradation.

---

# S2 — DNS_TIMEOUT_BURST

## Description

`DNS_TIMEOUT_BURST` is a condition where DNS queries fail or time out repeatedly within a short time window. Unlike `DNS_DEGRADED`, this scheme represents DNS resolution failure rather than slow but successful resolution.

The event is DNS-specific when IP reachability remains available while DNS resolution fails.

## Fault Injection Method

Inject DNS drop/timeout conditions.

Example parameters:

```yaml
scenario_id: S2_DNS_TIMEOUT_BURST
fault_type: dns_timeout_burst
target_scope: internal | external | all
burst_duration_sec: 5-10
repeat_count: 3
recovery_gap_sec: 5
```

Possible implementation approaches:

* Drop UDP/TCP port 53 traffic.
* Drop DNS traffic only for selected domains or resolvers.
* Drop internal DNS and external DNS separately to validate scope classification.

## User Impact

Users may remain connected to Wi-Fi and may still reach existing IP connections, but opening new services fails because hostnames cannot be resolved.

Typical symptoms:

* Browser shows DNS error.
* Apps fail to start new sessions.
* Some already-open services may still work temporarily because of cached DNS or existing connections.

## Expected Observable Symptoms

Expected telemetry pattern:

* `wifi_up == true`
* `ping.success == true`
* `dns_success == false` for affected scope
* DNS latency may approach timeout duration
* HTTP checks may fail early due to name resolution failure

## Trigger Logic

### Primary Metrics

| Metric           | Required Condition            | Source                                |
| ---------------- | ----------------------------- | ------------------------------------- |
| `dns_success`    | `false` for affected scope    | `fast_probe.py`, `telemetry_probe.py` |
| `dns_fail_ratio` | `>= dns_fail_ratio_threshold` | derived from DNS samples              |

### Supporting Metrics

| Metric           | Purpose                                                 | Source            |
| ---------------- | ------------------------------------------------------- | ----------------- |
| `wifi_up`        | Confirms Wi-Fi is not down                              | `fast_probe.py`   |
| `ping.success`   | Confirms IP connectivity is still alive                 | `fast_probe.py`   |
| `affected_scope` | Separates internal, external, and all-target DNS outage | DNS target config |

### Recommended Rule

```text
Trigger DNS_TIMEOUT_BURST when:
  wifi_up == true
  ping.success == true
  dns_fail_ratio(scope) >= dns_fail_ratio_threshold
  condition holds for N consecutive samples within burst_window_sec
```

Example threshold:

```yaml
dns_fail_ratio_threshold: 1.0
confirm_consecutive: 2
burst_window_sec: 5-10
```

### Scope Classification

```text
if internal_dns_fail_ratio >= threshold and external_dns_fail_ratio < threshold:
  affected_scope = internal

if external_dns_fail_ratio >= threshold and internal_dns_fail_ratio < threshold:
  affected_scope = external

if internal_dns_fail_ratio >= threshold and external_dns_fail_ratio >= threshold:
  affected_scope = all
```

## Recovery Logic

```text
Recover when:
  dns_success_ratio(scope) >= recovery_success_ratio
  condition holds for K seconds or K samples
```

## Evidence to Record

* DNS fail/success samples for all scoped targets.
* Resolver used.
* DNS error type if available.
* Ping status during DNS failure.
* Wi-Fi/network snapshot.
* HTTP error output if HTTP check fails due to DNS.

## Ground Truth Fields

```yaml
scenario_id: S2_DNS_TIMEOUT_BURST
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_domains: [...]
drop_ratio: 1.0
burst_duration_sec: ...
repeat_count: ...
```

## Notes / Caveats

* The current probe should distinguish timeout from NXDOMAIN, SERVFAIL, REFUSED, and other DNS failures if possible.
* If ping fails together with DNS, classify as S6 or S3 depending on connectivity state.
* DNS caching may hide short DNS outage bursts; targets should bypass cache where possible.

---

# S3 — LOSS_BURST

## Description

`LOSS_BURST` is a condition where packet loss increases sharply during a short interval while Wi-Fi remains associated. It represents transient connectivity degradation rather than a stable disconnection.

## Fault Injection Method

Inject packet loss on the network path.

Example parameters:

```yaml
scenario_id: S3_LOSS_BURST
fault_type: packet_loss_burst
loss_pct: 5-20
burst_duration_sec: 3-10
repeat_count: 3
```

Possible implementation approaches:

* Apply packet loss using traffic control on the fault injection laptop/router.
* Apply loss to ICMP only for controlled evaluation.
* Apply loss to all traffic for broader UXI impact testing.

## User Impact

Users may experience intermittent loading failures, short freezes, unstable voice/video calls, or random application retries.

Typical symptoms:

* Some requests succeed, others fail.
* Video call quality may degrade.
* Web pages may partially load or require refresh.
* Latency may become unstable.

## Expected Observable Symptoms

Expected telemetry pattern:

* `wifi_up == true`
* `ping.success` intermittently false
* `ping_loss_pct_window` increases
* DNS may still succeed or intermittently fail depending on loss severity
* HTTP may show timeout/retry behavior under heavier loss

## Trigger Logic

### Primary Metrics

| Metric                 | Required Condition      | Source                         |
| ---------------------- | ----------------------- | ------------------------------ |
| `ping_loss_pct_window` | `>= loss_threshold_pct` | derived from fast ping samples |
| `ping.success`         | repeated false samples  | `fast_probe.py`                |

### Supporting Metrics

| Metric                      | Purpose                                                 | Source               |
| --------------------------- | ------------------------------------------------------- | -------------------- |
| `wifi_up`                   | Confirms the link is still associated                   | `fast_probe.py`      |
| `dns_success`               | Helps distinguish packet loss from DNS-specific failure | `fast_probe.py`      |
| `http_total_ms` / `curl_rc` | Shows application impact if affected                    | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger LOSS_BURST when:
  wifi_up == true
  ping_loss_pct_window >= loss_threshold_pct
  sample_count_window >= minimum_samples
  condition holds within burst_window_sec
```

Example threshold:

```yaml
loss_threshold_pct: 20
window_sec: 10
minimum_samples: 5
```

## Recovery Logic

```text
Recover when:
  ping_loss_pct_window < recovery_loss_threshold_pct
  condition holds for K seconds or K samples
```

## Evidence to Record

* Fast ping success/failure window.
* Computed packet loss ratio.
* DNS samples during the same window.
* Wi-Fi snapshot to prove the device did not disconnect.
* HTTP timing/error if user-facing application checks are affected.

## Ground Truth Fields

```yaml
scenario_id: S3_LOSS_BURST
fault_start_ts: ...
fault_end_ts: ...
loss_pct: ...
loss_target: icmp | dns | http | all
burst_duration_sec: ...
repeat_count: ...
```

## Notes / Caveats

* A single failed ping is not enough to prove packet loss burst. The preferred metric is loss percentage in a sliding window.
* ICMP may be handled differently from application traffic, so application-level symptoms should be recorded when possible.
* If DNS and ping both fail continuously, the event may be closer to S6.

---

# S4 — HIGH_RTT

## Description

`HIGH_RTT` is a condition where round-trip time increases significantly compared with the normal baseline or a configured threshold. This event represents latency degradation, not necessarily packet loss or outage.

## Fault Injection Method

Inject delay into the network path.

Example parameters:

```yaml
scenario_id: S4_HIGH_RTT
fault_type: rtt_increase
injected_delay_ms: 100-500
duration_sec: 60-180
target: gateway | internet | all
```

Possible implementation approaches:

* Add delay using traffic control.
* Apply delay to ICMP and application traffic.
* Apply delay to upstream path while keeping packet loss low.

## User Impact

Users may experience sluggish interaction, delayed page loads, slow login flows, lag in video calls, and delayed application response even though connectivity remains available.

## Expected Observable Symptoms

Expected telemetry pattern:

* `rtt_avg_ms` increases
* `rtt_max_ms` and `rtt_mdev_ms` may increase
* `loss_pct` remains low or moderate
* HTTP `ttfb` or total time may increase
* DNS latency may or may not increase depending on injection scope

## Trigger Logic

### Primary Metrics

| Metric       | Required Condition                                  | Source               |
| ------------ | --------------------------------------------------- | -------------------- |
| `rtt_avg_ms` | `>= rtt_threshold_ms` or exceeds baseline deviation | `telemetry_probe.py` |
| `loss_pct`   | `< loss_threshold_pct`                              | `telemetry_probe.py` |

### Supporting Metrics

| Metric          | Purpose                           | Source               |
| --------------- | --------------------------------- | -------------------- |
| `rtt_mdev_ms`   | Indicates RTT instability/jitter  | `telemetry_probe.py` |
| `http_ttfb_ms`  | Shows user-facing latency impact  | `telemetry_probe.py` |
| `wifi_rssi_dbm` | Helps diagnose RF-related latency | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger HIGH_RTT when:
  rtt_avg_ms >= rtt_threshold_ms
  loss_pct < loss_threshold_pct
  condition holds for N telemetry samples
```

Example threshold:

```yaml
rtt_threshold_ms: 150
loss_threshold_pct: 10
confirm_consecutive: 2
```

### Baseline-Aware Rule

```text
Trigger HIGH_RTT when:
  rtt_avg_ms >= rolling_median_rtt + k * MAD_rtt
  loss_pct < loss_threshold_pct
  condition holds for N samples
```

## Recovery Logic

```text
Recover when:
  rtt_avg_ms < recovery_rtt_threshold_ms
  loss_pct < loss_threshold_pct
  condition holds for K seconds or K telemetry samples
```

## Evidence to Record

* Ping RTT min/avg/max/mdev.
* Packet loss percentage.
* HTTP timing during latency increase.
* Wi-Fi snapshot.
* Network snapshot.
* Baseline values if available.

## Ground Truth Fields

```yaml
scenario_id: S4_HIGH_RTT
fault_start_ts: ...
fault_end_ts: ...
injected_delay_ms: ...
delay_target: gateway | internet | all
affected_protocols: icmp | dns | http | all
```

## Notes / Caveats

* High RTT can be caused by Wi-Fi signal issues, bufferbloat, upstream congestion, or server-side delay.
* If packet loss is high, classify as S3 or mixed event rather than pure HIGH_RTT.
* Measuring both gateway RTT and external RTT would improve root-cause isolation.

---

# S5 — HTTP_SLOW

## Description

`HTTP_SLOW` is a condition where application-layer checks become slow or fail. It is detected through HTTP transaction timing such as DNS lookup time, TCP connect time, TLS time, time to first byte, and total request time.

This scheme focuses on application experience rather than raw throughput. A service can have acceptable ping and DNS, but still be slow at HTTP/TLS/application response level.

## Fault Injection Method

Inject delay, timeout, or throttling into HTTP/application traffic.

Example parameters:

```yaml
scenario_id: S5_HTTP_SLOW
fault_type: http_slow
injected_delay_ms: 300-2000
duration_sec: 60-180
target_scope: internal | external | all
target_urls: [...]
```

Possible implementation approaches:

* Delay traffic to selected HTTP/HTTPS endpoints.
* Slow down a local test web server.
* Inject TLS/connect delay if supported by the test environment.
* Apply bandwidth throttling as a related but separate throughput impairment.

## User Impact

Users experience slow page loads, delayed application login, slow API response, or application timeout even if Wi-Fi and DNS appear normal.

## Expected Observable Symptoms

Expected telemetry pattern:

* `http_total_ms` increases
* `http_ttfb_ms` may increase if server/application response is delayed
* `http_tls_ms` may increase if TLS handshake is affected
* `curl_rc != 0` or HTTP status error if timeout occurs
* DNS and ping may remain normal

## Trigger Logic

### Primary Metrics

| Metric          | Required Condition                                         | Source               |
| --------------- | ---------------------------------------------------------- | -------------------- |
| `http_total_ms` | `>= http_total_threshold_ms` or exceeds baseline deviation | `telemetry_probe.py` |
| `http_ttfb_ms`  | `>= http_ttfb_threshold_ms` or exceeds baseline deviation  | `telemetry_probe.py` |
| `curl_rc`       | non-zero indicates HTTP check failure                      | `telemetry_probe.py` |
| `http_status`   | outside expected 2xx/3xx range indicates application issue | `telemetry_probe.py` |

### Supporting Metrics

| Metric                           | Purpose                                                 | Source                                |
| -------------------------------- | ------------------------------------------------------- | ------------------------------------- |
| `dns_success` / `dns_latency_ms` | Helps separate HTTP slow from DNS slow                  | `fast_probe.py`, `telemetry_probe.py` |
| `rtt_avg_ms`                     | Helps separate HTTP slow from general latency           | `telemetry_probe.py`                  |
| `loss_pct`                       | Helps separate HTTP slow from packet loss               | `telemetry_probe.py`                  |
| `affected_scope`                 | Distinguishes internal vs external application slowness | HTTP target config                    |

### Recommended Rule

```text
Trigger HTTP_SLOW when:
  wifi_connected == true
  DNS is not failing globally
  and one of:
    http_total_ms(scope) >= http_total_threshold_ms
    http_ttfb_ms(scope) >= http_ttfb_threshold_ms
    curl_rc != 0
    http_status not in expected range
  condition holds for N telemetry samples
```

Example threshold:

```yaml
http_total_threshold_ms: 2000
http_ttfb_threshold_ms: 1000
confirm_consecutive: 2
```

### Baseline-Aware Rule

```text
Trigger HTTP_SLOW when:
  http_total_ms >= rolling_median_http_total + k * MAD_http_total
  or http_ttfb_ms >= rolling_median_ttfb + k * MAD_ttfb
```

## Recovery Logic

```text
Recover when:
  HTTP checks return expected status
  http_total_ms < recovery_http_total_threshold_ms
  condition holds for K seconds or K telemetry samples
```

## Evidence to Record

* HTTP timing breakdown.
* Curl return code and stderr.
* HTTP status code.
* DNS timing for the same target.
* Ping RTT/loss around the event.
* Wi-Fi/network snapshot.
* Internal/external target scope.

## Ground Truth Fields

```yaml
scenario_id: S5_HTTP_SLOW
fault_start_ts: ...
fault_end_ts: ...
target_scope: internal | external | all
target_urls: [...]
injected_delay_ms: ...
timeout_sec: ...
affected_phase: dns | tcp | tls | ttfb | total | unknown
```

## Notes / Caveats

* HTTP slow can be caused by DNS, TCP, TLS, server delay, packet loss, or bandwidth constraints. The timing breakdown is needed to isolate the dominant phase.
* If the experiment is specifically bandwidth throttling, record it as a throughput-related variant or a separate scheme.

---

# S5-alt — BANDWIDTH_THROTTLE / THROUGHPUT_DEGRADED

> Use this section if the experiment keeps bandwidth throttling as the fifth fault injection scenario instead of HTTP_SLOW.

## Description

`BANDWIDTH_THROTTLE` is a condition where measured download or upload throughput drops below an expected threshold or baseline. It is detected using active throughput testing.

## Fault Injection Method

Limit available bandwidth.

Example parameters:

```yaml
scenario_id: S5_BANDWIDTH_THROTTLE
fault_type: bandwidth_throttle
download_limit_mbps: 1-5
upload_limit_mbps: 1-5
duration_sec: 60-180
```

## User Impact

Users experience slow downloads, slow uploads, poor video quality, slow file synchronization, and degraded SaaS performance.

## Trigger Logic

```text
Trigger BANDWIDTH_THROTTLE when:
  download_throughput_total_mbps < download_threshold_mbps
  or upload_throughput_total_mbps < upload_threshold_mbps
  or all throughput runs fail
  condition holds for N throughput samples
```

Primary metrics:

| Metric                                            | Source                |
| ------------------------------------------------- | --------------------- |
| `summary.download.throughput_total_mbps.avg`      | `throughput_probe.py` |
| `summary.upload.upload_throughput_total_mbps.avg` | `throughput_probe.py` |
| `summary.download.run_health`                     | `throughput_probe.py` |
| `summary.upload.run_health`                       | `throughput_probe.py` |

## Notes / Caveats

* If throughput target is Cloudflare, the affected scope is external by default.
* Internal/external throughput comparison only makes sense if both internal and external throughput endpoints exist.

---

# S6 — CONNECTIVITY_FLAP

## Description

`CONNECTIVITY_FLAP` is a condition where connectivity repeatedly changes between connected/reachable and disconnected/unreachable within a short time window. It is not limited to Wi-Fi disconnection. Wi-Fi link flap is one possible cause, but upstream connectivity flap can also occur while Wi-Fi remains associated.

The key characteristic is repeated state transition, not just one failed sample.

## Fault Injection Method

Repeatedly interrupt and restore connectivity.

Example parameters:

```yaml
scenario_id: S6_CONNECTIVITY_FLAP
fault_type: connectivity_flap
down_duration_sec: 2-10
up_duration_sec: 2-10
repeat_count: 3-5
affected_layer: wifi | gateway | upstream | dns | all
```

Possible implementation approaches:

* Temporarily block all outbound traffic repeatedly.
* Toggle gateway reachability.
* Disable and re-enable Wi-Fi association for Wi-Fi-specific flap.
* Drop DNS and ping together while leaving Wi-Fi associated to emulate upstream flap.

## User Impact

Users experience intermittent disconnects, applications repeatedly reconnect, calls drop or freeze, and web/app sessions may fail unpredictably.

## Expected Observable Symptoms

Expected telemetry pattern:

* `connectivity_ok` changes `true -> false -> true` repeatedly
* `ping.success` may alternate success/failure
* `dns_success` may alternate success/failure
* `wifi_up` may remain true for upstream flap
* `wifi_up` may alternate for Wi-Fi link flap
* HTTP checks may alternate success/failure

## Trigger Logic

### Primary Metrics

| Metric            | Required Condition                     | Source                       |
| ----------------- | -------------------------------------- | ---------------------------- |
| `connectivity_ok` | repeated state transitions             | derived from `fast_probe.py` |
| `ping.success`    | may alternate true/false               | `fast_probe.py`              |
| `dns_success`     | may alternate true/false               | `fast_probe.py`              |
| `wifi_up`         | identifies Wi-Fi flap vs upstream flap | `fast_probe.py`              |

### Supporting Metrics

| Metric                    | Purpose                                  | Source               |
| ------------------------- | ---------------------------------------- | -------------------- |
| `wifi_bssid`              | Detects AP roam/reassociation            | `telemetry_probe.py` |
| `wifi_rssi_dbm`           | Helps identify RF instability            | `telemetry_probe.py` |
| `http_status` / `curl_rc` | Confirms application reachability impact | `telemetry_probe.py` |

### Recommended Rule

```text
Trigger CONNECTIVITY_FLAP when:
  state_transition_count(connectivity_ok) >= flap_transition_threshold
  within flap_window_sec
```

Example threshold:

```yaml
flap_transition_threshold: 2
flap_window_sec: 30
confirm_consecutive: 1
```

### Suspected Layer Classification

```text
if wifi_up alternates true/false:
  suspected_layer = wifi_link

if wifi_up remains true but ping and DNS alternate fail/success:
  suspected_layer = upstream

if ping remains OK but DNS alternates fail/success:
  suspected_layer = dns

if ping and DNS remain OK but HTTP alternates fail/success:
  suspected_layer = application
```

## Recovery Logic

```text
Recover when:
  connectivity_ok == true
  no additional state transition occurs for K seconds
```

## Evidence to Record

* Fast connectivity state sequence.
* Ping success/failure timeline.
* DNS success/failure timeline.
* Wi-Fi link state timeline.
* BSSID/RSSI snapshots if Wi-Fi is suspected.
* HTTP success/failure if application reachability is affected.

## Ground Truth Fields

```yaml
scenario_id: S6_CONNECTIVITY_FLAP
fault_start_ts: ...
fault_end_ts: ...
down_duration_sec: ...
up_duration_sec: ...
repeat_count: ...
affected_layer: wifi | gateway | upstream | dns | all
```

## Notes / Caveats

* A single outage is not necessarily a flap. Flap requires repeated transition.
* Wi-Fi disconnection and upstream outage should be represented as different suspected layers under the same event type.
* If all samples remain failed without recovery, classify as sustained outage rather than flap.

---

# 4. Recommended README-Level Threshold Configuration

Initial thresholds should be treated as starting values and tuned during experiments.

```yaml
thresholds:
  dns_latency_threshold_ms: 300
  dns_fail_ratio_threshold: 1.0
  dns_recovery_success_ratio: 1.0

  loss_threshold_pct: 20
  loss_window_sec: 10

  rtt_threshold_ms: 150
  rtt_loss_upper_bound_pct: 10

  http_total_threshold_ms: 2000
  http_ttfb_threshold_ms: 1000

  throughput_download_threshold_mbps: 3
  throughput_upload_threshold_mbps: 3

  flap_transition_threshold: 2
  flap_window_sec: 30

  confirm_consecutive: 2
  recovery_consecutive: 2
```

---

# 5. Minimal Evidence Bundle Checklist

Each detected event should produce at least:

```text
[event_id]/
  event_meta.json
  ground_truth_ref.json
  pre_window.jsonl or pre_window.csv
  event_window.jsonl or event_window.csv
  post_window.jsonl or post_window.csv
  net_snapshot.txt
  wifi_snapshot.txt
  probe_config.json
```

For DNS-related events, include:

```text
  dns_samples.jsonl
```

For HTTP-related events, include:

```text
  http_timing_samples.jsonl
```

For throughput-related events, include:

```text
  throughput_samples.jsonl
```

---

# 6. Ground Truth Alignment

A detected event matches an injected fault if:

```text
event_type matches expected scenario type
and event.ts_start is within [fault_start_ts - delta, fault_end_ts + delta]
```

Recommended tolerance:

```yaml
alignment_delta_sec: 2-5
```

If multiple events match one fault, use one predefined strategy:

* `first-match`: use the first valid event.
* `best-overlap`: use the event with the largest time overlap.

The chosen strategy must remain consistent across all experiments.

---

# 7. Open Design Decision

There is one important naming decision:

* The proposal event definition includes `HTTP_SLOW`.
* The planned fault injection scenarios also include `Bandwidth Throttling`.
* The current throughput probe supports download/upload throughput measurement.

Recommended resolution:

```text
Keep S5 = HTTP_SLOW for application-layer degradation.
Add S5-alt or S7 = BANDWIDTH_THROTTLE for throughput-specific degradation.
```

If the final evaluation must keep exactly six schemes, replace `HTTP_SLOW` with `BANDWIDTH_THROTTLE` only if the experiment focuses on throughput impairment rather than HTTP application timing.
