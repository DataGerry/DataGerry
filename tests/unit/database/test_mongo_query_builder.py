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

Covers the side-effect-free construction surface: field classification in __init__ (which also
guards the FieldType-enum lookup), and the rule-assembly helpers create_rule / get_operator_fragment
for valid operators. Pure tests: no Mongo.

Deliberately NOT covered (open issues flagged in the audit): build()/__build_ruleset (the ruleset
guard checks the root condition rather than the passed parameters) and the 'like' branch of
get_value_fragment (it emits a literal '/value/' string instead of a $regex).
"""
from typing import Any

import pytest

from cmdb.models.type_model import CmdbType
from cmdb.database.mongo_query_builder import MongoDBQueryBuilder
from cmdb.errors.mongo_query_builder import (
    MongoQueryBuilderInitError,
    MongoQueryBuilderInvalidOperatorError,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _build_type() -> CmdbType:
    """A CmdbType with one field of each classified type plus an MDS section"""
    type_doc: dict[str, Any] = {
        "public_id": 7,
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
            {"type": "text", "name": "mds1", "label": "MDS field"},
        ],
        "render_meta": {
            "icon": "fas fa-cube",
            "externals": [],
            "summary": {"fields": []},
            "sections": [
                {"type": "multi-data-section", "name": "mds-sec", "label": "MDS", "fields": ["mds1"]},
                {"type": "section", "name": "info", "label": "Info",
                 "fields": ["num1", "date1", "ref1", "refsec1"]},
            ],
        },
    }
    return CmdbType.from_data(type_doc)


@pytest.fixture(name='builder')
def fixture_builder() -> MongoDBQueryBuilder:
    """A MongoDBQueryBuilder over the demo type with no query rules"""
    return MongoDBQueryBuilder(None, _build_type())

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
#                                       create_rule / get_operator_fragment                                           #
# -------------------------------------------------------------------------------------------------------------------- #

def test_get_operator_fragment_builds_elem_match(builder: MongoDBQueryBuilder) -> None:
    """get_operator_fragment wraps the value fragment in an $elemMatch on name + value"""
    assert builder.get_operator_fragment("=", "f1", 5) == {
        "$elemMatch": {"name": "f1", "value": {"$eq": 5}},
    }


@pytest.mark.parametrize('operator, value, expected_value_fragment', [
    ("=", 5, {"$eq": 5}),
    ("!=", 5, {"$ne": 5}),
    ("<=", 5, {"$lte": 5}),
    (">=", 5, {"$gte": 5}),
    ("<", 5, {"$lt": 5}),
    (">", 5, {"$gt": 5}),
    ("in", [1, 2], {"$in": [1, 2]}),
    ("not in", [1, 2], {"$nin": [1, 2]}),
    ("contains", "abc", {"$regex": "abc"}),
    ("is null", None, {"$in": [None, ""]}),
    ("is not null", None, {"$nin": [None, ""]}),
])
def test_create_rule_for_valid_operators(
    builder: MongoDBQueryBuilder,
    operator: str,
    value: Any,
    expected_value_fragment: dict[str, Any],
) -> None:
    """create_rule nests the operator fragment under the target field via $elemMatch"""
    assert builder.create_rule("fields", operator, "f1", value) == {
        "fields": {"$elemMatch": {"name": "f1", "value": expected_value_fragment}},
    }


def test_create_rule_targets_mds_path(builder: MongoDBQueryBuilder) -> None:
    """create_rule honors a non-default target field (the MDS values path)"""
    result = builder.create_rule("multi_data_sections.values.data", "=", "mds1", 3)
    assert result == {
        "multi_data_sections.values.data": {"$elemMatch": {"name": "mds1", "value": {"$eq": 3}}},
    }


def test_create_rule_rejects_unknown_operator(builder: MongoDBQueryBuilder) -> None:
    """An unsupported operator surfaces as MongoQueryBuilderInvalidOperatorError"""
    with pytest.raises(MongoQueryBuilderInvalidOperatorError):
        builder.create_rule("fields", "bogus", "f1", 1)
