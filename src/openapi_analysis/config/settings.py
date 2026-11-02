"""Settings for the analysis — no side effects on import, stdlib only.

Environment variables (all optional):
    OPENAPI_ANALYSIS_DATA_DIR   where data/ lives (default: <repo>/data). Set it when
                                the package is installed as a dependency of another
                                repo and the data folder is not next to the code.
    OPENAPI_ANALYSIS_LOG_LEVEL  logging level (default INFO).
"""

import os

LOG_LEVEL = os.environ.get("OPENAPI_ANALYSIS_LOG_LEVEL", "INFO").upper()

# The 3GPP TS 28.532 management services this workspace works with. The folder
# names under data/reference/ and data/rulesbank/ use exactly these names.
SERVICES = (
    "ProvMnS",
    "PerfMnS",
    "FaultMnS",
    "FileDataReportingMnS",
    "HeartbeatNtf",
    "StreamingDataMnS",
)
DEFAULT_SERVICE = "ProvMnS"

# The 3GPP spec version a bank was extracted from, as coded in its filename
# (rules_bank_28532-<code>_...) → the TS 28.532 document version.
SPEC_VERSIONS = {
    "i00": "18.0.0",
    "i20": "18.2.0",
}

# The official YAML (its info.version) of each service in each spec version, as the
# annex of that spec holds it: an input is only ever evaluated against the official of
# the spec version it came from — i00 with i00, i20 with i20.
OFFICIAL_BY_SPEC = {
    "i00": {"ProvMnS": "17.5.0", "PerfMnS": "17.1.0"},
    "i20": {"ProvMnS": "18.2.0", "PerfMnS": "18.1.0"},
}

# Version of the JSON shape of every report this package emits. Bump it when a
# field is renamed or removed, so callers (generator repos, chat UI) can tell.
REPORT_SCHEMA_VERSION = 1
