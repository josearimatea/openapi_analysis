"""The rule taxonomy for the rules-bank evaluation: what a rule IS, how it is addressed.

THIS MODULE IS THE DEFINITION. A rule has one format — the rules-bank format of
openapi_rulesbank:

    {"rule_type": ..., "openapi_mapping": {"openapi_object": ..., "openapi_field": ...,
                                           "openapi_value": ..., "references": [...]}}

The generated bank is in it, and the rules extracted from the official YAML
(extraction.py) are produced in it. Both sides are compared rule by rule, keyed by
`rule_key` below; nothing else may build a rule key by hand, or the two counts
would diverge.

STATUS: DRAFT, under review (docs/RULES.md). The entries below record what the
generator ENFORCES today (openapi_rulesbank/utils/rules_check.py). When a decision
about a rule type is made, it is written here first, then pinned by a test.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleTypeSpec:
    """What one rule type means and how a rule of that type is addressed."""
    name: str
    yaml_location: str     # where the construct lives in an OpenAPI document
    object_format: str     # the shape of openapi_mapping.openapi_object
    field_format: str      # the shape of openapi_mapping.openapi_field
    value_meaning: str     # what openapi_mapping.openapi_value holds
    value_in_identity: bool = False   # True → the value is part of the address


RULE_TYPES: dict[str, RuleTypeSpec] = {spec.name: spec for spec in (
    RuleTypeSpec(
        name="path_operation",
        yaml_location="paths.<path>.<method>",
        object_format="paths.<path>",
        field_format="<method>  (get|put|post|delete|patch — one method per rule)",
        value_meaning="the method in upper case (GET, PUT, ...)",
    ),
    RuleTypeSpec(
        name="path_parameter",
        yaml_location="paths.<path>.parameters[] or paths.<path>.<method>.parameters[], in=path",
        object_format="paths.<path>  or  paths.<path>.<method>  (the level the YAML "
                      "declares it at — both are valid OpenAPI)",
        field_format="parameters[in=path,name=<name>]",
        value_meaning="the parameter's schema / type",
    ),
    RuleTypeSpec(
        name="query_parameter",
        yaml_location="paths.<path>.<method>.parameters[], in=query",
        object_format="paths.<path>.<method>  (always the operation — a query parameter "
                      "belongs to one operation; rules_check rejects the path alone)",
        field_format="parameters[in=query,name=<name>]",
        value_meaning="the parameter's schema / type",
    ),
    RuleTypeSpec(
        name="request_body",
        yaml_location="paths.<path>.<method>.requestBody.content.<mediaType>  (and the "
                      "same under a callback's delivery operation)",
        object_format="paths.<path>.<method>.requestBody  or, inside a callback, "
                      "paths.<path>.<method>.callbacks.<name>.<deliveryMethod>.requestBody",
        field_format="content",
        value_meaning="the media type (application/json, ...)",
        value_in_identity=True,   # field is constant; the media type tells rules apart
    ),
    RuleTypeSpec(
        name="response",
        yaml_location="paths.<path>.<method>.responses.<code>  (and the same under a "
                      "callback's delivery operation)",
        object_format="paths.<path>.<method>.responses  or, inside a callback, "
                      "paths.<path>.<method>.callbacks.<name>.<deliveryMethod>.responses",
        field_format="<code>  (3-digit, 1XX–5XX, or default)",
        value_meaning="the response body schema / $ref (empty for a body-less response)",
    ),
    RuleTypeSpec(
        name="callback",
        yaml_location="paths.<path>.<method>.callbacks.<name>.<expression>.<method>",
        object_format="paths.<path>.<method>.callbacks.<name>",
        field_format="<delivery method>",
        value_meaning="the runtime expression of the consumer address ({$request.body#/...})",
    ),
    RuleTypeSpec(
        name="schema_property",
        yaml_location="components.schemas.<Name>",
        object_format="components/schemas/<Name>  (the ROOT schema, never a path inside it)",
        field_format=("properties.<name>  or a keyword: enum | required | oneOf | anyOf | "
                      "allOf | items | additionalProperties"),
        value_meaning="the property's type / $ref, or the keyword's whole collection",
    ),
    RuleTypeSpec(
        name="security_scheme",
        yaml_location="components.securitySchemes.<Name>",
        object_format="components/securitySchemes/<Name>",
        field_format="type",
        value_meaning="oauth2 | http | apiKey | openIdConnect",
    ),
)}

KNOWN_RULE_TYPES = frozenset(RULE_TYPES)

# HTTP methods a rule may name (rules_check.py _VALID_HTTP_METHODS).
HTTP_METHODS = ("get", "put", "post", "delete", "patch")

# schema_property keywords (rules_check.py _VALID_SCHEMA_KEYWORDS). A keyword is ONE
# rule whose value is the whole collection — never one rule per item.
SCHEMA_KEYWORDS = ("enum", "required", "oneOf", "anyOf", "allOf", "items",
                   "additionalProperties")

_VALUE_IN_IDENTITY = frozenset(n for n, s in RULE_TYPES.items() if s.value_in_identity)

RuleKey = tuple[str, str, str, str]


def rule_key(rule: dict) -> RuleKey:
    """The identity a rule is counted and matched by — the only key builder allowed.

    `rule` is in the rules-bank format, whether it comes from the generated bank or
    was extracted from the official YAML. The key is (rule_type, object, field,
    value-if-part-of-identity-else-""): for most types the value is CONTENT to be
    compared, not identity (RuleTypeSpec.value_in_identity). Taken as written, with
    no normalisation — whether to normalise is an open decision (docs/RULES.md).
    """
    rule_type = rule.get("rule_type", "")
    mapping = rule.get("openapi_mapping") or {}
    value = mapping.get("openapi_value", "")
    return (rule_type, mapping.get("openapi_object", ""), mapping.get("openapi_field", ""),
            value if rule_type in _VALUE_IN_IDENTITY else "")
