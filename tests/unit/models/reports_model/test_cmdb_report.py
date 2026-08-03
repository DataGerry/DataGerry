# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for CmdbReport and its condition-tree surgery

Covers the (de)serialization contract - including the lenient read of the two schema-optional keys, so
one legacy document cannot fail a whole report list - and ``clear_rules_of_field`` /
``remove_field_occurrences``, the tree rewrite that runs when a CmdbType loses a field: nested groups,
groups that collapse, malformed nodes, duplicate selected fields and the promise not to mutate the
document a report was loaded from.
"""
from typing import Any

import pytest

from cmdb.models.reports_model.cmdb_report import CmdbReport, clear_rules_of_field
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.reports_model.report_constants import ReportConditionKey, ReportConditionLogic
from cmdb.errors.cmdb_object import RequiredInitKeyNotFoundError
from cmdb.errors.models.cmdb_report import (
    CmdbReportInitFromDataError,
    CmdbReportToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

REPORT_ID: int = 7
CATEGORY_ID: int = 3
TYPE_ID: int = 5

REMOVED_FIELD: str = 'gone'
KEPT_FIELD: str = 'stays'


def _leaf(field_name: str) -> dict[str, Any]:
    """Builds one leaf condition rule referencing a field."""
    return {'field': field_name, 'operator': '=', 'value': 'x'}


def _group(*rules: dict[str, Any], condition: str = ReportConditionLogic.AND.value) -> dict[str, Any]:
    """Builds one condition group combining the given rules."""
    return {'condition': condition, 'rules': list(rules)}


def _report_document(**overrides: Any) -> dict[str, Any]:
    """Builds a complete stored CmdbReport document."""
    document: dict[str, Any] = {
        'public_id': REPORT_ID,
        'report_category_id': CATEGORY_ID,
        'name': 'My Report',
        'type_id': TYPE_ID,
        'selected_fields': [KEPT_FIELD],
        'conditions': _group(_leaf(KEPT_FIELD)),
        'report_query': {'data': "{'type_id': 5}"},
        'predefined': False,
        'mds_mode': MdsMode.ROWS.value,
    }
    document.update(overrides)

    return document


def _report(**overrides: Any) -> CmdbReport:
    """Builds a CmdbReport from a complete stored document."""
    return CmdbReport.from_data(_report_document(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 clear_rules_of_field                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('conditions', [None, {}])
def test_clear_rules_of_field_returns_none_for_an_empty_tree(conditions: dict[str, Any] | None) -> None:
    """A report without conditions has nothing to strip."""
    assert clear_rules_of_field(conditions, REMOVED_FIELD) is None


def test_clear_rules_of_field_drops_only_the_matching_leaf() -> None:
    """The rule naming the removed field goes, its siblings stay, the group operator is preserved."""
    conditions = _group(_leaf(REMOVED_FIELD), _leaf(KEPT_FIELD), condition=ReportConditionLogic.OR.value)

    stripped = clear_rules_of_field(conditions, REMOVED_FIELD)

    assert stripped == {'condition': ReportConditionLogic.OR.value, 'rules': [_leaf(KEPT_FIELD)]}


def test_clear_rules_of_field_strips_nested_groups_at_any_depth() -> None:
    """A leaf buried in nested groups is removed while the surrounding structure survives."""
    conditions = _group(
        _leaf(KEPT_FIELD),
        _group(_group(_leaf(REMOVED_FIELD), _leaf(KEPT_FIELD))),
    )

    stripped = clear_rules_of_field(conditions, REMOVED_FIELD)

    assert stripped == _group(_leaf(KEPT_FIELD), _group(_group(_leaf(KEPT_FIELD))))


def test_clear_rules_of_field_drops_a_group_that_becomes_empty() -> None:
    """A group whose every rule referenced the removed field is dropped from its parent."""
    conditions = _group(_leaf(KEPT_FIELD), _group(_leaf(REMOVED_FIELD)))

    stripped = clear_rules_of_field(conditions, REMOVED_FIELD)

    assert stripped == _group(_leaf(KEPT_FIELD))


def test_clear_rules_of_field_collapses_a_fully_stripped_tree_to_none() -> None:
    """When nothing survives, the whole tree becomes None - the report loses its filter entirely."""
    conditions = _group(_leaf(REMOVED_FIELD), _group(_leaf(REMOVED_FIELD)))

    assert clear_rules_of_field(conditions, REMOVED_FIELD) is None


def test_clear_rules_of_field_keeps_a_leaf_without_a_field_key() -> None:
    """A malformed leaf is not the searched field, so it is kept instead of raising a KeyError."""
    conditions = _group({'operator': '='}, _leaf(REMOVED_FIELD))

    stripped = clear_rules_of_field(conditions, REMOVED_FIELD)

    assert stripped == _group({'operator': '='})


def test_clear_rules_of_field_tolerates_a_group_without_a_logical_operator() -> None:
    """A node without 'condition' is rebuilt with a missing operator instead of raising a KeyError."""
    stripped = clear_rules_of_field({'rules': [_leaf(REMOVED_FIELD), _leaf(KEPT_FIELD)]}, REMOVED_FIELD)

    assert stripped == {'condition': None, 'rules': [_leaf(KEPT_FIELD)]}


def test_clear_rules_of_field_tolerates_a_group_without_rules() -> None:
    """A group carrying no rules at all collapses to None."""
    assert clear_rules_of_field({'condition': ReportConditionLogic.AND.value}, REMOVED_FIELD) is None


def test_clear_rules_of_field_does_not_mutate_the_input_tree() -> None:
    """The input tree is left untouched - the caller's stored document must not change."""
    conditions = _group(_leaf(REMOVED_FIELD), _leaf(KEPT_FIELD))
    original = _group(_leaf(REMOVED_FIELD), _leaf(KEPT_FIELD))

    clear_rules_of_field(conditions, REMOVED_FIELD)

    assert conditions == original


