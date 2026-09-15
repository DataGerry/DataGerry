# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.database.mongo_query_builder

Covers, without a database:
  * field classification in __init__ (which also guards the FieldType-enum lookup),
  * value coercion (_coerce_value): datetime for date fields, int for number / reference fields,
    per-element for list-valued operators, unchanged otherwise,
  * the rule-assembly helpers (_create_rule / _build_elem_match) and the value fragments
    (_get_value_fragment) for every supported operator, including the regex-escaped contains / like,
    the day-granular date comparisons and the missing-entry half of 'is null',
  * build(): the type-only query, the single top-level type_id scoping and the and / or / nested
    group shapes,
  * the error paths: an unknown condition, a rule missing a required key, an unsupported operator
    and an uncoercible value - each raising its own error type, all of them MongoDBQueryBuilderError
    subclasses so the report routes can answer 400.
"""
from datetime import datetime
from typing import Any

import pytest

from cmdb.models.type_model import CmdbType
from cmdb.models.reports_model.report_constants import ReportConditionLogic, ReportQueryOperator
from cmdb.database.mongo_query_builder import (
    MongoDBQueryBuilder,
    FIELDS_PATH,
    MDS_VALUES_PATH,
    TYPE_ID_KEY,
)
from cmdb.errors.mongo_query_builder import (
    MongoDBQueryBuilderError,
    MongoQueryBuilderInitError,
    MongoQueryBuilderInvalidOperatorError,
    MongoQueryBuilderBuildError,
    MongoQueryBuilderBuildRuleError,
    MongoQueryBuilderBuildRulesetError,
)
# pylint: disable=protected-access
# -------------------------------------------------------------------------------------------------------------------- #

DEMO_TYPE_ID: int = 7


def _build_type() -> CmdbType:
    """A CmdbType with one field of each classified type plus an MDS section"""
    type_doc: dict[str, Any] = {
        "public_id": DEMO_TYPE_ID,
        "name": "demo",
        "label": "Demo",
        "active": True,
        "author_id": 1,
        "version": "1.0.0",
        "fields": [
            {"type": "number", "name": "num1", "label": "Num"},
            {"type": "date", "name": "date1", "label": "Date"},
            {"type": "ref", "name": "ref1", "label": "Ref"},
            {"type": "ref-section-field", "name": "refsec1", "label": "RefSec"},
            {"type": "text", "name": "txt1", "label": "Txt"},
            {"type": "text", "name": "mds1", "label": "MDS field"},
        ],
        "render_meta": {
            "icon": "fas fa-cube",
            "externals": [],
            "summary": {"fields": []},
            "sections": [
                {"type": "multi-data-section", "name": "mds-sec", "label": "MDS", "fields": ["mds1"]},
                {"type": "section", "name": "info", "label": "Info",
                 "fields": ["num1", "date1", "ref1", "refsec1", "txt1"]},
            ],
        },
    }
    return CmdbType.from_data(type_doc)


@pytest.fixture(name='builder')
def fixture_builder() -> MongoDBQueryBuilder:
    """A MongoDBQueryBuilder over the demo type with no query rules"""
    return MongoDBQueryBuilder(None, _build_type())


def _builder_with(
    rules: list[dict[str, Any]],
    condition: str = ReportConditionLogic.AND,
) -> MongoDBQueryBuilder:
    """A MongoDBQueryBuilder over the demo type with the given condition / rules"""
    return MongoDBQueryBuilder({"condition": condition, "rules": rules}, _build_type())

# -------------------------------------------------------------------------------------------------------------------- #
#                                          __init__ field classification                                              #
# -------------------------------------------------------------------------------------------------------------------- #

def test_init_classifies_fields_by_type(builder: MongoDBQueryBuilder) -> None:
    """Each field is bucketed by its FieldType (number/date/ref/ref-section-field)"""
    assert builder.number_fields == ["num1"]
    assert builder.date_fields == ["date1"]
    assert builder.ref_fields == ["ref1"]
    assert builder.ref_section_fields == ["refsec1"]


def test_init_collects_mds_field_names_as_strings(builder: MongoDBQueryBuilder) -> None:
    """MDS fields are collected as field-name strings (so the membership check in __build_rule works)"""
    assert builder.mds_fields == ["mds1"]
    assert all(isinstance(name, str) for name in builder.mds_fields)


def test_init_raises_init_error_on_invalid_report_type() -> None:
    """A report_type that does not expose the field accessors raises MongoQueryBuilderInitError"""
    with pytest.raises(MongoQueryBuilderInitError):
        MongoDBQueryBuilder(None, None)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _coerce_value                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_coerce_value_parses_date_field(builder: MongoDBQueryBuilder) -> None:
    """A date field's value is parsed into a datetime"""
    assert builder._coerce_value("date1", ReportQueryOperator.EQ, "2024-01-15") == datetime(2024, 1, 15)


