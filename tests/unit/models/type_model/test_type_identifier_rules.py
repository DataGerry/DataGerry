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
Unit tests for cmdb.models.type_model.type_identifier_rules

What a NEW field or section identifier may be. Pinned in both directions: every shape the type builder produces
passes (its random ``<type>-<uuid>`` and the label-derived names, dots and non-ASCII letters included), and the three
shapes that break something are refused - blank, padded, bracketed. A name the stored type already holds is never
judged, whatever it looks like: identifiers are immutable
"""
from typing import Any

import pytest

from cmdb.framework.exporter.exporter_constants import TEMPLATE_COLUMN_PART_SEPARATOR, TEMPLATE_FIELD_NAME_TEMPLATE
from cmdb.framework.importer.parser.csv_object_parser import normalize_csv_header
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.type_constants import IdentifierKind, TypeIdentifierError
from cmdb.models.type_model.type_identifier_rules import (
    identifier_error,
    identifier_problem,
    payload_identifier_names,
    stored_identifier_names,
)
# -------------------------------------------------------------------------------------------------------------------- #

BUILDER_RANDOM_NAME: str = 'text-3f6b1c2e-9d4a-4c1b-8e2f-0a1b2c3d4e5f'
BRACKETED: str = 'size-[gb]'
PADDED: str = ' cpu'


@pytest.mark.parametrize('name', [
    BUILDER_RANDOM_NAME, 'hostname', 'ip.address', 'größe', 'cpu-(ghz)', 'dg_location', 'a', 'Mixed_Case-1',
], ids=['builder-random', 'plain', 'dot', 'umlaut', 'parentheses', 'underscore', 'one-character', 'mixed'])
def test_every_name_the_builder_produces_is_usable(name: str) -> None:
    """The builder derives names from labels - lowercase, spaces to hyphens - so all of these are ordinary"""
    assert identifier_problem(name) is None


@pytest.mark.parametrize('name, problem', [
    ('', TypeIdentifierError.BLANK),
    ('   ', TypeIdentifierError.BLANK),
    ('\t', TypeIdentifierError.BLANK),
    (PADDED, TypeIdentifierError.SURROUNDING_WHITESPACE),
    ('cpu ', TypeIdentifierError.SURROUNDING_WHITESPACE),
    (BRACKETED, TypeIdentifierError.FORBIDDEN_CHARACTER),
    ('a]b', TypeIdentifierError.FORBIDDEN_CHARACTER),
], ids=['empty', 'spaces', 'tab', 'leading', 'trailing', 'brackets', 'closing-bracket'])
def test_the_three_breaking_shapes_are_refused(name: str, problem: TypeIdentifierError) -> None:
    """Blank, padded, bracketed"""
    assert identifier_problem(name) is problem


@pytest.mark.parametrize('name', [None, 7, ['x']], ids=['none', 'number', 'list'])
def test_a_value_that_is_no_string_is_left_to_the_schema(name: Any) -> None:
    """The schema and the structure rules answer for those"""
    assert identifier_problem(name) is None


class TestIdentifierError:
    """The write-level answer: the first refused NEW identifier, fields before sections."""

    def test_a_usable_write_passes(self) -> None:
        """Nothing to refuse"""
        assert identifier_error(['hostname', 'ip.address'], ['main', 'interfaces']) is None

    def test_the_first_refused_field_is_named(self) -> None:
        """In write order, with its kind"""
        assert identifier_error(['ok', BRACKETED, PADDED], []) == TypeIdentifierError.FORBIDDEN_CHARACTER.format(
            kind=IdentifierKind.FIELD.value, name=BRACKETED)

    def test_fields_come_before_sections(self) -> None:
        """A bad field is reported even when a section is bad too"""
        assert identifier_error([PADDED], ['']).startswith("The field identifier")

    def test_a_section_is_judged_too(self) -> None:
        """Section identifiers follow the same rule"""
        assert identifier_error(['ok'], ['']) == TypeIdentifierError.BLANK.format(
            kind=IdentifierKind.SECTION.value, name='')

    def test_a_stored_identifier_is_never_judged(self) -> None:
        """Immutable: an old bracketed field and an old blank section pass, a NEW bracketed field does not"""
        assert identifier_error([BRACKETED], [''], {BRACKETED}, {''}) is None
        assert identifier_error([BRACKETED, 'new-[x]'], [], {BRACKETED}) == \
            TypeIdentifierError.FORBIDDEN_CHARACTER.format(kind=IdentifierKind.FIELD.value, name='new-[x]')


class TestTheNameReaders:
    """Where the identifiers come from."""

    def test_payload_identifier_names_reads_fields_and_sections_in_order(self) -> None:
        """Non-dict entries are skipped"""
        data: dict[str, Any] = {
            'fields': [{'name': 'a'}, 'junk', {'name': 'b'}],
            'render_meta': {'sections': [{'name': 's1'}, None, {'name': 's2'}]},
        }

        assert payload_identifier_names(data) == (['a', 'b'], ['s1', 's2'])

    def test_payload_identifier_names_tolerates_missing_keys(self) -> None:
        """A payload without fields or render_meta has no identifiers"""
        assert payload_identifier_names({}) == ([], [])

    def test_stored_identifier_names_reads_a_cmdb_type(self) -> None:
        """The fields and sections of a real CmdbType"""
        cmdb_type: CmdbType = CmdbType.from_data({
            'public_id': 1, 'name': 't', 'author_id': 1,
            'fields': [{'type': 'text', 'name': 'a'}, {'type': 'text', 'name': 'b'}],
            'render_meta': {'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': ['a', 'b']}]},
        })

        assert stored_identifier_names(cmdb_type) == ({'a', 'b'}, {'main'})


class TestWhyBracketsAreRefused:
    """The object-import template carries the identifier in its header; a bracket cannot be read back."""

    @staticmethod
    def _header(name: str) -> str:
        """A template column header for a field, as the exporter builds it"""
        return TEMPLATE_COLUMN_PART_SEPARATOR.join(['Label', TEMPLATE_FIELD_NAME_TEMPLATE.format(name=name)])

    @pytest.mark.parametrize('name', ['ip.address', 'größe', 'cpu-(ghz)', BUILDER_RANDOM_NAME])
    def test_a_usable_name_is_read_back(self, name: str) -> None:
        """The template round trip keeps every allowed name"""
        assert normalize_csv_header([self._header(name)]) == [name]

    @pytest.mark.parametrize('name', [BRACKETED, 'a]b'])
    def test_a_bracketed_name_is_not(self, name: str) -> None:
        """The pattern cannot find it - the reason the rule refuses brackets; loosen the reader before the rule"""
        assert normalize_csv_header([self._header(name)]) != [name]
