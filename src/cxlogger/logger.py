import os
import json
import logging
import atexit
from typing import Dict, Any, Optional

from opentelemetry import _logs as otel_logs
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

class CoralogixOTelLogger:
    """
    A production-grade OpenTelemetry logger for sending structured JSON
    directly to Coralogix via their official OTLP gRPC endpoint.
    """

    _LEVEL_MAP = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "WARN": logging.WARNING,
        "ERR": logging.ERROR,
        "CRIT": logging.CRITICAL
    }

    def __init__(
        self,
        app_name: str,
        subsystem_name: str,
        api_key: str,
        domain: str = "us1.coralogix.com",
        log_level: str = "info",
        cert_path: Optional[str] = None
    ):
        self.app_name = app_name
        self.subsystem_name = subsystem_name
        self.logger_name = f"cx_{app_name}_{subsystem_name}"

        self.log_level_repr = log_level.upper()
        self.log_level_int = self._LEVEL_MAP.get(self.log_level_repr, logging.INFO)

        current_provider = otel_logs.get_logger_provider()

        if isinstance(current_provider, LoggerProvider):
            self.provider = current_provider
        else:
            resource = Resource.create({
                "cx.application.name": self.app_name,
                "cx.subsystem.name": self.subsystem_name,
                "service.name": f"{app_name}-logger"
            })
            self.provider = LoggerProvider(resource=resource)
            otel_logs.set_logger_provider(self.provider)

            endpoint = f"https://ingress.{domain}:443"
            exporter_kwargs = {
                "endpoint": endpoint,
                "headers": {"authorization": f"Bearer {api_key}"}
            }
            if cert_path and os.path.exists(cert_path):
                exporter_kwargs["certificate_file"] = cert_path

            exporter = OTLPLogExporter(**exporter_kwargs)
            self.provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

        self.logger = logging.getLogger(self.logger_name)
        self.logger.setLevel(self.log_level_int)

        if not self.logger.handlers:
            handler = LoggingHandler(level=self.log_level_int, logger_provider=self.provider)
            self.logger.addHandler(handler)

        atexit.register(self.flush)

    def __str__(self) -> str:
        return f"<Coralogix Logger | App: {self.app_name} | Subsystem: {self.subsystem_name} | Level: {self.log_level_repr}>"

    def __repr__(self) -> str:
        return (
            f"CoralogixOTelLogger("
            f"app_name='{self.app_name}', "
            f"subsystem_name='{self.subsystem_name}', "
            f"log_level='{self.log_level_repr}'"
            f")"
        )

    def log(self, payload: Dict[str, Any], level: Optional[str] = None) -> None:
        """
        Serializes a native dictionary to a string so Coralogix auto-parses it,
        and ships it via OTel gRPC.
        """
        # Parse the override level if provided, otherwise use the class default
        if level:
            emit_level = self._LEVEL_MAP.get(level.upper(), self.log_level_int)
        else:
            emit_level = self.log_level_int

        try:
            stringified_payload = json.dumps(payload)
            self.logger.log(emit_level, stringified_payload)
        except TypeError as e:
            fallback_msg = json.dumps({
                "event_type": "logger_serialization_error",
                "error": str(e),
                "app": self.app_name
            })
            self.logger.error(fallback_msg)

    def flush(self) -> None:
        """Forces the batch processor to send any remaining logs immediately."""
        if hasattr(self, 'provider') and hasattr(self.provider, 'force_flush'):
            self.provider.force_flush()