def test_coerce_value_casts_number_and_reference_fields(builder: MongoDBQueryBuilder) -> None:
    """Number and reference field values are cast to int"""
    assert builder._coerce_value("num1", ReportQueryOperator.EQ, "5") == 5
    assert builder._coerce_value("ref1", ReportQueryOperator.EQ, "9") == 9
    assert builder._coerce_value("refsec1", ReportQueryOperator.EQ, "3") == 3


def test_coerce_value_leaves_text_fields_unchanged(builder: MongoDBQueryBuilder) -> None:
    """A text field's value is not coerced"""
    assert builder._coerce_value("txt1", ReportQueryOperator.EQ, "hello") == "hello"


def test_coerce_value_coerces_list_operators_element_wise(builder: MongoDBQueryBuilder) -> None:
    """For 'in' / 'not in' every list element of a numeric / date field is coerced individually"""
    assert builder._coerce_value("num1", ReportQueryOperator.IN, ["1", "2", "3"]) == [1, 2, 3]
    assert builder._coerce_value("date1", ReportQueryOperator.NOT_IN, ["2024-01-01", "2024-12-31"]) == [
        datetime(2024, 1, 1), datetime(2024, 12, 31),
    ]


def test_coerce_value_returns_falsy_untouched(builder: MongoDBQueryBuilder) -> None:
    """A None / empty value is returned untouched (no int / datetime parsing attempted)"""
    assert builder._coerce_value("num1", ReportQueryOperator.IS_NULL, None) is None
    assert builder._coerce_value("date1", ReportQueryOperator.IS_NULL, "") == ""

# -------------------------------------------------------------------------------------------------------------------- #
#                                        _create_rule / _build_elem_match                                             #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_elem_match_wraps_name_and_value(builder: MongoDBQueryBuilder) -> None:
    """_build_elem_match selects the named field entry and applies the value fragment to it"""
    assert builder._build_elem_match("f1", {"$eq": 5}) == {
        "$elemMatch": {"name": "f1", "value": {"$eq": 5}},
    }


@pytest.mark.parametrize('operator, value, expected_value_fragment', [
    (ReportQueryOperator.EQ, 5, {"$eq": 5}),
    (ReportQueryOperator.NE, 5, {"$ne": 5}),
    (ReportQueryOperator.LTE, 5, {"$lte": 5}),
    (ReportQueryOperator.GTE, 5, {"$gte": 5}),
    (ReportQueryOperator.LT, 5, {"$lt": 5}),
    (ReportQueryOperator.GT, 5, {"$gt": 5}),
    (ReportQueryOperator.IN, [1, 2], {"$in": [1, 2]}),
    (ReportQueryOperator.NOT_IN, [1, 2], {"$nin": [1, 2]}),
    (ReportQueryOperator.IS_NOT_NULL, None, {"$nin": [None, ""]}),
])
def test_create_rule_for_valid_operators(
    builder: MongoDBQueryBuilder,
    operator: str,
    value: Any,
    expected_value_fragment: dict[str, Any],
) -> None:
    """_create_rule nests the operator fragment under the target field via $elemMatch"""
    assert builder._create_rule(FIELDS_PATH, operator, "f1", value) == {
        FIELDS_PATH: {"$elemMatch": {"name": "f1", "value": expected_value_fragment}},
    }


def test_create_rule_for_is_null_also_matches_a_missing_entry(builder: MongoDBQueryBuilder) -> None:
    """'is null' ORs "entry exists and is empty" with "no such entry", because an object created
    before the field was added to its type carries no entry at all and $elemMatch cannot match it"""
    assert builder._create_rule(FIELDS_PATH, ReportQueryOperator.IS_NULL, "f1", None) == {
        "$or": [
            {FIELDS_PATH: {"$elemMatch": {"name": "f1", "value": {"$in": [None, ""]}}}},
            {FIELDS_PATH: {"$not": {"$elemMatch": {"name": "f1"}}}},
        ],
    }


def test_contains_emits_escaped_regex(builder: MongoDBQueryBuilder) -> None:
    """'contains' matches the value as a regex with the user input regex-escaped (literal match)"""
    assert builder._get_value_fragment(ReportQueryOperator.CONTAINS, "a.b*c") == {"$regex": r"a\.b\*c"}


def test_like_emits_case_insensitive_escaped_regex(builder: MongoDBQueryBuilder) -> None:
    """'like' emits a case-insensitive regex (not the old literal '/value/' string)"""
    assert builder._get_value_fragment(ReportQueryOperator.LIKE, "a.b") == {"$regex": r"a\.b", "$options": "i"}


