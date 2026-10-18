"""Settings for layer 3, the semantic judge (docs/JUDGE_PLAN.md).

Kept apart from settings.py on purpose: this module loads the repo's .env (API keys)
on import, and only the judge imports it — the deterministic layers never read a key.
The values mirror openapi_rulesbank (same provider scheme, model, Qdrant collections
and chunk sizes; the embedding model comes from qdrant_3gpp_rag, as there), so the judge reads the corpus the way the
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
# The embedding model of the shared collections, from its single source. A query
# must use the model the collections were built with.
try:  # qdrant_3gpp_rag comes with the [judge] extra
    from qdrant_3gpp_rag.embedding_config import (
        DEFAULT_EMBEDDING_DIM as EMBEDDING_DIM,
        DEFAULT_EMBEDDING_MODEL as EMBEDDING_MODEL,
    )
except ImportError:  # pragma: no cover — without the extra there is no RAG to embed for
    EMBEDDING_MODEL, EMBEDDING_DIM = "", 0
EMBEDDING_DEVICE = "cpu"       # the [judge] extra installs CPU-only torch

# The OpenAPI 3.0.1 reference, a permanent collection built by openapi_rulesbank.
OPENAPI_COLLECTION = "openapi_reference"

# The main spec is read from the SHARED 3GPP corpus (qdrant_3gpp_rag), one collection
# per spec — decided 06/out: no collection of our own. That corpus indexes whole specs
# (annexes included) at one version, with no clause in the metadata; the retrieval cuts
# the annexes out itself (judge/spec_index.annex_cut) and reads the clause from the
# chunk's heading. Version: 28532-i00, while the banks judged come from i20.
SPEC_CORPUS = {"28532": "3gpp_rel18_28_28532"}

# The old per-version collection of our own (scripts/index_specs.py), no longer used.
SPEC_COLLECTION_PREFIX = "analysis_spec_"
SPEC_CHUNK_SIZE = 3000         # as openapi_rulesbank's spec RAG
SPEC_CHUNK_OVERLAP = 200
JUDGE_SPEC_CODES = ("i20",)

# A spec usually holds several services side by side; the judge reads only the
# evaluated service's clauses. That scope is not a table written for one spec: it is
# read from the bank itself — the two-level blocks ("11.1", "12.1") of the clauses its
# rules were extracted from (services/judge_service.scope_of_bank).

# Retrieval per part (judge/retrieval.py): 3 queries on the spec and 2 on the OpenAPI
# reference, each keeping its best PER_QUERY chunks. A spec query takes them, in
# scope, from the top SEARCH_POOL hits of an unfiltered search — the shared retriever
# filters on one exact value only, and a scope has several blocks.
PER_QUERY = 5
SEARCH_POOL = 50            # more hits dropped (annex, out of scope) in the corpus


def spec_collection(spec: str, code: str) -> str:
    """Collection of one spec version, e.g. ('28532', 'i20') → 'analysis_spec_28532_i20'."""
    return f"{SPEC_COLLECTION_PREFIX}{spec}_{code}"
