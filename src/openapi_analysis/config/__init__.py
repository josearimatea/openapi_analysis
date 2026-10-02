"""Lightweight config entry point — paths, settings and logging.

Mirrors the sibling repos (openapi_rulesbank/config, openapi_generator/config):
    from openapi_analysis.config import get_logger
    from openapi_analysis.config.paths import REFERENCE_DIR, reference_yaml
    from openapi_analysis.config.settings import SERVICES
"""

_logging_configured = False


def get_logger(name: str):
    """Configure logging once (on first call) and return a named logger.

    Logging is configured lazily so that importing this package as a LIBRARY (from
    the generator repos or the chat UI) never touches the host's logging setup
    until a logger is actually requested.
    """
    global _logging_configured
    if not _logging_configured:
        from . import logging_config  # noqa: F401 — configures the package logger
        _logging_configured = True

    import logging
    return logging.getLogger(name)


__all__ = ["get_logger"]
