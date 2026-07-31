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
Unit tests for the parser response base classes (BaseParserResponse / ObjectParserResponse)

DB-free: focus on the base ABC contract (not directly instantiable, abstract output raises when
called via super) and that ObjectParserResponse.output() returns count + entries plus any
attributes a subclass adds to its __dict__.
"""
import pytest

from cmdb.framework.importer.responses.base_parser_response import BaseParserResponse
from cmdb.framework.importer.responses.object_parser_response import ObjectParserResponse
from cmdb.framework.importer.responses.json_object_parser_response import JsonObjectParserResponse
from cmdb.framework.importer.responses.csv_object_parser_response import CsvObjectParserResponse
from cmdb.framework.importer.responses.importer_object_response import ImporterObjectResponse
from cmdb.framework.importer.responses.import_report_response import (
    ImportReportResponse,
    build_import_summary_message,
)
from cmdb.framework.importer.importer_constants import ImportNoun
# -------------------------------------------------------------------------------------------------------------------- #


# -------------------------------------------------------------------------------------------------------------------- #
#                                                BaseParserResponse                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

class TestBaseParserResponse:
    """The abstract parser-response base."""

    def test_cannot_be_instantiated_directly(self) -> None:
        """BaseParserResponse is abstract (output is unimplemented)."""
        with pytest.raises(TypeError):
            BaseParserResponse(count=1)  # pylint: disable=abstract-class-instantiated

    def test_super_output_raises_not_implemented(self) -> None:
        """A subclass delegating to super().output() hits the abstract NotImplementedError."""
        class _DelegatingResponse(BaseParserResponse):
            def output(self) -> dict:  # pylint: disable=useless-parent-delegation
                return super().output()

        with pytest.raises(NotImplementedError):
            _DelegatingResponse(count=0).output()


# -------------------------------------------------------------------------------------------------------------------- #
#                                               ObjectParserResponse                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

class TestObjectParserResponse:
    """The concrete object parser response."""

    def test_stores_count_and_entries(self) -> None:
        """count and entries are stored as given."""
        response = ObjectParserResponse(count=2, entries=[{'a': 1}, {'a': 2}])

        assert response.count == 2
        assert response.entries == [{'a': 1}, {'a': 2}]

    def test_entries_default_to_empty_list(self) -> None:
        """Omitting entries yields an empty list, not None."""
        response = ObjectParserResponse(count=0)

        assert response.entries == []

    def test_output_returns_count_and_entries(self) -> None:
        """output() exposes at least count and entries."""
        output = ObjectParserResponse(count=1, entries=[{'x': 1}]).output()

        assert output == {'count': 1, 'entries': [{'x': 1}]}

    def test_output_includes_subclass_attributes(self) -> None:
        """output() returns __dict__, so subclass attributes are included automatically."""
        class _WithExtra(ObjectParserResponse):
            def __init__(self, count: int, entries: list, extra: str) -> None:
                self.extra: str = extra
                super().__init__(count=count, entries=entries)

        output = _WithExtra(count=1, entries=[], extra='meta').output()

        assert output['extra'] == 'meta'
        assert output['count'] == 1
        assert output['entries'] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                             JsonObjectParserResponse                                               #
# -------------------------------------------------------------------------------------------------------------------- #

class TestJsonObjectParserResponse:
    """The JSON parser response is a thin marker subtype of ObjectParserResponse."""

    def test_is_object_parser_response(self) -> None:
        """It inherits the object-parser response behaviour."""
        response = JsonObjectParserResponse(count=2, entries=[{'a': 1}, {'a': 2}])

        assert isinstance(response, ObjectParserResponse)

    def test_output_returns_count_and_entries(self) -> None:
        """output() exposes the inherited count and entries."""
        output = JsonObjectParserResponse(count=1, entries=[{'x': 1}]).output()

        assert output == {'count': 1, 'entries': [{'x': 1}]}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             CsvObjectParserResponse                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestCsvObjectParserResponse:
    """The CSV parser response adds a header row and per-entry length."""

    def test_stores_header_and_entry_length(self) -> None:
        """The header list and entry length are stored and exposed via the getters."""
        response = CsvObjectParserResponse(
            count=1, entries=[{0: 'a', 1: 'b'}], entry_length=2, header=['id', 'name'],
        )

        assert response.get_header_list() == ['id', 'name']
        assert response.get_entry_length() == 2

    def test_header_defaults_to_empty_list(self) -> None:
        """Omitting the header yields an empty list, not an empty dict (B1)."""
        response = CsvObjectParserResponse(count=0, entries=[], entry_length=0)

        assert response.get_header_list() == []
        assert isinstance(response.get_header_list(), list)

    def test_output_includes_header_and_entry_length(self) -> None:
        """output() surfaces the CSV-specific attributes alongside count/entries."""
        output = CsvObjectParserResponse(
            count=1, entries=[{0: 'a'}], entry_length=1, header=['id'],
        ).output()

        assert output['header'] == ['id']
        assert output['entry_length'] == 1
        assert output['count'] == 1
        assert output['entries'] == [{0: 'a'}]

    def test_raw_header_is_kept_next_to_the_resolved_one(self) -> None:
        """A decorated (import-template) header travels along untouched for display purposes."""
        response = CsvObjectParserResponse(
            count=1,
            entries=[{0: 'a'}],
            entry_length=1,
            header=['hostname'],
            raw_header=['Hostname [hostname]'],
        )

        assert response.get_header_list() == ['hostname']
        assert response.get_raw_header_list() == ['Hostname [hostname]']

    def test_raw_header_defaults_to_the_resolved_header(self) -> None:
        """A plain header needs no second list, so both are the same - one code path for a consumer."""
        response = CsvObjectParserResponse(count=1, entries=[{0: 'a'}], entry_length=1, header=['id'])

        assert response.get_raw_header_list() == ['id']

    def test_output_includes_the_raw_header(self) -> None:
        """The raw header is part of the /parse/ payload (additive - `header` keeps its meaning)."""
        output = CsvObjectParserResponse(
            count=1, entries=[{0: 'a'}], entry_length=1, header=['id'], raw_header=['Id [id]'],
        ).output()

        assert output['header'] == ['id']
        assert output['raw_header'] == ['Id [id]']


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ImporterObjectResponse                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImporterObjectResponse:
    """The importer's internal result keeps a message per imported and per failed object."""

    def test_stores_message_and_import_lists(self) -> None:
        """The message and both import lists are stored as given."""
        response = ImporterObjectResponse(message='ok', success_imports=[1], failed_imports=[2])

        assert response.message == 'ok'
        assert response.success_imports == [1]
        assert response.failed_imports == [2]

    def test_import_lists_default_to_empty(self) -> None:
        """Omitting the import lists yields empty lists, not None."""
        response = ImporterObjectResponse(message='none')

        assert response.success_imports == []
        assert response.failed_imports == []


