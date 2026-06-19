# Coralogix OTel Logger

A production-grade, highly resilient OpenTelemetry (OTel) logger for Python applications sending data to Coralogix via gRPC.

This package is designed to solve the common pitfalls of enterprise OTel deployments, acting as a drop-in integration for Python's standard `logging` library.

## Why this exists

When deploying OTel in corporate environments, engineers typically run into three major roadblocks. This logger is built to handle them automatically:

1. **Global State Conflicts:** OTel `LoggerProvider` requires strict singleton management. This class safely guards initialization to prevent duplicate providers and broken pipelines.
2. **Corporate SSL / Proxy MITM:** Built-in support for passing custom SSL certificates when operating behind strict corporate firewalls that perform SSL inspection.
3. **Elasticsearch Mapping Conflicts:** Coralogix relies on Elasticsearch, which drops data when mapping conflicts occur (e.g., a field is a string one day, and an object the next). This logger forces a strict JSON schema and serializes dynamic data (Schema-on-Read) to ensure 100% data ingestion without indexing failures.

## Installation

```bash
pip install coralogix-otel-logger
```

## Quick Start
Initialize the logger once in your application entry point.

It registers uniquely and will not interfere with stdout or other standard loggers.

```py
from cxlogger import CoralogixOTelLogger

# Initialize the production logger
coralogix_logger = CoralogixOTelLogger(
    private_key="your-coralogix-send-your-data-key",
    domain="eu2.coralogix.com, default is us1.coralogix.com",
    app_name="my-production-app",
    subsystem_name="backend-services",
    log_level="info, info is a default and could be omitted"
)

# Use it anywhere in your app
coralogix_logger.log(
    level="info",
    message="Service initialized successfully",
    payload={"status": "active", "dynamic_data": "safely parsed"}
)
```

## Features
Dynamic Data Parsing: Safely processes deeply nested dictionaries and unpredictable diffs into a consistent JSON schema.

Fallback Safety: Never crashes your main application thread due to a malformed log payload.

PEP 8 Compliant: Clean, predictable class design.

## License
Apache 2T License. See [LICENSE](https://github.com/nix-power/coralogix-otel-logger/blob/main/LICENSE) for more information.

