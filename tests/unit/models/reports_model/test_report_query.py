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
Unit tests for cmdb.models.reports_model.report_query

The one reader of a stored report query, shared by the report run and the DocAPI report table: it
rebuilds the repr the report was stored as, datetime values included, and reads a report storing no
query as an empty one. The evaluation keeps builtin NAMES out of scope - which is all it does; the
module docstring says why that is not a sandbox
"""
from datetime import datetime
from typing import Any

import pytest

from cmdb.models.reports_model.report_query import (
    STORED_DATETIME_CALL,
    eval_stored_report_query,
    read_stored_report_query,
)
# -------------------------------------------------------------------------------------------------------------------- #

STORED_QUERY: str = f"{{'field': 'x', 'when': {STORED_DATETIME_CALL}(2024, 11, 26)}}"


class TestEvalStoredReportQuery:
    """The stored repr back into a dict."""

    def test_the_dict_is_rebuilt_with_its_datetime_values(self) -> None:
        """A stored query string is evaluated back into a dict, including datetime() calls"""
        result: dict[str, Any] = eval_stored_report_query(STORED_QUERY)

        assert result == {'field': 'x', 'when': datetime(2024, 11, 26)}

    def test_a_builtin_name_is_not_in_scope(self) -> None:
        """The namespace carries no builtins, so a builtin NAME does not resolve"""
        with pytest.raises(NameError):
            eval_stored_report_query("__import__('os')")

    def test_a_string_that_is_no_query_raises(self) -> None:
        """What a corrupted report answers is the caller's decision, so the reader raises"""
        with pytest.raises(SyntaxError):
            eval_stored_report_query('{not a dict')


class TestReadStoredReportQuery:
    """A report document's stored query, or an empty one."""

    def test_the_stored_query_is_read(self) -> None:
        """A report carrying a stored query gets it evaluated back into a dict"""
        assert read_stored_report_query({'report_query': {'data': "{'type_id': 5}"}}) == {'type_id': 5}

    @pytest.mark.parametrize('report', [
        {},
        {'report_query': None},
        {'report_query': {}},
        {'report_query': {'data': ''}},
        {'report_query': {'data': '   '}},
        {'report_query': {'data': None}},
        {'report_query': 'not-a-dict'},
    ])
    def test_a_report_storing_no_query_reads_as_empty(self, report: dict[str, Any]) -> None:
        """No usable stored query is a report without conditions, not an error"""
        assert read_stored_report_query(report) == {}

    def test_a_corrupted_stored_query_raises(self) -> None:
        """A query that IS stored but unreadable is left to the caller to answer"""
        with pytest.raises(SyntaxError):
            read_stored_report_query({'report_query': {'data': '{not a dict'}})
