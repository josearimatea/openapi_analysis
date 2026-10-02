"""Pin the extraction of official rules so an instrument regression cannot pass silently.

The ad-hoc extractors this replaces mis-counted targets. These tests lock the
number, shape and values the extraction produces, so any change to a count is a
deliberate edit to this file, never a quiet drift. See rulesbank/extraction.py.
"""

import pytest
import yaml

from openapi_analysis.config.paths import reference_yaml
from openapi_analysis.rulesbank.extraction import rules_from_yaml, summarize
from openapi_analysis.rulesbank.rule_types import rule_key

# Versioned in data/inputs — a missing file is a failure, never a skip.
YAML_PROVMNS = reference_yaml("ProvMnS", "18.2.0")


def _load(service, version):
    return yaml.safe_load(reference_yaml(service, version).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def provmns():
    return rules_from_yaml(_load("ProvMnS", "18.2.0"))


def _by_key(rules):
    return {rule_key(r): r for r in rules}


def _value(rules, rule_type, obj, field):
    for r in rules:
        m = r["openapi_mapping"]
        if (r["rule_type"], m["openapi_object"], m["openapi_field"]) == (rule_type, obj, field):
            return m
    raise AssertionError(f"no rule {rule_type} {obj} {field}")


def test_provmns_total_and_breakdown(provmns):
    """Official rule count for ProvMnS rel18, pinned per rule_type."""
    assert summarize(provmns) == {
        "path_parameter": 2,     # className, id (path level)
        "path_operation": 4,     # get, put, patch, delete
        "query_parameter": 5,    # scope, filter, attributes, fields, dataNodeSelector (get)
        "request_body": 11,      # media types across put/patch and the callbacks
        "response": 21,          # per code across operations and callbacks
        "callback": 5,           # notifyMOICreation/Deletion/AttributeValueChanges/Event/MOIChanges
        "schema_property": 65,   # descending oneOf/allOf/properties/items
        "total": 113,
    }


@pytest.mark.parametrize("service, version, total", [
    ("ProvMnS", "17.5.0", 103),
    ("ProvMnS", "17.7.0", 112),
    ("ProvMnS", "18.2.0", 113),
    ("PerfMnS", "17.1.0", 15),
    ("PerfMnS", "18.1.0", 15),
    ("FaultMnS", "17.2.0", 260),
    ("FileDataReportingMnS", "17.1.0", 40),
    ("HeartbeatNtf", "17.1.0", 3),
    ("StreamingDataMnS", "17.1.0", 74),
])
def test_every_official_yaml_total(service, version, total):
    assert summarize(rules_from_yaml(_load(service, version)))["total"] == total


def test_rules_are_in_the_rules_bank_format(provmns):
    for r in provmns:
        assert set(r) == {"rule_type", "openapi_mapping"}
        assert set(r["openapi_mapping"]) == {"openapi_object", "openapi_field",
                                             "openapi_value", "references"}


def test_query_params_are_operation_level_not_path_level(provmns):
    """The 5 GET query params are addressed at the .get operation (§3.22)."""
    keys = set(_by_key(provmns))
    for name in ("scope", "filter", "attributes", "fields", "dataNodeSelector"):
        field = f"parameters[in=query,name={name}]"
        assert ("query_parameter", "paths./{className}={id}.get", field, "") in keys
        assert ("query_parameter", "paths./{className}={id}", field, "") not in keys


def test_path_level_params_stay_at_path(provmns):
    keys = set(_by_key(provmns))
    for name in ("className", "id"):
        assert ("path_parameter", "paths./{className}={id}",
                f"parameters[in=path,name={name}]", "") in keys


def test_header_parameters_are_not_rules():
    """in: header has no rule_type — it must not turn into a query_parameter."""
    rules = rules_from_yaml(_load("StreamingDataMnS", "17.1.0"))
    fields = {r["openapi_mapping"]["openapi_field"] for r in rules}
    assert not any("in=header" in f for f in fields)
    assert "parameters[in=query,name=Connection]" not in fields


def test_request_body_media_type_is_part_of_identity(provmns):
    rb = [r for r in provmns if r["rule_type"] == "request_body"]
    assert all(r["openapi_mapping"]["openapi_field"] == "content" for r in rb)
    patch_media = {r["openapi_mapping"]["openapi_value"] for r in rb
                   if r["openapi_mapping"]["openapi_object"]
                   == "paths./{className}={id}.patch.requestBody"}
    assert {"application/merge-patch+json", "application/json-patch+json"} <= patch_media


def test_callbacks_are_anchored_on_the_registering_operation(provmns):
    cbs = [r for r in provmns if r["rule_type"] == "callback"]
    for name in ("notifyMOICreation", "notifyMOIDeletion", "notifyMOIAttributeValueChanges",
                 "notifyEvent", "notifyMOIChanges"):
        m = _value(cbs, "callback", f"paths./{{className}}={{id}}.put.callbacks.{name}", "post")
        assert m["openapi_value"] == "{request.body#/notificationRecipientAddress}"


def test_nested_composition_is_descended(provmns):
    """Not descending into oneOf/allOf is the bug that once counted 54 targets."""
    keys = {(r["openapi_mapping"]["openapi_object"], r["openapi_mapping"]["openapi_field"])
            for r in provmns}
    for e in [
        ("components/schemas/Resource", "oneOf"),
        ("components/schemas/Resource", "anyOf"),
        ("components/schemas/Resource", "additionalProperties"),
        ("components/schemas/NotifyEvent", "required"),
        ("components/schemas/NotifyEvent", "allOf"),
        ("components/schemas/NotifyMoiCreation", "properties.additionalText"),
    ]:
        assert e in keys, f"missing nested rule {e}"


def test_values_follow_the_bank_formats(provmns):
    """Values are written the way the rules-bank extractor prompt asks for them."""
    assert _value(provmns, "path_operation", "paths./{className}={id}", "put")[
        "openapi_value"] == "PUT"
    assert _value(provmns, "schema_property", "components/schemas/Operation", "enum")[
        "openapi_value"] == "[add, remove, replace]"
    m = _value(provmns, "schema_property", "components/schemas/MoiChange", "properties.path")
    assert m["openapi_value"] == "$ref: 'TS28623_ComDefs.yaml#/components/schemas/Uri'"
    assert m["references"] == [{"file": "TS28623_ComDefs.yaml", "schema_name": "Uri"}]


def test_references_are_shallow(provmns):
    """An allOf rule references its members — not the refs of properties inside them."""
    m = _value(provmns, "schema_property", "components/schemas/NotifyMoiChanges", "allOf")
    assert m["references"] == [{"file": "TS28623_ComDefs.yaml",
                                "schema_name": "NotificationHeader"}]


def test_array_property_references_its_element(provmns):
    m = _value(provmns, "schema_property", "components/schemas/NotifyMoiChanges",
               "properties.moiChanges")
    assert m["openapi_value"] == "array"
    assert m["references"] == [{"file": "", "schema_name": "MoiChange"}]


def test_no_external_ref_interiors_leak_in(provmns):
    """Schema rules only address schemas defined in THIS document (§3.10)."""
    defined = {f"components/schemas/{n}"
               for n in _load("ProvMnS", "18.2.0")["components"]["schemas"]}
    objs = {r["openapi_mapping"]["openapi_object"] for r in provmns
            if r["rule_type"] == "schema_property"}
    assert objs <= defined
