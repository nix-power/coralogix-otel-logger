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

## Quick Start

Initialize the logger once in your application entry point. It safely handles background batch buffering and registers a termination hook via `atexit` to flush remaining logs automatically when the process exits.

```python
import os
from cxlogger import CoralogixOTelLogger

# 1. Initialize the logger
# Leaving api_key empty makes the SDK look for os.environ["CORALOGIX_API_KEY"]
coralogix_logger = CoralogixOTelLogger(
    app_name="ldap-manager",
    subsystem_name="dynamic-secrets",
    log_level="info"  # Optional: defaults to "info"
)

# 2. Prepare structured dictionary data
audit_data = {
    "event_type": "dynamic_mr_approvers_assigned",
    "gitlab_context": {
        "project_id": "7196",
        "mr_iid": "679",
        "mr_initiator": "Dimitry Zyuryaev"
    }
}

# 3. Ship it cleanly using standard pythonic logging signatures
coralogix_logger.info("GitLab MR Security Audit Event", payload=audit_data)
```

### Fail-Safe Typing Enforcement

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