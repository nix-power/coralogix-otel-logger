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

from .exceptions import CoralogixConfigurationError


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
        logger_name: Optional[str] = None,
        api_key: Optional[str] = None,
        domain: Optional[str] = None,
        log_level: str = "info",
        flush_delay_ms=5000,
        cert_path: Optional[str] = None
    ):
        self.app_name = app_name
        self.subsystem_name = subsystem_name
        self.logger_name = logger_name or f"cx_{app_name}_{subsystem_name}"
        self.cert_path = cert_path

        effective_api_key = api_key or os.environ.get("CORALOGIX_API_KEY")
        if not effective_api_key:
            raise CoralogixConfigurationError(
                "Coralogix API key is missing. You must provide it via the 'api_key' parameter "
                "or set the 'CORALOGIX_API_KEY' environment variable."
            )

        if domain is None:
            env_region = os.environ.get("CORALOGIX_REGION")
            if env_region:
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
            self.provider.add_log_record_processor(
                BatchLogRecordProcessor(
                    exporter,
                    max_queue_size=2048,
                    max_export_batch_size=50,
                    schedule_delay_millis=flush_delay_ms
                )
            )

        self.logger = logging.getLogger(self.logger_name)
        self.logger.setLevel(self.log_level_int)

        has_otel_handler = any(isinstance(h, LoggingHandler) for h in self.logger.handlers)
        if not has_otel_handler:
            handler = LoggingHandler(level=self.log_level_int, logger_provider=self.provider)
            self.logger.addHandler(handler)

        atexit.register(self.flush)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self.flush()
        except Exception:
            pass

    def __str__(self) -> str:
        return f"<Coralogix Logger | App: {self.app_name} | Subsystem: {self.subsystem_name} | Level: {self.log_level_repr}>"

    def __repr__(self) -> str:
        return (
            f"CoralogixOTelLogger("
            f"app_name={self.app_name!r}, "
            f"subsystem_name={self.subsystem_name!r}, "
            f"logger_name={self.logger_name!r}, "
            f"api_key='***', "
            f"domain={self.domain!r}, "
            f"log_level={self.log_level_repr!r}, "
            f"cert_path={self.cert_path!r}"
            f")"
        )

    def _log(self, msg: str, payload: Dict[str, Any], level: Optional[str] = None) -> None:
        """
        Routes the clean plaintext message to native handlers, while attaching the
        dynamic structured payload to the OTel attribute pipeline via native `extra`.
        """
        emit_level = self._LEVEL_MAP.get(level.upper(), self.log_level_int) if level else self.log_level_int

        try:
            json.dumps(payload)
            self.logger.log(emit_level, msg, extra={"payload": payload})
        except TypeError as e:
            fallback_extra = {
                "payload": {
                    "event_type": "logger_serialization_error",
                    "error": str(e),
                    "app": self.app_name
                }
            }
            self.logger.error("Serialization Error", extra=fallback_extra)

    def _transform(self, level: str, msg: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """
        Validates structure to eliminate platform rendering ambiguity and routes to _log.
        """
        # UI Bridge: Seed the dictionary with the mandatory headline token 'message'
        # This prevents Coralogix's UI from making blind structural guesses
        safe_payload = {"message": msg}

        if payload is not None:
            if isinstance(payload, dict):
                safe_payload.update(payload)
            else:
                safe_payload.update({
                    "event_type": "logger_payload_type_error",
                    "logger_warning": f"Passed an invalid payload type ({type(payload).__name__}). Expected 'dict'.",
                    "rejected_raw_payload": str(payload)[:500]
                })
                level = "ERROR"

        self._log(msg, safe_payload, level=level)

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
        if hasattr(self, 'provider') and hasattr(self.provider, 'force_flush'):
            self.provider.force_flush()
