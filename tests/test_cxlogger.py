import os
import json
import pytest
import logging
from unittest.mock import patch, MagicMock

# Assuming your class is in a file named cxlogger.py
from cxlogger import CoralogixOTelLogger

@pytest.fixture(autouse=True)
def mock_otel_infrastructure():
    """
    Automatically mocks the OTel Exporter and Batch Processor for all tests.
    This prevents the tests from spinning up background threads or trying
    to send real gRPC network requests to Coralogix during CI/CD.
    """
    with patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
         patch('cxlogger.cxlogger.BatchLogRecordProcessor') as mock_processor, \
         patch('cxlogger.cxlogger.Resource.create') as mock_resource:
        yield

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
        with pytest.raises(ValueError, match="Coralogix API key is missing"):
            # Environment is wiped, and we pass no explicit key
            CoralogixOTelLogger(app_name="app", subsystem_name="sub")

    def test_init_succeeds_with_constructor_arg_only(self, clean_env):
        """SUCCESS: No environment variable, but key passed directly to constructor."""
        try:
            # Environment is wiped, but we provide the explicit argument
            logger = CoralogixOTelLogger(
                app_name="app",
                subsystem_name="sub",
                api_key="explicit-key-123"
            )
        except ValueError:
            pytest.fail("Logger crashed even though 'api_key' was passed to the constructor!")

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key-456"})
    def test_init_succeeds_with_env_var_only(self):
        """SUCCESS: No constructor argument, but environment variable is present."""
        try:
            # We don't pass an explicit key, but the OS environment has one
            logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        except ValueError:
            pytest.fail("Logger crashed even though 'CORALOGIX_API_KEY' env var was present!")

    def test_init_with_explicit_args(self, clean_env):
        """Test initialization with explicit arguments instead of env vars."""
        logger = CoralogixOTelLogger(
            app_name="test-app",
            subsystem_name="test-sub",
            api_key="explicit-key",
            domain="custom.coralogix.com",
            log_level="debug"
        )
        assert logger.domain == "custom.coralogix.com"
        assert logger.log_level_int == logging.DEBUG
        assert logger.logger_name == "cx_test-app_test-sub"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key", "CORALOGIX_REGION": "eu2"})
    def test_init_with_env_vars(self):
        """Test that the logger correctly consumes environment variables."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        # Should automatically resolve to eu2.coralogix.com
        assert logger.domain == "eu2.coralogix.com"

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_init_default_region(self):
        """Test fallback to us1 if region is not specified."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")
        assert logger.domain == "us1.coralogix.com"

    #====================================
    # 2. Singleton LoggerProvider Reuse Test and Handler Deduplication
    #=====================================
    def test_reuses_existing_logger_provider(self, clean_env):
        """
        Ensure that if an OTel LoggerProvider is already active in the global registry,
        the class reuses it instead of spinning up duplicate gRPC exporters.
        """
        from opentelemetry.sdk._logs import LoggerProvider

        # Create a fake provider that looks like a real one
        mock_existing_provider = MagicMock(spec=LoggerProvider)

        # Force the global registry to return our fake provider
        with patch('cxlogger.cxlogger.otel_logs.get_logger_provider', return_value=mock_existing_provider), \
             patch('cxlogger.cxlogger.OTLPLogExporter') as mock_exporter, \
             patch('cxlogger.cxlogger.Resource.create') as mock_resource:

            logger = CoralogixOTelLogger(
                app_name="app",
                subsystem_name="sub",
                api_key="explicit-key"
            )

            # 1. It should have grabbed the exact provider from the registry
            assert logger.provider is mock_existing_provider

            # 2. It should have completely skipped creating a new Resource
            mock_resource.assert_not_called()

            # 3. It should have completely skipped creating a duplicate Exporter network connection
            mock_exporter.assert_not_called()

    def test_prevents_duplicate_handlers(self, clean_env):
        """
        Ensure that multiple instantiations of the same logger name
        do not attach duplicate OTel handlers (preventing log amplification).
        """
        from opentelemetry.sdk._logs import LoggingHandler
        import logging

        with patch('cxlogger.cxlogger.OTLPLogExporter'), patch('cxlogger.cxlogger.Resource.create'):
            # First instantiation (e.g., in main.py)
            logger1 = CoralogixOTelLogger(
                app_name="duplicate-test",
                subsystem_name="module",
                api_key="test-key"
            )

            # Second instantiation of the exact same subsystem (e.g., in utils.py)
            logger2 = CoralogixOTelLogger(
                app_name="duplicate-test",
                subsystem_name="module",
                api_key="test-key"
            )

            # 1. Prove they both grabbed the same underlying Python logger from the registry
            assert logger1.logger is logger2.logger

            # 2. THE CRITICAL CHECK: It should only have exactly ONE handler attached, not two!
            assert len(logger1.logger.handlers) == 1

            # 3. Ensure that the single attached handler is actually the OTel bridge
            assert isinstance(logger1.logger.handlers[0], LoggingHandler)

            # Cleanup the global logging registry so this test doesn't pollute other tests
            logger1.logger.handlers.clear()

    # ==========================================
    # 2. STRING REPRESENTATION TESTS
    # ==========================================

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_str_and_repr(self):
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub", log_level="warning")

        assert str(logger) == "<Coralogix Logger | App: app | Subsystem: sub | Level: WARNING>"

        repr_str = repr(logger)
        assert "app_name='app'" in repr_str
        assert "api_key='***'" in repr_str # Ensure API key is masked in repr!

    # ==========================================
    # 3. PAYLOAD TRANSFORMATION & SAFETY TESTS
    # ==========================================

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_valid_payload_transformation(self):
        """Test that a valid dictionary is properly merged with the message."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        # Mock the underlying standard logger to intercept what _log attempts to write
        with patch.object(logger.logger, 'log') as mock_log:
            logger.info("Test message", payload={"user": "john.doe"})

            # Extract the stringified JSON passed to the standard logger
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
            # Pass a list (invalid) instead of a dictionary
            logger.info("Test message", payload=["invalid", "list"])

            args, _ = mock_log.call_args
            emitted_level, emitted_json_str = args

            # The level should be automatically elevated to ERROR
            assert emitted_level == logging.ERROR
            emitted_dict = json.loads(emitted_json_str)

            # Ensure the fallback schema was applied
            assert emitted_dict["message"] == "Test message"
            assert emitted_dict["event_type"] == "logger_payload_type_error"
            assert "Passed an invalid payload type (list)" in emitted_dict["logger_warning"]

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_unserializable_json_defense(self):
        """Test the defense mechanism when a dict contains non-JSON-serializable objects."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        with patch.object(logger.logger, 'error') as mock_error:
            # Sets are not JSON serializable!
            bad_payload = {"bad_key": set([1, 2, 3])}
            logger.info("Test message", payload=bad_payload)

            args, _ = mock_error.call_args
            emitted_json_str = args[0]

            emitted_dict = json.loads(emitted_json_str)
            assert emitted_dict["event_type"] == "logger_serialization_error"
            assert emitted_dict["app"] == "app"
            assert "is not JSON serializable" in emitted_dict["error"]

    # ==========================================
    # 4. LOGGING METHOD ROUTING TESTS
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
            # Dynamically call logger.debug(), logger.info(), etc.
            log_method = getattr(logger, method_name)
            log_method("Test route")

            args, _ = mock_log.call_args
            assert args[0] == expected_level

    # ==========================================
    # 5. FLUSH MECHANISM TEST
    # ==========================================

    @patch.dict(os.environ, {"CORALOGIX_API_KEY": "env-key"})
    def test_force_flush(self):
        """Test that the flush method successfully calls the OTel provider."""
        logger = CoralogixOTelLogger(app_name="app", subsystem_name="sub")

        # Mock the provider's force_flush method
        logger.provider.force_flush = MagicMock()

        logger.flush()
        logger.provider.force_flush.assert_called_once()