class TestImporterObjectResponseAsReport:
    """as_report() turns the internal result into the body the caller receives."""

    def test_imported_objects_collapse_to_a_count(self) -> None:
        """The response reports HOW MANY objects were imported, not the objects themselves."""
        report = ImporterObjectResponse(message='ok', success_imports=['a', 'b', 'c']).as_report()

        assert isinstance(report, ImportReportResponse)
        assert report.success_imports == 3

    def test_failures_and_message_are_carried_over(self) -> None:
        """The rejected objects keep their messages and the summary line is reused as built."""
        failures = [{'failed_object': {}, 'errors': ['boom']}]

        report = ImporterObjectResponse(message='summary', success_imports=[], failed_imports=failures).as_report()

        assert report.message == 'summary'
        assert report.failed_imports is failures

    def test_an_empty_import_reports_zero(self) -> None:
        """A batch that imported nothing reports 0, not an empty list."""
        assert ImporterObjectResponse(message='none').as_report().success_imports == 0


class TestImportReportResponse:
    """The wire report carries the imported count and the failure messages."""

    def test_success_imports_is_a_count(self) -> None:
        """success_imports is a plain number - the imported entries are never echoed back."""
        report = ImportReportResponse(message='ok', success_imports=2, failed_imports=['f'])

        assert report.success_imports == 2
        assert report.failed_imports == ['f']

    def test_defaults_to_nothing_imported(self) -> None:
        """Omitting both sides yields a zero count and an empty failure list, not None."""
        report = ImportReportResponse(message='none')

        assert report.success_imports == 0
        assert report.failed_imports == []


class TestBuildImportSummaryMessage:
    """The summary line reports what happened, including when nothing could be imported."""

    @pytest.mark.parametrize(
        'success, failed, expected',
        [
            (2, 0, 'Imported 2 of 2 objects, 0 failed'),
            (1, 0, 'Imported 1 of 1 object, 0 failed'),
            (0, 0, 'Imported 0 of 0 objects, 0 failed'),
            (2, 1, 'Imported 2 of 3 objects, 1 failed'),
            (0, 3, 'Imported 0 of 3 objects, 3 failed'),
            (0, 1, 'Imported 0 of 1 object, 1 failed'),
        ],
        ids=['all-ok', 'single', 'empty-file', 'partial', 'all-rejected', 'single-rejected'],
    )
    def test_summary_wording(self, success: int, failed: int, expected: str) -> None:
        """Every count combination reads as a plain statement of the outcome."""
        assert build_import_summary_message(success, failed) == expected

    @pytest.mark.parametrize('success, failed', [(2, 0), (2, 1), (0, 3), (0, 0)])
    def test_both_counts_are_always_present(self, success: int, failed: int) -> None:
        """Every summary states the imported count, the submitted total and the failed count."""
        message = build_import_summary_message(success, failed)

        assert f'Imported {success} of {success + failed}' in message
        assert f'{failed} failed' in message

    @pytest.mark.parametrize(
        'success, failed, expected',
        [
            (2, 1, 'Imported 2 of 3 types, 1 failed'),
            (1, 0, 'Imported 1 of 1 type, 0 failed'),
            (0, 0, 'Imported 0 of 0 types, 0 failed'),
        ],
        ids=['partial', 'single', 'empty-upload'],
    )
    def test_the_noun_names_what_was_imported(self, success: int, failed: int, expected: str) -> None:
        """The type import reuses the same line, only naming types instead of objects."""
        assert build_import_summary_message(success, failed, ImportNoun.TYPE) == expected
