"""Settings for layer 3, the semantic judge (docs/JUDGE_PLAN.md).

Kept apart from settings.py on purpose: this module loads the repo's .env (API keys)
on import, and only the judge imports it — the deterministic layers never read a key.
The values mirror openapi_rulesbank (same provider scheme, model, Qdrant collections,
embedding model and chunk sizes), so the judge reads the corpus the way the
generators were given it.
"""

import os

from openapi_analysis.config.paths import ROOT

try:  # python-dotenv comes with the [judge] extra
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover — without the extra, rely on the real environment
    load_dotenv = None
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")

# ── LLM ──────────────────────────────────────────────────────────────────────
# OpenRouter needs the vendor prefix, OpenAI the bare name, so the default model
# follows the provider (as in openapi_rulesbank); JUDGE_MODEL overrides it.
PROVIDER = os.getenv("JUDGE_PROVIDER", "openrouter").strip().lower()
DEFAULT_MODEL_BY_PROVIDER = {
    "openrouter": "openai/gpt-5.6-luna",
    "openai": "gpt-5.6-luna",
}
MODEL = os.getenv("JUDGE_MODEL") or DEFAULT_MODEL_BY_PROVIDER.get(PROVIDER, "gpt-5.6-luna")
TEMPERATURE = float(os.getenv("JUDGE_TEMPERATURE", "0"))
# "none" OMITS the reasoning parameter (the model reasons as it does by default) —
# openapi_rulesbank measured that sending a disable flag answers worse.
REASONING_EFFORT = os.getenv("JUDGE_REASONING_EFFORT", "none").strip().lower()
LLM_REQUEST_TIMEOUT = 120      # seconds; a hung call fails fast and is retried
LLM_MAX_RETRIES = 2

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "openapi-analysis")

# ── Qdrant / RAG ─────────────────────────────────────────────────────────────
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
EMBEDDING_DEVICE = "cpu"       # the [judge] extra installs CPU-only torch

# Permanent collections, built by the sibling repos.
OPENAPI_COLLECTION = "openapi_reference"                    # OpenAPI 3.0.1 reference
GPP_CORPUS_COLLECTIONS = ("3gpp_rel18_all", "3gpp_rel18_28")  # first one present wins

# The main spec of each evaluated input, indexed once per version by
# scripts/index_specs.py into a collection of its own (fixed, not per run).
SPEC_COLLECTION_PREFIX = "analysis_spec_"
# Spec versions the judge works on (the i00 banks are left out of it for now).
JUDGE_SPEC_CODES = ("i20",)
SPEC_CHUNK_SIZE = 3000         # as openapi_rulesbank's spec RAG
SPEC_CHUNK_OVERLAP = 200

# Chunks retrieved per part, per source.
SPEC_RETRIEVE_CHUNKS = 4
CORPUS_RETRIEVE_CHUNKS = 3
OPENAPI_RETRIEVE_CHUNKS = 4


def spec_collection(spec: str, code: str) -> str:
    """Collection of one spec version, e.g. ('28532', 'i20') → 'analysis_spec_28532_i20'."""
    return f"{SPEC_COLLECTION_PREFIX}{spec}_{code}"
