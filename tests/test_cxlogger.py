import os
import json
import pytest
import logging
from unittest.mock import patch, MagicMock

from cxlogger import CoralogixOTelLogger
from cxlogger.exceptions import CoralogixConfigurationError

@pytest.fixture(autouse=True)
def mock_otel_infrastructure():
    with patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
         patch('cxlogger.cxlogger.BatchLogRecordProcessor') as mock_processor, \
         patch('cxlogger.cxlogger.Resource.create') as mock_resource:

        yield {
            "exporter": mock_exporter,
            "processor": mock_processor,
            "resource": mock_resource
        }

@pytest.fixture
def clean_env():
    with patch.dict(os.environ, {}, clear=True):
        yield

class TestCoralogixOTelLogger:
    # ==========================================
    # 1. INITIALIZATION & CONFIGURATION TESTS
    # ==========================================
    def test_init_fails_when_both_keys_missing(self, clean_env):
        with pytest.raises(CoralogixConfigurationError, match="Coralogix API key is missing"):
            CoralogixOTelLogger(app_name="app", subsystem_name="sub")

    def test_init_succeeds_with_constructor_arg_only(self, clean_env):
        try:
            logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub", api_key="explicit-key-123")
        except CoralogixConfigurationError:
            pytest.fail("Logger crashed even though 'api_key' was passed to the constructor!")

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key-456"})
    def test_init_succeeds_with_env_var_only(self):
        try:
            logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        except CoralogixConfigurationError:
            pytest.fail("Logger crashed even though 'CORALOGIX_API_KEY' env var was present!")

    def test_init_with_explicit_args(self, clean_env):
        logger = CoralogixOTelLogger(
            app_name="test-app",
            subsystem_name="test-sub",
            logger_name="my_custom_logger",
            api_key="explicit-key",
            domain="custom.coralogix.com",
            log_level="debug",
            flush_delay_ms=5000
        )
        assert logger.domain == "custom.coralogix.com"
        assert logger.log_level_int == logging.DEBUG
        assert logger.logger_name == "my_custom_logger"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key", "CORALOGIX_REGION": "eu2"})
    def test_init_with_env_vars(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        assert logger.domain == "eu2.coralogix.com"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_init_default_region(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        assert logger.domain == "us1.coralogix.com"

    # ==========================================
    # 2. HANDLER ADDITIVITY & ROUTING TESTS
    # ==========================================
    @patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=MagicMock())
    def test_flush_delay_parameter_routing(self, mock_get_provider, mock_otel_infrastructure, clean_env):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub", api_key="test-key", flush_delay_ms=200)
        mock_processor = mock_otel_infrastructure["processor"]
        mock_processor.assert_called_once()
        _, kwargs = mock_processor.call_args
        assert kwargs.get("schedule_delay_millis") == 200
        assert kwargs.get("max_export_batch_size") == 50
        assert kwargs.get("max_queue_size") == 2048

    def test_additive_logger_behavior(self, clean_env):
        """Ensures the wrapper seamlessly adopts existing logger handlers without destroying them."""
        from opentelemetry.sdk._logs import LoggingHandler

        # Mock an application that already configured a standard terminal logger
        native_logger = logging.getLogger("company.main.logger")
        stream_handler = logging.StreamHandler()
        native_logger.addHandler(stream_handler)

        logger = CoralogixOTelLogger(
            app_name="app",
            subsystem_name="sub",
            api_key="test-key",
            logger_name="company.main.logger"
        )

        assert len(native_logger.handlers) == 2
        assert stream_handler in native_logger.handlers
        assert any(isinstance(h, LoggingHandler) for h in native_logger.handlers)

        # Cleanup global registry for next tests
        native_logger.handlers.clear()

    def test_reuses_existing_logger_provider(self, clean_env):
        from opentelemetry.sdk._logs import LoggerProvider

        mock_existing_provider = MagicMock(spec=LoggerProvider)

        with patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=mock_existing_provider), \
             patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
             patch('cxlogger.cxlogger.Resource.create') as mock_resource:

            logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub", api_key="explicit-key")

            assert logger.provider is mock_existing_provider
            mock_resource.assert_not_called()
            mock_exporter.assert_not_called()

    # ==========================================
    # 3. STRING REPRESENTATION TESTS
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_str_and_repr(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub", log_level="warning")
        assert str(logger) == "<Coralogix Logger | App: app | Subsystem: sub | Level: WARNING>"
        repr_str = repr(logger)
        assert "app_name='app'" in repr_str
        assert "api_key='***'" in repr_str

    # ==========================================
    # 4. PAYLOAD TRANSFORMATION & SAFETY TESTS
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_valid_payload_transformation(self):
        """Test that the extra parameter routes perfectly and the base msg stays clean."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            logger.info("Test message", payload={"user": "john.doe"})

            args, kwargs = mock_log.call_args
            assert args[0] == logging.INFO
            assert args[1] == "Test message"
            assert kwargs["extra"]["payload"]["user"] == "john.doe"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_invalid_payload_type_defense(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            logger.info("Test message", payload=["invalid", "list"])

            args, kwargs = mock_log.call_args
            assert args[0] == logging.ERROR
            assert args[1] == "Test message"
            assert kwargs["extra"]["payload"]["event_type"] == "logger_payload_type_error"
            assert "Passed an invalid payload type (list)" in kwargs["extra"]["payload"]["logger_warning"]

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_unserializable_json_defense(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'error') as mock_error:
            bad_payload = {"bad_key": set([1, 2, 3])}
            logger.info("Test message", payload=bad_payload)

            args, kwargs = mock_error.call_args
            assert args[0] == "Serialization Error"
            assert kwargs["extra"]["payload"]["event_type"] == "logger_serialization_error"
            assert "is not JSON serializable" in kwargs["extra"]["payload"]["error"]

    # ==========================================
    # 5. LOGGING METHOD ROUTING TESTS
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    @pytest.mark.parametrize("method_name, expected_level", [
        ("debug", logging.DEBUG),
        ("info", logging.INFO),
        ("warning", logging.WARNING),
        ("error", logging.ERROR),
        ("critical", logging.CRITICAL),
    ])
    def test_log_level_routing(self, method_name, expected_level):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            log_method = getattr(logger, method_name)
            log_method("Test route")

            args, _ = mock_log.call_args
            assert args[0] == expected_level

    # ==========================================
    # 6. FLUSH & CONTEXT MECHANISM TESTS
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_force_flush(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        logger.provider.force_flush = MagicMock()
        logger.flush()
        logger.provider.force_flush.assert_called_once()

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_context_manager_normal_execution(self):
        with patch.object(CoralogixOTelLogger, 'flush') as mock_flush:
            with CoralogixOTelLogger(app_name="app", subsystem_name="sub") as logger:
                assert isinstance(logger, CoralogixOTelLogger)
                mock_flush.assert_not_called()
            mock_flush.assert_called_once()

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_context_manager_exception_propagation(self):
        with patch.object(CoralogixOTelLogger, 'flush') as mock_flush:
            with pytest.raises(ValueError, match="App crashed!"):
                with CoralogixOTelLogger(app_name="app", subsystem_name="sub"):
                    raise ValueError("App crashed!")
            mock_flush.assert_called_once()
