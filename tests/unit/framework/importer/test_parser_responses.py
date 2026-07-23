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


# -------------------------------------------------------------------------------------------------------------------- #
#                                              ImporterObjectResponse                                                #
# -------------------------------------------------------------------------------------------------------------------- #

class TestImporterObjectResponse:
    """The bulk-import response carries a message and the success/failed message lists."""

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
