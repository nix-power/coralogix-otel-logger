# Coralogix OTel Logger

A production-grade, highly resilient OpenTelemetry (OTel) logger for Python applications sending structured data to Coralogix via gRPC.

Based on [Official Coralogix Documentation](https://coralogix.com/docs/integrations/sdks/python-sdk/)

This package is designed to solve the common pitfalls of enterprise OTel deployments, acting as a drop-in integration that natively complements standard structured telemetry workflows without breaking existing console or file logs.

---

## Why This Exists

When deploying OTel in corporate environments, engineers typically run into critical infrastructure roadblocks. This logger handles them automatically:

1. **Additive Handler Architecture:** Instead of forcing you to manage two separate logging pipelines (one for `stdout` and one for Coralogix), this SDK seamlessly injects itself into any existing standard Python logger.
2. **Deterministic Schemas via `extra`:** Raw JSON dumped to standard out causes mapping conflicts in database backends. This logger preserves clean, human-readable terminal output while routing deep structured metadata as OpenTelemetry attributes via Python's native `extra` mechanism.
3. **Accurate Caller Metadata:** Solves the common "wrapper trap" by dynamically traversing execution stacks to bypass the SDK wrapper methods. Logs will accurately report the exact file, function, and line number of your application code, completely immune to interactive shells like Jupyter/IPython.
4. **Global State Conflicts:** Safely guards OpenTelemetry singletons to prevent network leaks and duplication in containerized environments.

---

## Installation

```bash
pip install coralogix-otel-logger
```

---

## Environment Configuration

You can leverage native infrastructure environment variables to configure the SDK automatically:

| Environment Variable | Expected Values | Behavior |
| :--- | :--- | :--- |
| `CORALOGIX_API_KEY` | `str` (e.g., `cx-...`) | The private Send-Your-Data administrative token. Used automatically if `api_key` is omitted. |
| `CORALOGIX_REGION` | `eu1`, `eu2`, `us1`, `us2`, `us3`, `ap1`, `ap2`, `ap3` | Automatically standardizes and resolves the target endpoint to `https://ingress.{region}.coralogix.com:443`. |

---

## Integration Patterns

Because this wrapper is non-destructive, your development team can adopt it using either a clean abstraction or pure zero-dependency Python code.

### Pattern 1: The Unified Wrapper (Clean Syntax)
Initialize the SDK targeting your application's existing logger name. The wrapper will safely adopt it. Your terminal stays clean, and Coralogix gets the rich `payload`.

```python
import logging
from cxlogger import CoralogixOTelLogger

# 1. Your standard corporate logging setup
logger = logging.getLogger("auth_service")
logger.addHandler(logging.StreamHandler())

# 2. Additive initialization targeting your exact logger
with CoralogixOTelLogger(
    app_name="ldap-mgr",
    subsystem_name="audit",
    logger_name="auth_service"
) as cx_logger:

    audit_data = {"user": "alex_admin", "status": "verified"}

    # Outputs clean text to terminal: "[INFO] Auth process completed"
    # Streams structured JSON to Coralogix containing the audit_data attributes
    cx_logger.info("Auth process completed", payload=audit_data)
```

### Pattern 2: Pure Native Python Logging (Downstream Modules)
You only need to import and initialize the `cxlogger` SDK **once** at your application's entry point. Once the OTel handler is bound to Python's global registry, developers working in other files across the codebase can write standard native Python code without needing to import the SDK into their specific files.

**1. At the Application Entry Point (e.g., `main.py`):**
```python
import logging
from cxlogger import CoralogixOTelLogger

# Set up your standard corporate logging
logger = logging.getLogger("auth_service")
logger.addHandler(logging.StreamHandler())

# Initialize the SDK exactly ONCE to equip the global logger with the Coralogix handler
cx_plugin = CoralogixOTelLogger(
    app_name="auth",
    subsystem_name="api",
    logger_name="auth_service"
)
```

**2. Deep inside another project file (e.g., `lib/database.py`):**
```python
import logging
# Notice: No cxlogger import needed here!

# Grabs the exact same logger object equipped during startup
logger = logging.getLogger("auth_service")

# By using Python's native `extra` keyword, the OpenTelemetry background worker
# automatically translates this into rich Coralogix JSON attributes!
logger.info(
    "Data processed securely",
    extra={"payload": {"bytes": 4096, "latency_ms": 120}}
)
```

---

## Tuning the Telemetry Transport

OpenTelemetry utilizes unmanaged background worker threads to transmit data over the network. Export latency is fully under your control via the `flush_delay_ms` parameter in the constructor (defaults to `5000` ms).

* **For long-running Daemons/Microservices:** Leave the default (`5000`). It optimizes network bandwidth by batching logs together over 5-second intervals.
* **For ephemeral CI/CD automation scripts:** Set it low (e.g., `200`) and wrap the execution in a Context Manager (`with` block). This ensures high-throughput execution and guarantees a synchronous network flush before the container dies.

---

## Coralogix UI Rendering & Schema Alignment

OpenTelemetry maps log messages directly to the OTLP protocol `body` block. However, when an OTel packet contains rich key-value lists, the Coralogix frontend UI column template bypasses the native protocol body and scans the custom attribute tree searching for a root-level key string to render as the main dashboard headline.

To guarantee crisp row readability out of the box, **this SDK intentionally injects a root-level `"message"` key inside your `attributes.payload` namespace.**

### A Note on Custom Infrastructure Schemas
`message` is the standard anchor for string headers. However, user-defined metadata spaces in Coralogix are dynamic. If your enterprise infrastructure team has manually deleted or renamed the `"message"` field mapping inside your Coralogix account's **Schema Manager** settings, the Coralogix column template will fail to resolve the path. It will fall back to an automated guessing heuristic, causing your main grid layout to randomly alternate text.

Ensure `"message"` is preserved as a designated String field in your account's schema configuration to lock down uniform layout fidelity across your logs.

---

## Fail-Safe Typing Enforcement

To maintain perfectly predictable schemas across your team, the `payload` argument strictly expects a Python dictionary (`dict`).

If a developer mistakenly passes an invalid type (such as a list) into the `payload` parameter, the SDK safeguards your cluster: it **will not crash your runtime environment**. Instead, it intercepts the error, flags the log severity to `ERROR`, and routes a high-visibility structural misuse notification to your Coralogix dashboard.

---

## License
Apache 2.0 License.