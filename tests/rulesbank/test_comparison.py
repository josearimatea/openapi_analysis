"""Unit tests for the rule-by-rule comparison — small hand-made rules, no data files."""

from openapi_analysis.rulesbank.comparison import compare_rules, compare_value


def rule(rule_type, obj, field, value="", refs=(), **extra):
    return {"rule_type": rule_type,
            "openapi_mapping": {"openapi_object": obj, "openapi_field": field,
                                "openapi_value": value,
                                "references": [{"file": f, "schema_name": n} for f, n in refs]},
            **extra}


S = "components/schemas/X"


# ── value ────────────────────────────────────────────────────────────────────

def test_external_ref_turned_internal_is_flagged_323():
    exp = rule("schema_property", S, "properties.p", "$ref: 'A.yaml#/components/schemas/Uri'",
               refs=[("A.yaml", "Uri")])
    act = rule("schema_property", S, "properties.p", "$ref: '#/components/schemas/Uri'",
               refs=[("", "Uri")])
    status, note = compare_value(exp, act)
    assert status == "different" and "§3.23" in note


def test_ref_written_only_in_the_value_counts():
    exp = rule("schema_property", S, "properties.p", "$ref: '#/components/schemas/Y'",
               refs=[("", "Y")])
    act = rule("schema_property", S, "properties.p", "$ref: '#/components/schemas/Y'")
    assert compare_value(exp, act)[0] == "equal"


def test_enum_is_a_set():
    exp = rule("schema_property", S, "enum", "[a, b, c]")
    assert compare_value(exp, rule("schema_property", S, "enum", "[c, a, b]"))[0] == "equal"
    status, note = compare_value(exp, rule("schema_property", S, "enum", "[a, b]"))
    assert status == "different" and "'c'" in note


def test_enum_written_with_prose_checks_presence():
    exp = rule("schema_property", S, "enum", "[ON, OFF]")
    act = rule("schema_property", S, "enum", "[ON — switched on, the default, OFF — off]")
    assert compare_value(exp, act)[0] == "equal"
    act = rule("schema_property", S, "enum", "[ON — switched on, the default]")
    assert compare_value(exp, act)[0] == "different"


def test_required_with_an_extra_item_is_different():
    exp = rule("schema_property", S, "required", "[id]")
    assert compare_value(exp, rule("schema_property", S, "required", "[id, x]"))[0] == "different"


def test_type_is_read_from_the_start_of_the_value():
    exp = rule("schema_property", S, "properties.p", "string")
    assert compare_value(exp, rule("schema_property", S, "properties.p",
                                   "string (date-time)"))[0] == "equal"
    assert compare_value(exp, rule("schema_property", S, "properties.p",
                                   "integer"))[0] == "different"


def test_nothing_to_compare_is_not_comparable():
    exp = rule("response", "paths./x.put.responses", "204", "")
    assert compare_value(exp, rule("response", "paths./x.put.responses", "204",
                                   "No Content"))[0] == "not_comparable"


def test_no_body_is_equal_to_a_value_that_names_no_body():
    """Equal only when the bank names nothing a body carries; any doubt stays different."""
    exp = rule("response", "paths./x.put.responses", "204", "no body")
    for said in ("No Content", "No response body", "no message body is returned"):
        assert compare_value(exp, rule("response", "paths./x.put.responses", "204",
                                       said))[0] == "equal", said
    for said in ("object", "array of Uri", "ErrorResponse body", "oneOf the two"):
        assert compare_value(exp, rule("response", "paths./x.put.responses", "204",
                                       said))[0] == "different", said


def test_a_schema_written_as_it_is_is_equal_only_to_the_same_schema():
    exp = rule("schema_property", S, "properties.v", "{nullable: true}")
    assert compare_value(exp, rule("schema_property", S, "properties.v",
                                   "{ nullable: true }"))[0] == "equal"
    for said in ("{}", "object", "any type"):
        assert compare_value(exp, rule("schema_property", S, "properties.v",
                                       said))[0] == "different", said


def test_body_where_the_yaml_has_none_is_different():
    exp = rule("response", "paths./x.delete.responses", "200", "no body")
    act = rule("response", "paths./x.delete.responses", "200",
               "$ref: '#/components/schemas/Uri'")
    assert compare_value(exp, act)[0] == "different"


def test_callback_expression_ignores_braces_and_dollar():
    exp = rule("callback", "paths./x.put.callbacks.n", "post", "{$request.body#/a}")
    assert compare_value(exp, rule("callback", "paths./x.put.callbacks.n", "post",
                                   "{request.body#/a}"))[0] == "equal"


# ── rule by rule ─────────────────────────────────────────────────────────────

def test_duplicates_on_one_address_are_all_kept():
    """Two bank rules on one address both survive — never overwritten by key."""
    official = [rule("schema_property", S, "properties.p", "string")]
    bank = {"rules": [rule("schema_property", S, "properties.p", "string"),
                      rule("schema_property", S, "properties.p", "integer")]}
    ev = compare_rules(official, bank)
    assert ev.totals.covered == 1 and ev.totals.bank_rules == 2
    assert ev.totals.bank_duplicates == 1
    assert [b.index for b in ev.shared_addresses[0].bank] == [0, 1]


def test_bank_rules_are_covering_plus_duplicates_plus_extra():
    official = [rule("path_operation", "paths./x", "get", "GET")]
    bank = {"rules": [rule("path_operation", "paths./x", "get", "GET"),
                      rule("path_operation", "paths./x", "get", "GET"),
                      rule("path_operation", "paths./y", "get", "GET")]}
    t = compare_rules(official, bank).totals
    assert t.bank_rules == t.covered + t.bank_duplicates + t.bank_extra == 3


