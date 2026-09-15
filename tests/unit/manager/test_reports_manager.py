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
Unit tests for cmdb.manager.reports_manager.ReportsManager

Only strip_removed_fields_from_reports carries logic of its own - the rest of the class is the
inherited GenericManager CRUD surface, covered by tests/unit/manager/test_generic_manager.py.

Pure tests: no Mongo. The method is invoked unbound with a MagicMock standing in for the manager, so
bulk_write is stubbed and only the report rewriting is exercised.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.reports_manager import ReportsManager
from cmdb.models.reports_model.report_constants import ReportQueryKey
from cmdb.errors.manager.reports_manager import ReportsManagerUpdateError
# -------------------------------------------------------------------------------------------------------------------- #

MANAGER_PATH: str = 'cmdb.manager.reports_manager'

REPORT_ID: int = 41
TYPE_ID: int = 7

KEPT_FIELD: str = 'kept-field'
GONE_FIELD: str = 'gone-field'
OTHER_GONE_FIELD: str = 'other-gone-field'


def _report_doc(public_id: int = REPORT_ID) -> dict[str, Any]:
    """A stored CmdbReport document selecting and filtering on both a kept and a removed field"""
    return {
        'public_id': public_id,
        'report_category_id': 1,
        'name': f'report-{public_id}',
        'type_id': TYPE_ID,
        'selected_fields': [KEPT_FIELD, GONE_FIELD],
        'conditions': {
            'condition': 'and',
            'rules': [
                {'field': KEPT_FIELD, 'operator': '=', 'value': 'a'},
                {'field': GONE_FIELD, 'operator': '=', 'value': 'b'},
            ],
        },
        'report_query': {'data': '{}'},
        'predefined': False,
        'mds_mode': 'ROWS',
    }


def _written_report(mock_self: MagicMock, index: int = 0) -> dict[str, Any]:
    """The '$set' payload of the n-th UpdateOne handed to bulk_write"""
    operations = mock_self.bulk_write.call_args.args[0]

    return operations[index]._doc['$set']  # pylint: disable=protected-access


def _strip(mock_self: MagicMock, reports: list[dict[str, Any]], removed: set[str]) -> int:
    """Runs the method unbound with the query builder patched out"""
    with patch(f'{MANAGER_PATH}.MongoDBQueryBuilder') as builder:
        builder.return_value.build.return_value = {'rebuilt': True}

        return ReportsManager.strip_removed_fields_from_reports(mock_self, reports, removed, MagicMock())

# -------------------------------------------------------------------------------------------------------------------- #
#                                                      NO-OPS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #

def test_no_removed_fields_writes_nothing() -> None:
    """Nothing removed means no work - the common case on a metadata-only type edit"""
    mock_self = MagicMock()

    assert _strip(mock_self, [_report_doc()], set()) == 0
    mock_self.bulk_write.assert_not_called()


def test_no_reports_writes_nothing() -> None:
    """A type without reports needs no write even when fields were removed"""
    mock_self = MagicMock()

    assert _strip(mock_self, [], {GONE_FIELD}) == 0
    mock_self.bulk_write.assert_not_called()

# -------------------------------------------------------------------------------------------------------------------- #
#                                                     STRIPPING                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_removes_the_field_from_the_selection() -> None:
    """The removed field is dropped from selected_fields and the kept one survives"""
    mock_self = MagicMock()

    _strip(mock_self, [_report_doc()], {GONE_FIELD})

    assert _written_report(mock_self)['selected_fields'] == [KEPT_FIELD]


def test_removes_the_rule_from_the_conditions() -> None:
    """A condition rule on the removed field is dropped, the unrelated rule survives"""
    mock_self = MagicMock()

    _strip(mock_self, [_report_doc()], {GONE_FIELD})

    rules = _written_report(mock_self)['conditions']['rules']

    assert [rule['field'] for rule in rules] == [KEPT_FIELD]


def test_rebuilds_the_stored_query_from_the_remaining_conditions() -> None:
    """report_query is regenerated rather than left describing the pre-removal filter"""
    mock_self = MagicMock()

    _strip(mock_self, [_report_doc()], {GONE_FIELD})

    assert _written_report(mock_self)['report_query'] == {ReportQueryKey.DATA: str({'rebuilt': True})}


def test_removes_every_named_field() -> None:
    """All removed names are stripped, not just the first"""
    mock_self = MagicMock()
    report = _report_doc()
    report['selected_fields'] = [KEPT_FIELD, GONE_FIELD, OTHER_GONE_FIELD]

    _strip(mock_self, [report], {GONE_FIELD, OTHER_GONE_FIELD})

    assert _written_report(mock_self)['selected_fields'] == [KEPT_FIELD]


def test_writes_every_report_in_one_bulk_operation() -> None:
    """All of a type's reports are persisted in a single round-trip"""
    mock_self = MagicMock()
    reports = [_report_doc(REPORT_ID), _report_doc(REPORT_ID + 1)]

    assert _strip(mock_self, reports, {GONE_FIELD}) == len(reports)

    mock_self.bulk_write.assert_called_once()
    assert len(mock_self.bulk_write.call_args.args[0]) == len(reports)


def test_each_update_targets_its_own_report() -> None:
    """The UpdateOne filters pin each write to the report it came from"""
    mock_self = MagicMock()
    reports = [_report_doc(REPORT_ID), _report_doc(REPORT_ID + 1)]

    _strip(mock_self, reports, {GONE_FIELD})

    operations = mock_self.bulk_write.call_args.args[0]
    filters = [operation._filter for operation in operations]  # pylint: disable=protected-access

    assert filters == [{'public_id': REPORT_ID}, {'public_id': REPORT_ID + 1}]


def test_leaves_the_input_documents_untouched() -> None:
    """The stored documents handed in are not mutated - the caller may still need them"""
    mock_self = MagicMock()
    report = _report_doc()

    _strip(mock_self, [report], {GONE_FIELD})

    assert report['selected_fields'] == [KEPT_FIELD, GONE_FIELD]

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ERROR MAPPING                                                      #
# -------------------------------------------------------------------------------------------------------------------- #

def test_failed_write_raises_the_manager_error() -> None:
    """A failing bulk write surfaces as ReportsManagerUpdateError, not as a raw pymongo error"""
    mock_self = MagicMock()
    mock_self.bulk_write.side_effect = RuntimeError('boom')

    with pytest.raises(ReportsManagerUpdateError):
        _strip(mock_self, [_report_doc()], {GONE_FIELD})


def test_broken_report_document_raises_the_manager_error() -> None:
    """A stored document that cannot be hydrated is reported, not silently skipped"""
    mock_self = MagicMock()

    with pytest.raises(ReportsManagerUpdateError):
        _strip(mock_self, [{'public_id': REPORT_ID}], {GONE_FIELD})
