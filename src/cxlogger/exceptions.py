# src/cxlogger/exceptions.py

class CoralogixLoggerError(Exception):
    """Base exception for all Coralogix logger errors."""
    pass

class CoralogixConfigurationError(CoralogixLoggerError):
    """Raised when the logger is initialized with missing or invalid credentials."""
    pass
