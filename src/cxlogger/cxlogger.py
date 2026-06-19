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
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        log_level: str = "info",
        cert_path: Optional[str] = None
    ):
        self.app_name = app_name
        self.subsystem_name = subsystem_name
        self.logger_name = f"cx_{app_name}_{subsystem_name}"
        self.cert_path = cert_path

        effective_api_key = api_key or os.environ.get("CORALOGIX_API_KEY")
        if not effective_api_key:
            raise ValueError(
                "Coralogix API key is missing. You must provide it via the 'api_key' parameter "
                "or set the 'CORALOGIX_API_KEY' environment variable."
            )

        if domain is None:
            env_region = os.environ.get("CORALOGIX_REGION")
            if env_region:
                # All Coralogix regions now strictly follow: {region}.coralogix.com
                # e.g., eu1, eu2, us1, us2, us3, ap1, ap2, ap3
                self.domain = f"{env_region.lower()}.coralogix.com"
            else:
                self.domain = "us1.coralogix.com"
        else:
            self.domain = domain

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

            endpoint = f"https://ingress.{self.domain}:443"

            exporter_kwargs = {
                "endpoint": endpoint,
                "headers": {"authorization": f"Bearer {effective_api_key}"}
            }
            if self.cert_path and os.path.exists(self.cert_path):
                exporter_kwargs["certificate_file"] = self.cert_path

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
            f"app_name={self.app_name!r}, "
            f"subsystem_name={self.subsystem_name!r}, "
            f"api_key='***', "
            f"domain={self.domain!r}, "
            f"log_level={self.log_level_repr!r}, "
            f"cert_path={self.cert_path!r}"
            f")"
        )

    def _log(self, payload: Dict[str, Any], level: Optional[str] = None) -> None:
        """
        Serializes a native dictionary to a string so Coralogix auto-parses it,
        and ships it via OTel gRPC.
        """
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

    def _transform(self, level: str, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """
        Transforms incoming arguments into a standardized,
        flat JSON payload structure to eliminate platform rendering ambiguity.
        """
        out_payload = {"message": msg}

        if payload is not None:
            if isinstance(payload, dict):
                out_payload.update(payload)
            else:
                out_payload.update({
                    "event_type": "logger_misuse_error",
                    "logger_warning": f"Passed an invalid payload type ({type(payload).__name__}). Expected 'dict'.",
                    "rejected_raw_payload": str(payload)[:500]
                })
                level = "ERROR"

        # Now that the data is transformed, hand it over to the I/O engine to ship it
        self._log(out_payload, level=level)

    def debug(self, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._transform("DEBUG", msg, payload)

    def info(self, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._transform("INFO", msg, payload)

    def warning(self, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._transform("WARNING", msg, payload)

    def error(self, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._transform("ERROR", msg, payload)

    def critical(self, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._transform("CRITICAL", msg, payload)

    def flush(self) -> None:
        """Forces the batch processor to send any remaining logs immediately."""
        if hasattr(self, 'provider') and hasattr(self.provider, 'force_flush'):
            self.provider.force_flush()
