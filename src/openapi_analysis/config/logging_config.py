"""Logging for the openapi_analysis package.

Only the package's own logger is configured (not the root logger), so a host
application that imports this library keeps full control of its own logging.
Level from the OPENAPI_ANALYSIS_LOG_LEVEL environment variable (default INFO).
"""

import logging

from openapi_analysis.config.settings import LOG_LEVEL

_logger = logging.getLogger("openapi_analysis")
_logger.setLevel(LOG_LEVEL)

if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    _logger.addHandler(_handler)
