import os
import json
import pytest
import logging
from unittest.mock import patch, MagicMock

# Assuming your class is in a file named cxlogger.py
from cxlogger import CoralogixOTelLogger
from cxlogger.exceptions import CoralogixConfigurationError

@pytest.fixture(autouse=True)
def mock_otel_infrastructure():
    """
    Automatically mocks the OTel Exporter and Batch Processor for all tests.
    Yields the mocks as a dictionary so specific tests can assert against them.
    """
    with patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
         patch('cxlogger.cxlogger.BatchLogRecordProcessor') as mock_processor, \
         patch('cxlogger.cxlogger.Resource.create') as mock_resource:

        # We yield the mocks so tests can verify how they were called
        yield {
            "exporter": mock_exporter,
            "processor": mock_processor,
            "resource": mock_resource
        }

@pytest.fixture
def clean_env():
    """Ensures environment variables are clean before testing."""
    with patch.dict(os.environ, {}, clear=True):
        yield

class TestCoralogixOTelLogger:
    # ==========================================
    # 1. INITIALIZATION & CONFIGURATION TESTS
    # ==========================================
    def test_init_fails_when_both_keys_missing(self, clean_env):
        """CRASH: No environment variable AND no constructor argument."""
        with pytest.raises(CoralogixConfigurationError, match="Coralogix API key is missing"):
            CoralogixOTelLogger(app_name="app", subsystem_name="sub")

    def test_init_succeeds_with_constructor_arg_only(self, clean_env):
        """SUCCESS: No environment variable, but key passed directly to constructor."""
        try:
            logger = CoralogixOTelLogger(
                app_name="app",
                subsystem_name="sub",
                api_key="explicit-key-123"
            )
        except CoralogixConfigurationError:
            pytest.fail("Logger crashed even though 'api_key' was passed to the constructor!")

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key-456"})
    def test_init_succeeds_with_env_var_only(self):
        """SUCCESS: No constructor argument, but environment variable is present."""
        try:
            logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        except CoralogixConfigurationError:
            pytest.fail("Logger crashed even though 'CORALOGIX_API_KEY' env var was present!")

    def test_init_with_explicit_args(self, clean_env):
        """Test initialization with explicit arguments instead of env vars."""
        logger = CoralogixOTelLogger(
            app_name="test-app",
            subsystem_name="test-sub",
            api_key="explicit-key",
            domain="custom.coralogix.com",
            log_level="debug",
            flush_delay_ms=5000
        )
        assert logger.domain == "custom.coralogix.com"
        assert logger.log_level_int == logging.DEBUG
        assert logger.logger_name == "cx_test-app_test-sub"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key", "CORALOGIX_REGION": "eu2"})
    def test_init_with_env_vars(self):
        """Test that the logger correctly consumes environment variables."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        assert logger.domain == "eu2.coralogix.com"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_init_default_region(self):
        """Test fallback to us1 if region is not specified."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        assert logger.domain == "us1.coralogix.com"

    # ==========================================
    # 1.5 PROCESSOR ROUTING TESTS (NEW)
    # ==========================================
    # We mock get_logger_provider to simulate a "fresh" start so it doesn't skip initialization
    @patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=MagicMock())
    def test_flush_delay_parameter_routing(self, mock_get_provider, mock_otel_infrastructure, clean_env):
        """Ensure flush_delay_ms and hardcoded safety boundaries are passed to the OTel Processor."""
        logger = CoralogixOTelLogger(
            app_name="app",
            subsystem_name="sub",
            api_key="test-key",
            flush_delay_ms=200 # Pass a custom explicit delay
        )

        mock_processor = mock_otel_infrastructure["processor"]

        # Ensure the processor was instantiated
        mock_processor.assert_called_once()

        # Inspect the arguments passed to BatchLogRecordProcessor
        _, kwargs = mock_processor.call_args

        # Verify the dynamic parameter
        assert kwargs.get("schedule_delay_millis") == 200

        # Verify our hardcoded structural safety boundaries
        assert kwargs.get("max_export_batch_size") == 50
        assert kwargs.get("max_queue_size") == 2048

    @patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=MagicMock())
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_default_flush_delay_routing(self, mock_get_provider, mock_otel_infrastructure):
        """Ensure the default flush delay is exactly 5000ms if omitted."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        mock_processor = mock_otel_infrastructure["processor"]
        _, kwargs = mock_processor.call_args

        assert kwargs.get("schedule_delay_millis") == 5000

    # ==========================================
    # 2. Singleton LoggerProvider Reuse Test and Handler Deduplication
    # ==========================================
    def test_reuses_existing_logger_provider(self, clean_env):
        """
        Ensure that if an OTel LoggerProvider is already active in the global registry,
        the class reuses it instead of spinning up duplicate gRPC exporters.
        """
        from opentelemetry.sdk._logs import LoggerProvider

        mock_existing_provider = MagicMock(spec=LoggerProvider)

        with patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=mock_existing_provider), \
             patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
             patch('cxlogger.cxlogger.Resource.create') as mock_resource:

            logger = CoralogixOTelLogger(
                app_name="app",
                subsystem_name="sub",
                api_key="explicit-key"
            )

            assert logger.provider is mock_existing_provider
            mock_resource.assert_not_called()
            mock_exporter.assert_not_called()

    def test_prevents_duplicate_handlers(self, clean_env):
        """
        Ensure that multiple instantiations of the same logger name
        do not attach duplicate OTel handlers (preventing log amplification).
        """
        from opentelemetry.sdk._logs import LoggingHandler
        import logging

        with patch('cxlogger.cxlogger.OTLPLogExporter'), patch('cxlogger.cxlogger.Resource.create'):
            logger1 = CoralogixOTelLogger(
                app_name="duplicate-test",
                subsystem_name="module",
                api_key="test-key"
            )

            logger2 = CoralogixOTelLogger(
                app_name="duplicate-test",
                subsystem_name="module",
                api_key="test-key"
            )

            assert logger1.logger is logger2.logger
            assert len(logger1.logger.handlers) == 1
            assert isinstance(logger1.logger.handlers[0], LoggingHandler)

            logger1.logger.handlers.clear()

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
        """Test that a valid dictionary is properly merged with the message."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            logger.info("Test message", payload={"user": "john.doe"})

            args, _ = mock_log.call_args
            emitted_level, emitted_json_str = args

            assert emitted_level == logging.INFO
            emitted_dict = json.loads(emitted_json_str)
            assert emitted_dict["message"] == "Test message"
            assert emitted_dict["user"] == "john.doe"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_invalid_payload_type_defense(self):
        """Test the defense mechanism when a user passes a list instead of a dict."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            logger.info("Test message", payload=["invalid", "list"])

            args, _ = mock_log.call_args
            emitted_level, emitted_json_str = args

            assert emitted_level == logging.ERROR
            emitted_dict = json.loads(emitted_json_str)

            assert emitted_dict["message"] == "Test message"
            assert emitted_dict["event_type"] == "logger_payload_type_error"
            assert "Passed an invalid payload type (list)" in emitted_dict["logger_warning"]

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_unserializable_json_defense(self):
        """Test the defense mechanism when a dict contains non-JSON-serializable objects."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'error') as mock_error:
            bad_payload = {"bad_key": set([1, 2, 3])}
            logger.info("Test message", payload=bad_payload)

            args, _ = mock_error.call_args
            emitted_json_str = args[0]

            emitted_dict = json.loads(emitted_json_str)
            assert emitted_dict["event_type"] == "logger_serialization_error"
            assert emitted_dict["app"] == "app"
            assert "is not JSON serializable" in emitted_dict["error"]

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
        """Ensure debug(), info(), etc., map to the correct internal logging integer."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'log') as mock_log:
            log_method = getattr(logger, method_name)
            log_method("Test route")

            args, _ = mock_log.call_args
            assert args[0] == expected_level

    # ==========================================
    # 6. FLUSH MECHANISM TEST
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_force_flush(self):
        """Test that the flush method successfully calls the OTel provider."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        logger.provider.force_flush = MagicMock()

        logger.flush()
        logger.provider.force_flush.assert_called_once()

    # ==========================================
    # 7. CONTEXT MANAGER TESTS
    # ==========================================
    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_context_manager_normal_execution(self):
        """Test that the 'with' block returns the logger and flushes on exit."""
        with patch.object(CoralogixOTelLogger, 'flush') as mock_flush:
            with CoralogixOTelLogger(app_name="app", subsystem_name="sub") as logger:
                assert isinstance(logger, CoralogixOTelLogger)
                # It should NOT flush while still inside the block
                mock_flush.assert_not_called()

            # The exact moment we exit the block, it should have flushed automatically
            mock_flush.assert_called_once()

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_context_manager_exception_propagation(self):
        """Ensure the context manager does NOT swallow application-level exceptions."""
        with patch.object(CoralogixOTelLogger, 'flush') as mock_flush:
            # We expect the ValueError to bubble up through the context manager
            with pytest.raises(ValueError, match="App crashed!"):
                with CoralogixOTelLogger(app_name="app", subsystem_name="sub"):
                    raise ValueError("App crashed!")

            # Crucially: Even if the app crashes, __exit__ should STILL attempt to
            # flush the logs so we capture the error before the container dies!
            mock_flush.assert_called_once()

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_context_manager_swallows_flush_errors(self):
        """Ensure that if the telemetry flush itself fails, it doesn't crash the main app."""
        # Force the flush method to simulate a hard network failure
        with patch.object(CoralogixOTelLogger, 'flush', side_effect=Exception("Network down!")):
            try:
                with CoralogixOTelLogger(app_name="app", subsystem_name="sub"):
                    pass # App does some normal work successfully
            except Exception:
                pytest.fail("The context manager allowed a background flush exception to crash the application!")