def test_create_rule_targets_mds_path(builder: MongoDBQueryBuilder) -> None:
    """_create_rule honors a non-default target field (the MDS values path)"""
    result = builder._create_rule(MDS_VALUES_PATH, ReportQueryOperator.EQ, "mds1", 3)
    assert result == {
        MDS_VALUES_PATH: {"$elemMatch": {"name": "mds1", "value": {"$eq": 3}}},
    }


def test_create_rule_rejects_unknown_operator(builder: MongoDBQueryBuilder) -> None:
    """An unsupported operator surfaces as MongoQueryBuilderInvalidOperatorError"""
    with pytest.raises(MongoQueryBuilderInvalidOperatorError):
        builder._create_rule(FIELDS_PATH, "bogus", "f1", 1)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       build()                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_build_returns_type_only_query_without_rules(builder: MongoDBQueryBuilder) -> None:
    """With no condition / rules the query is just the type_id scoping"""
    assert builder.build() == {TYPE_ID_KEY: DEMO_TYPE_ID}


def test_build_scopes_to_type_id_exactly_once() -> None:
    """A built ruleset is AND-ed with a single top-level type_id constraint"""
    query = _builder_with([{"field": "txt1", "operator": "=", "value": "x"}], condition="and").build()

    assert query == {
        "$and": [
            {"$and": [{FIELDS_PATH: {"$elemMatch": {"name": "txt1", "value": {"$eq": "x"}}}}]},
            {TYPE_ID_KEY: DEMO_TYPE_ID},
        ],
    }
    # the type_id constraint must appear exactly once, even though rules may nest
    assert str(query).count(f"'{TYPE_ID_KEY}'") == 1


def test_build_uses_or_combiner_for_or_group() -> None:
    """An 'or' group becomes a $or combiner inside the type-scoped $and"""
    query = _builder_with([{"field": "txt1", "operator": "=", "value": "x"}], condition="or").build()

    assert query["$and"][0] == {"$or": [{FIELDS_PATH: {"$elemMatch": {"name": "txt1", "value": {"$eq": "x"}}}}]}


def test_build_recurses_into_nested_groups() -> None:
    """A nested group is translated recursively and carries no extra type_id constraint"""
    rules = [
        {"condition": "or", "rules": [{"field": "num1", "operator": ">", "value": "5"}]},
        {"field": "txt1", "operator": "=", "value": "x"},
    ]
    query = _builder_with(rules, condition="and").build()

    outer = query["$and"][0]["$and"]
    assert outer[0] == {"$or": [{FIELDS_PATH: {"$elemMatch": {"name": "num1", "value": {"$gt": 5}}}}]}
    assert outer[1] == {FIELDS_PATH: {"$elemMatch": {"name": "txt1", "value": {"$eq": "x"}}}}
    assert str(query).count(f"'{TYPE_ID_KEY}'") == 1


def test_build_coerces_multi_value_number_rule() -> None:
    """A number field with 'in' over a list of strings coerces every element to int (no crash)"""
    query = _builder_with([{"field": "num1", "operator": "in", "value": ["1", "2", "3"]}], condition="and").build()

    elem = query["$and"][0]["$and"][0][FIELDS_PATH]["$elemMatch"]
    assert elem == {"name": "num1", "value": {"$in": [1, 2, 3]}}


class _RaisingType:
    """A CmdbType stand-in whose public_id access fails, to reach the generic build() fallback."""

    @property
    def public_id(self) -> int:
        """Always raises, standing in for an unforeseen failure inside build()."""
        raise RuntimeError('type is unusable')


# -------------------------------------------------------------------------------------------------------------------- #
#                                            date comparisons (day-granular)                                           #
# -------------------------------------------------------------------------------------------------------------------- #

DAY_START: datetime = datetime(2026, 8, 6)
DAY_END: datetime = datetime(2026, 8, 6, 23, 59, 59, 999999)
DAY: str = '2026-08-06'


def _date_value_fragment(operator: str) -> dict[str, Any]:
    """The value fragment a date rule with the given operator produces for DAY."""
    query = _builder_with([{"field": "date1", "operator": operator, "value": DAY}], condition="and").build()

    return query["$and"][0]["$and"][0][FIELDS_PATH]["$elemMatch"]["value"]


