"""Pin the target enumeration so an instrument regression cannot pass silently.

The ad-hoc extractors this replaces mis-counted targets. These tests lock the
number and shape the counting spec produces for the ProvMnS YAML, so any future
change to that count is a deliberate edit to this file, never a quiet drift. See
targets.py for the counting specification (which mirrors the generator's contract).
"""

from pathlib import Path

import pytest
import yaml

from openapi_analysis.targets import targets_from_yaml, summarize

# The official YAML lives in the sibling generator repo; analysis only reads it.
YAML_PROVMNS = (
    Path(__file__).resolve().parents[2]
    / "openapi_rulesbank/data/inputs/yamls/rel18_TS28532_ProvMnS.yaml"
)


@pytest.fixture(scope="module")
def provmns_targets():
    if not YAML_PROVMNS.exists():
        pytest.skip(f"official YAML not found at {YAML_PROVMNS}")
    spec = yaml.safe_load(YAML_PROVMNS.read_text())
    return targets_from_yaml(spec)


def test_provmns_total_and_breakdown(provmns_targets):
    """Positional target count for ProvMnS rel18, pinned per rule_type.

    113 positional targets, addressed exactly as the generator addresses its rules
    (callbacks and per-operation request-body media types included).
    """
    assert summarize(provmns_targets) == {
        "path_parameter": 2,     # className, id (path level)
        "path_operation": 4,     # get, put, patch, delete
        "query_parameter": 5,    # scope, filter, attributes, fields, dataNodeSelector (get level)
        "request_body": 11,      # media types across put/patch and the callbacks
        "response": 21,          # per code across operations and callbacks
        "callback": 5,           # notifyMOICreation/Deletion/AttributeValueChanges/Event/MOIChanges
        "schema_property": 65,   # descending oneOf/allOf/properties/items
        "total": 113,
    }


def test_query_params_are_operation_level_not_path_level(provmns_targets):
    """The 5 GET query params must be addressed at the .get operation, not the path.

    This is the §3.22 discriminator: a bank rule that puts them at path level is a
    defect, and coverage can only catch it if the target itself is operation-level.
    """
    keys = {t.key() for t in provmns_targets}
    for name in ("scope", "filter", "attributes", "fields", "dataNodeSelector"):
        op_level = ("query_parameter", "paths./{className}={id}.get",
                    f"parameters[in=query,name={name}]", "")
        path_level = ("query_parameter", "paths./{className}={id}",
                      f"parameters[in=query,name={name}]", "")
        assert op_level in keys, f"{name} should be an operation-level target"
        assert path_level not in keys, f"{name} must NOT be a path-level target"


def test_path_level_params_stay_at_path(provmns_targets):
    """className and id apply to every method, so they belong to the path level."""
    keys = {t.key() for t in provmns_targets}
    for name in ("className", "id"):
        assert ("path_parameter", "paths./{className}={id}",
                f"parameters[in=path,name={name}]", "") in keys


def test_request_body_media_type_is_part_of_identity(provmns_targets):
    """The generator keeps field='content' and puts the media type in the value.

    So each media type is a distinct target; the value carries it. If the extractor
    dropped the value, the four PATCH media types would collapse into one target and
    the missing ones (§3.19) would be invisible.
    """
    rb = [t for t in provmns_targets if t.rule_type == "request_body"]
    assert all(t.openapi_field == "content" for t in rb)
    assert all(t.value for t in rb)  # every request_body target names a media type
    patch_media = {
        t.value for t in rb
        if t.openapi_object == "paths./{className}={id}.patch.requestBody"
    }
    assert "application/merge-patch+json" in patch_media
    assert "application/json-patch+json" in patch_media


def test_callbacks_are_enumerated(provmns_targets):
    """The 5 PUT callbacks are targets, addressed on the operation that hosts them."""
    cbs = {
        t.openapi_object for t in provmns_targets if t.rule_type == "callback"
    }
    for name in ("notifyMOICreation", "notifyMOIDeletion",
                 "notifyMOIAttributeValueChanges", "notifyEvent", "notifyMOIChanges"):
        assert f"paths./{{className}}={{id}}.put.callbacks.{name}" in cbs


def test_nested_oneof_schema_targets_are_found(provmns_targets):
    """Targets inside Resource's oneOf and other composed schemas must be present.

    Not descending into oneOf/allOf is the exact bug that reported 54 targets where
    there were more; these assertions guard that descent.
    """
    keys = {(t.openapi_object, t.openapi_field) for t in provmns_targets}
    for e in [
        ("components/schemas/Resource", "oneOf"),
        ("components/schemas/Resource", "anyOf"),
        ("components/schemas/Resource", "additionalProperties"),
        ("components/schemas/NotifyEvent", "required"),
        ("components/schemas/NotifyEvent", "allOf"),
        ("components/schemas/NotifyMoiCreation", "properties.additionalText"),
    ]:
        assert e in keys, f"missing nested target {e}"


def test_collection_keyword_is_one_target(provmns_targets):
    """A collection-valued keyword (enum/required/oneOf) is ONE target, never per-item.

    Mirrors §3.27: one rule per collection field. Per-item targets would break both
    coverage and the duplicate check.
    """
    for t in provmns_targets:
        if t.rule_type == "schema_property" and t.openapi_field in (
            "enum", "required", "oneOf", "anyOf", "allOf", "items",
            "additionalProperties",
        ):
            assert "." not in t.openapi_field
            assert "[" not in t.openapi_field


def test_no_external_ref_interiors_leak_in(provmns_targets):
    """No target addresses the inside of an imported type (Uri, ErrorResponse...).

    We stop at a $ref; the reference is the target, its interior is not ours to
    enumerate (§3.10). Every schema target's object must be a schema defined in THIS
    document.
    """
    spec = yaml.safe_load(YAML_PROVMNS.read_text())
    defined = {f"components/schemas/{n}" for n in spec["components"]["schemas"]}
    schema_objs = {
        t.openapi_object for t in provmns_targets
        if t.openapi_object.startswith("components/schemas/")
    }
    assert schema_objs <= defined