def test_missing_and_extra():
    official = [rule("path_operation", "paths./x", "get", "GET"),
                rule("path_operation", "paths./x", "put", "PUT")]
    bank = {"rules": [rule("path_operation", "paths./x", "get", "GET"),
                      rule("path_operation", "paths./y", "get", "GET"),
                      rule("made_up", "paths./x", "get", "GET", validation_passed=False)]}
    ev = compare_rules(official, bank)
    assert ev.totals.expected == 2 and ev.totals.covered == 1 and ev.totals.missing == 1
    assert [x.reason for x in ev.extra] == ["not_in_official_yaml", "unknown_rule_type"]
    assert ev.bank_invalid_rules == 1


def test_query_param_on_the_path_does_not_cover_the_operation_one_322():
    official = [rule("query_parameter", "paths./x.get", "parameters[in=query,name=q]", "string")]
    bank = {"rules": [rule("query_parameter", "paths./x", "parameters[in=query,name=q]",
                           "string")]}
    ev = compare_rules(official, bank)
    assert ev.totals.covered == 0 and len(ev.extra) == 1


def test_media_type_is_identity_for_request_body():
    obj = "paths./x.patch.requestBody"
    official = [rule("request_body", obj, "content", "application/json"),
                rule("request_body", obj, "content", "application/merge-patch+json")]
    bank = {"rules": [rule("request_body", obj, "content", "application/json")]}
    ev = compare_rules(official, bank)
    assert ev.totals.covered == 1 and ev.totals.missing == 1


R = "paths./x.get.responses"
ERR = "$ref: '#/components/schemas/ErrorResponse'"


def test_a_default_is_covered_by_the_4xx_and_5xx_of_its_operation():
    official = [rule("response", R, "default", ERR, refs=[("", "ErrorResponse")])]
    bank = {"rules": [rule("response", R, "4XX", ERR, refs=[("", "ErrorResponse")]),
                      rule("response", R, "5XX", ERR, refs=[("", "ErrorResponse")]),
                      rule("response", "paths./y.get.responses", "4XX", ERR)]}
    ev = compare_rules(official, bank)
    t = ev.totals
    assert (t.covered, t.value_equal, t.bank_ranges, t.bank_duplicates, t.bank_extra) == (
        1, 1, 1, 0, 1)                                 # /y is another operation: extra
    assert t.bank_rules == t.covered + t.bank_duplicates + t.bank_ranges + t.bank_extra
    assert ev.shared_addresses == [] and ev.matches[0].ranges


def test_a_default_covered_by_the_ranges_compares_its_ref():
    official = [rule("response", R, "default", "$ref: '#/components/schemas/ErrorResponseDefault'",
                     refs=[("", "ErrorResponseDefault")])]
    bank = {"rules": [rule("response", R, "4XX", ERR, refs=[("", "ErrorResponse")]),
                      rule("response", R, "5XX", ERR, refs=[("", "ErrorResponse")])]}
    m = compare_rules(official, bank).matches[0]
    assert m.value_status == "different" and "4XX" in m.note and "ErrorResponse" in m.note


def test_a_default_replaced_by_one_range_only_is_missing():
    """OpenAPI: default covers the codes not declared, 4XX only 400-499 — 5XX is lacking."""
    official = [rule("response", R, "default", ERR)]
    bank = {"rules": [rule("response", R, "4XX", ERR)]}
    ev = compare_rules(official, bank)
    t = ev.totals
    assert (t.covered, t.missing, t.bank_ranges, t.bank_extra) == (0, 1, 0, 1)
    assert ev.missing_note(official[0]) == "the bank replaced default by 4XX only: 5XX missing"
    assert ev.extra[0].note == ev.missing_note(official[0])


def test_ranges_the_official_declares_are_not_taken_by_its_default():
    official = [rule("response", R, "default", ERR), rule("response", R, "4XX", ERR)]
    bank = {"rules": [rule("response", R, "4XX", ERR)]}
    t = compare_rules(official, bank).totals
    assert (t.covered, t.missing, t.bank_ranges, t.bank_extra) == (1, 1, 0, 0)


def test_a_bank_default_is_matched_by_address_not_by_ranges():
    official = [rule("response", R, "default", ERR)]
    bank = {"rules": [rule("response", R, "default", ERR), rule("response", R, "4XX", ERR)]}
    ev = compare_rules(official, bank)
    assert not ev.matches[0].ranges and ev.totals.bank_extra == 1


def test_two_rules_on_one_range_are_a_duplicate():
    official = [rule("response", R, "default", ERR)]
    bank = {"rules": [rule("response", R, "4XX", ERR), rule("response", R, "4XX", ERR),
                      rule("response", R, "5XX", ERR)]}
    ev = compare_rules(official, bank)
    assert (ev.totals.bank_duplicates, ev.totals.bank_ranges) == (1, 1)
    assert len(ev.shared_addresses) == 1


def test_coverage_and_fidelity_ratios():
    official = [rule("schema_property", S, "properties.a", "string"),
                rule("schema_property", S, "properties.b", "string"),
                rule("schema_property", S, "properties.c", ""),
                rule("schema_property", S, "properties.d", "string")]
    bank = {"rules": [rule("schema_property", S, "properties.a", "string"),
                      rule("schema_property", S, "properties.b", "integer"),
                      rule("schema_property", S, "properties.c", "{}")]}
    t = compare_rules(official, bank).totals
    assert (t.covered, t.value_equal, t.value_different, t.value_not_comparable) == (3, 1, 1, 1)
    assert t.coverage == 0.75 and t.fidelity == 0.5
