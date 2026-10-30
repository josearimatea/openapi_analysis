"""The grouper's fixed OpenAPI knowledge is complete and consistently cited."""

import re

from openapi_analysis.judge.grouping_prompts import (
    GROUPING_SYSTEM,
    OPENAPI_IDENTITY_RULES,
)


def test_rule_ids_are_unique_and_in_order():
    ids = [rid for rid, _, _ in OPENAPI_IDENTITY_RULES]
    assert ids == [f"R{i}" for i in range(1, len(ids) + 1)]


def test_every_rule_cited_in_the_instructions_exists():
    ids = {rid for rid, _, _ in OPENAPI_IDENTITY_RULES}
    for prompt in (GROUPING_SYSTEM,):
        assert set(re.findall(r"\bR\d+\b", prompt)) <= ids
        assert all(f"[{rid}]" in prompt for rid in ids)      # every rule is given