def test_clear_rules_of_field_uses_the_condition_key_enum() -> None:
    """The rebuilt tree is keyed by ReportConditionKey members, which serialize as their strings."""
    stripped = clear_rules_of_field(_group(_leaf(KEPT_FIELD)), REMOVED_FIELD)

    assert stripped[ReportConditionKey.CONDITION] == ReportConditionLogic.AND.value
    assert stripped[ReportConditionKey.RULES] == [_leaf(KEPT_FIELD)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                              remove_field_occurrences                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_remove_field_occurrences_strips_the_field_from_both_places() -> None:
    """The field leaves the selected fields and its condition rules in one call."""
    report = _report(selected_fields=[KEPT_FIELD, REMOVED_FIELD], conditions=_group(_leaf(REMOVED_FIELD)))

    report.remove_field_occurrences(REMOVED_FIELD)

    assert report.selected_fields == [KEPT_FIELD]
    assert report.conditions is None


def test_remove_field_occurrences_removes_every_duplicate() -> None:
    """A duplicated selected field is removed completely, not just its first occurrence."""
    report = _report(selected_fields=[REMOVED_FIELD, KEPT_FIELD, REMOVED_FIELD])

    report.remove_field_occurrences(REMOVED_FIELD)

    assert report.selected_fields == [KEPT_FIELD]


def test_remove_field_occurrences_does_not_mutate_the_source_document() -> None:
    """The list is replaced, not mutated, so the document the report was loaded from is unchanged."""
    document = _report_document(selected_fields=[KEPT_FIELD, REMOVED_FIELD])
    report = CmdbReport.from_data(document)

    report.remove_field_occurrences(REMOVED_FIELD)

    assert document['selected_fields'] == [KEPT_FIELD, REMOVED_FIELD]


def test_remove_field_occurrences_of_an_unrelated_field_changes_nothing() -> None:
    """Removing a field the report never referenced leaves both attributes as they were."""
    report = _report()

    report.remove_field_occurrences('never-referenced')

    assert report.selected_fields == [KEPT_FIELD]
    assert report.conditions == _group(_leaf(KEPT_FIELD))


def test_remove_field_occurrences_leaves_the_stored_query_stale() -> None:
    """The compiled query is NOT rebuilt here - that is the caller's job (documented contract)."""
    report = _report()
    stored_query = report.report_query

    report.remove_field_occurrences(KEPT_FIELD)

    assert report.report_query is stored_query


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      from_data                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_reads_a_complete_document() -> None:
    """Every stored key lands on the instance."""
    report = _report()

    assert report.public_id == REPORT_ID
    assert report.report_category_id == CATEGORY_ID
    assert report.name == 'My Report'
    assert report.type_id == TYPE_ID
    assert report.selected_fields == [KEPT_FIELD]
    assert report.report_query == {'data': "{'type_id': 5}"}
    assert report.predefined is False
    assert report.mds_mode == MdsMode.ROWS


@pytest.mark.parametrize('missing_key,expected', [
    ('mds_mode', ('mds_mode', MdsMode.ROWS)),
    ('predefined', ('predefined', False)),
    ('conditions', ('conditions', None)),
    ('report_query', ('report_query', None)),
])
def test_from_data_defaults_the_optional_keys(missing_key: str, expected: tuple[str, Any]) -> None:
    """A document written before these keys existed still hydrates, with the documented default.

    'mds_mode' is the live case: it postdates the reporting feature, it is optional in the validation
    schema, and the report list hydrates EVERY row - so a strict read would fail the whole list.
    """
    document = _report_document()
    del document[missing_key]

    report = CmdbReport.from_data(document)

    attribute, default = expected
    assert getattr(report, attribute) == default


@pytest.mark.parametrize('missing_key', ['report_category_id', 'name', 'type_id', 'selected_fields'])
def test_from_data_missing_required_key_raises(missing_key: str) -> None:
    """The keys the schema marks required are read strictly - such a document is broken."""
    document = _report_document()
    del document[missing_key]

    with pytest.raises(CmdbReportInitFromDataError):
        CmdbReport.from_data(document)


def test_from_data_without_a_public_id_raises() -> None:
    """The lenient ``.get('public_id')`` cannot produce an instance: CmdbDAO coerces the identity
    with ``int()``, so a document without one fails as the model's own from-data error."""
    document = _report_document()
    del document['public_id']

    with pytest.raises(CmdbReportInitFromDataError):
        CmdbReport.from_data(document)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       to_json                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_to_json_round_trips_a_document() -> None:
    """A stored document survives from_data -> to_json unchanged."""
    document = _report_document()

    assert CmdbReport.to_json(CmdbReport.from_data(document)) == document


def test_to_json_raises_for_an_incomplete_instance() -> None:
    """Serializing an instance whose attributes were stripped surfaces as the model's own error."""
    report = _report()
    del report.name

    with pytest.raises(CmdbReportToJsonError):
        CmdbReport.to_json(report)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     constructor                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_init_applies_its_defaults_when_the_keys_are_passed_explicitly() -> None:
    """The declared defaults are what a caller gets for the two server-owned keys."""
    report = CmdbReport(
        public_id=REPORT_ID,
        report_category_id=CATEGORY_ID,
        name='My Report',
        type_id=TYPE_ID,
        selected_fields=[],
        conditions=None,
        report_query=None,
        predefined=False,
        mds_mode=MdsMode.ROWS,
    )

    assert report.predefined is False
    assert report.mds_mode == MdsMode.ROWS


@pytest.mark.parametrize('omitted_key', ['public_id', 'predefined', 'mds_mode'])
def test_init_demands_every_required_init_key_as_a_kwarg(omitted_key: str) -> None:
    """REQUIRED_INIT_KEYS is enforced by CmdbDAO.__new__, so the signature defaults of 'predefined'
    and 'mds_mode' are unreachable through a direct construction - and the failure happens BEFORE
    __init__, so it is not wrapped as CmdbReportInitError. from_data always passes all of them."""
    kwargs: dict[str, Any] = {
        'public_id': REPORT_ID,
        'report_category_id': CATEGORY_ID,
        'name': 'My Report',
        'type_id': TYPE_ID,
        'selected_fields': [],
        'conditions': None,
        'report_query': None,
        'predefined': False,
        'mds_mode': MdsMode.ROWS,
    }
    del kwargs[omitted_key]

    with pytest.raises(RequiredInitKeyNotFoundError):
        CmdbReport(**kwargs)


def test_index_declarations_and_schema_are_exposed() -> None:
    """The model exposes its collection, its index declarations and the shared validation schema."""
    assert CmdbReport.COLLECTION == 'framework.reports'
    assert {entry['name'] for entry in CmdbReport.INDEX_KEYS} == {'report_category_id', 'type_id'}
    assert CmdbReport.SCHEMA['name']['required'] is True
