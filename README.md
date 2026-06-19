# Coralogix OTel Logger

A production-grade, highly resilient OpenTelemetry (OTel) logger for Python applications sending structured data to Coralogix via gRPC.

Based on [Official Coralogix Documentation](https://coralogix.com/docs/integrations/sdks/python-sdk/)

This package is designed to solve the common pitfalls of enterprise OTel deployments, acting as a drop-in integration that natively complements standard structured telemetry workflows.

---

## Why This Exists

When deploying OTel in corporate environments, engineers typically run into three major roadblocks. This logger handles them automatically:

1. **Global State Conflicts:** The OTel `LoggerProvider` requires strict singleton management. This class safely guards initialization, cleanly reusing an existing provider if found, to prevent duplicate providers and broken pipelines inside containerized architectures.
2. **Corporate SSL / Proxy MITM:** Built-in support for passing custom SSL certificates (`cert_path`) when operating behind strict corporate firewalls that perform deep packet SSL inspection.
3. **Eliminating UI Rendering Ambiguity:** Logging systems often drop data or break dashboard layouts when dynamic data structures vary. By routing all calls through an internal data transformation layer, this SDK maps an explicit plaintext summary headline to the root `"message"` key while cleanly formatting and nesting complex metadata structures below it. This eliminates platform-side heuristic guessing games entirely.

---

## Installation

```bash
pip install coralogix-otel-logger
```

---

## Environment Configuration

Instead of hardcoding sensitive tokens or routing domains in your code, you can leverage native infrastructure environment variables to configure the SDK automatically:

| Environment Variable | Expected Values | Behavior |
| :--- | :--- | :--- |
| `CORALOGIX_API_KEY` | `str` (e.g., `cx-...`) | The private Send-Your-Data administrative token. Used automatically if `api_key` is omitted in the constructor. |
| `CORALOGIX_REGION` | `eu1`, `eu2`, `us1`, `us2`, `us3`, `ap1`, `ap2`, `ap3` | Automatically standardizes and resolves the target endpoint to `https://ingress.{region}.coralogix.com:443`. Case-insensitive. |

*Note: Explicitly passing code parameters (`api_key` or `domain`) in the class constructor will always take priority and override environment variables.*

---

## Tuning the Telemetry Transport

Under the hood, this logger implements the OpenTelemetry `BatchLogRecordProcessor`. To protect the gRPC network transport boundary and prevent memory blowouts (like hitting Coralogix's 32KB per-log or 2MB per-batch limits), structural safety boundaries are strictly hardcoded:
* `max_export_batch_size=50`
* `max_queue_size=2048`

However, **export latency is fully under your control** via the `flush_delay_ms` parameter in the constructor (defaults to `5000` ms).

* **For long-running Daemons/Microservices:** Leave the default (`5000`). It optimizes network bandwidth by batching logs together over 5-second intervals.
* **For ephemeral CI/CD automation scripts:** Set it low (e.g., `200`). This ensures high-throughput, low-latency execution without waiting for background timers.

---

## Quick Start

Initialize the logger once in your application entry point.

```python
import os
from cxlogger import CoralogixOTelLogger

# 1. Initialize the logger
# Leaving api_key empty makes the SDK look for os.environ["CORALOGIX_API_KEY"]
coralogix_logger = CoralogixOTelLogger(
    app_name="ldap-manager",
    subsystem_name="dynamic-secrets",
    log_level="info",     # Optional: defaults to "info"
    flush_delay_ms=5000   # Optional: defaults to 5000ms
)

# 2. Prepare structured dictionary data
audit_data = {
    "event_type": "New Event Type",
    "context": {
        "one": "45345",
        "two": "JLrffsd",
        "pass": True
    }
}

# 3. Ship it cleanly using standard pythonic logging signatures
coralogix_logger.info("GitLab MR Security Audit Event", payload=audit_data)
```

---

## Flushing the Pipeline (CI/CD Safety)

OpenTelemetry utilizes unmanaged background worker threads to transmit data over the network. If you are running short-lived automation scripts (like a GitLab CI runner), the Python interpreter will often exit and kill these background threads **before** they have time to transmit your logs, resulting in silent data loss.

While this package provides an `atexit` fallback hook, **you should always explicitly flush the logger in ephemeral environments.**

### Option A: The Context Manager (Recommended)
Using a `with` block guarantees that the memory queue is flushed exactly when the block concludes, gracefully handling application errors along the way.

```python
with CoralogixOTelLogger(app_name="auth", subsystem_name="audit", flush_delay_ms=200) as logger:
    logger.info("Pipeline started.")
    # Do work...
    logger.info("Pipeline finished.", payload={"status": "success"})

# <-- The gRPC pipeline is fully and safely drained the moment execution leaves the block.
```

### Option B: Explicit Flush
If you are passing the logger around multiple files and cannot use a context manager, manually call `.flush()` right before your script issues a `sys.exit()` or `return`.

```python
logger.info("Final log entry.")

# Force OpenTelemetry to block and transmit all background queues immediately
logger.flush()
```

---

## Fail-Safe Typing Enforcement

To maintain perfectly predictable schemas across your team, the `payload` argument strictly expects a Python dictionary (`dict`).

If a developer mistakenly passes an invalid type (such as a raw string or list) into the `payload` parameter, the SDK safeguards your cluster: it **will not crash your runtime environment**. Instead, it intercepts the error, automatically flags the log severity to `ERROR`, and routes a high-visibility structural misuse notification to your Coralogix dashboard containing the raw rejected chunk so you can catch the bug instantly in staging.

---

## Features

* **Pristine Public Interface:** Exposes only standard pythonic logger methods (`.debug()`, `.info()`, `.warning()`, `.error()`, and `.critical()`), preventing developer friction and code complexity.
* **Unified UI Alignment:** Automatically positions your string message to the root `"message"` field, providing a reliable summary headline in the log grid while rendering your payload as a clean, expandable JSON tree.
* **Credential Masking:** Overrides native internal `__repr__` bindings. Inspecting or printing the logger instance inside terminal prompts (`IPython`), stack traces, or environment outputs automatically masks your private administrative keys as `'***'`.
* **Isolated Serialization Guards:** Heavy JSON encoding processes are fully wrapped inside isolated exception blocks, ensuring logging subsystems never trigger unexpected fatal thread panics.
* **PEP 8 Compliant:** Clean, predictable class design.

---

## License

Apache 2.0 License. See [LICENSE](https://github.com/nix-power/coralogix-otel-logger/blob/main/LICENSE) for more information.