class TestDateValueFragments:
    """A date rule carries only a day, so its comparison spans that whole day."""

    def test_end_of_day_is_the_last_instant(self, builder: MongoDBQueryBuilder) -> None:
        """The upper bound keeps the date and maxes out the time."""
        assert builder._end_of_day(DAY_START) == DAY_END

    def test_equals_spans_the_whole_day(self) -> None:
        """Regression: '=' used to match only objects stamped exactly at midnight."""
        assert _date_value_fragment(ReportQueryOperator.EQ) == {"$gte": DAY_START, "$lte": DAY_END}

    def test_not_equals_excludes_the_whole_day(self) -> None:
        """'!=' is the negation of the day range, not of its first instant."""
        assert _date_value_fragment(ReportQueryOperator.NE) == {"$not": {"$gte": DAY_START, "$lte": DAY_END}}

    def test_less_than_or_equal_includes_the_whole_day(self) -> None:
        """Regression: '<=' used to exclude everything after 00:00:00 on the given date."""
        assert _date_value_fragment(ReportQueryOperator.LTE) == {"$lte": DAY_END}

    def test_greater_than_excludes_the_whole_day(self) -> None:
        """Regression: '>' used to include the rest of the given date."""
        assert _date_value_fragment(ReportQueryOperator.GT) == {"$gt": DAY_END}

    def test_greater_than_or_equal_starts_at_midnight(self) -> None:
        """'>=' already meant 'from the start of that day' and is unchanged."""
        assert _date_value_fragment(ReportQueryOperator.GTE) == {"$gte": DAY_START}

    def test_less_than_starts_at_midnight(self) -> None:
        """'<' already meant 'before that day started' and is unchanged."""
        assert _date_value_fragment(ReportQueryOperator.LT) == {"$lt": DAY_START}

    def test_non_date_values_are_untouched(self, builder: MongoDBQueryBuilder) -> None:
        """The widening applies to datetime values only, never to numbers or text."""
        assert builder._get_value_fragment(ReportQueryOperator.LTE, 5) == {"$lte": 5}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    error paths                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestErrorPaths:
    """A malformed condition tree raises a precise builder error, not a generic one."""

    def test_unknown_condition_operator(self) -> None:
        """A group whose 'condition' is not and / or is rejected by name."""
        with pytest.raises(MongoQueryBuilderBuildRulesetError, match="Unknown condition operator"):
            _builder_with([{"field": "txt1", "operator": "=", "value": "x"}], condition="xor").build()

    @pytest.mark.parametrize('missing_key, rule', [
        ('field', {"operator": "=", "value": "x"}),
        ('operator', {"field": "txt1", "value": "x"}),
    ])
    def test_rule_missing_a_required_key_names_that_key(self, missing_key: str, rule: dict[str, Any]) -> None:
        """Regression: every KeyError used to be reported as 'Unknown condition operator'."""
        with pytest.raises(MongoQueryBuilderBuildRulesetError, match=f"missing the '{missing_key}' key"):
            _builder_with([rule], condition="and").build()

    def test_nested_group_missing_its_rules(self) -> None:
        """A group node without 'rules' is reported against the group, not the leaf."""
        with pytest.raises(MongoQueryBuilderBuildRulesetError, match="missing the 'rules' key"):
            _builder_with([{"condition": "or"}], condition="and").build()

    def test_unsupported_operator_survives_to_the_caller(self) -> None:
        """build() re-raises the precise error instead of flattening it to a build error."""
        with pytest.raises(MongoQueryBuilderInvalidOperatorError):
            _builder_with([{"field": "txt1", "operator": "between", "value": "x"}], condition="and").build()

    def test_unparsable_date_raises_a_build_rule_error(self) -> None:
        """A date that is not YYYY-MM-DD is a rule failure, not an internal error."""
        with pytest.raises(MongoQueryBuilderBuildRuleError):
            _builder_with([{"field": "date1", "operator": "=", "value": "06.08.2026"}], condition="and").build()

    def test_non_numeric_value_on_a_number_field_raises_a_build_rule_error(self) -> None:
        """The same for a number field that cannot take the value."""
        with pytest.raises(MongoQueryBuilderBuildRuleError):
            _builder_with([{"field": "num1", "operator": "=", "value": "abc"}], condition="and").build()

    def test_every_builder_error_is_a_mongodb_query_builder_error(self) -> None:
        """The routes catch the base class, so every raise must inherit from it."""
        with pytest.raises(MongoDBQueryBuilderError):
            _builder_with([{"field": "num1", "operator": "=", "value": "abc"}], condition="and").build()

    def test_non_iterable_rules_raise_a_ruleset_error(self) -> None:
        """A stored report whose 'rules' is not a list is a ruleset failure, not a crash."""
        builder = MongoDBQueryBuilder({"condition": "and", "rules": 5}, _build_type())

        with pytest.raises(MongoQueryBuilderBuildRulesetError, match="Error building MongoDB ruleset"):
            builder.build()

    def test_unexpected_failure_becomes_a_build_error(self) -> None:
        """Anything that is not already a builder error is wrapped as MongoQueryBuilderBuildError."""
        builder = _builder_with([{"field": "txt1", "operator": "=", "value": "x"}], condition="and")
        # The type is only read for its public_id at build time, so this is the last thing that can
        # fail outside the rule tree
        builder.report_type = _RaisingType()

        with pytest.raises(MongoQueryBuilderBuildError, match="Failed to build MongoDB query"):
            builder.build()
