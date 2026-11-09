"""Layer 3 — the semantic judge (docs/JUDGE_PLAN.md). Needs the [judge] extra.

Takes the divergences layers 1 and 2 found, one part at a time, retrieves what the
3GPP spec and the OpenAPI reference say about THAT part (RAG), and asks the LLM why
it differs, whether it is an error or an improvement, and which version reads better.
It judges; it never measures — its verdicts are reported apart from the agreement.

spec_index.py  index a spec once per version (qdrant_3gpp_rag's cut); a section's clause
parts.py       cut the divergences of the layer 1/2 reports into parts
retrieval.py   aim the spec and OpenAPI-reference search at one part
"""
