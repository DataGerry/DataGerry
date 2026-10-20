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
Unit tests for cmdb.models.type_model.type_structure_rules

The one structure rule set the type routes and the type import share: the rules it holds, what it allows on purpose
(an orphan field, an empty section, a select without options), the external links' ``object_id`` pseudo-field, and the
summary line naming a field twice
"""
from typing import Any

import pytest

from cmdb.models.type_model.type_constants import STRUCTURE_ERROR_SEPARATOR, TypeStructureError
from cmdb.models.type_model.type_structure_rules import STRUCTURE_RULES, validate_type_structure
# -------------------------------------------------------------------------------------------------------------------- #

FIELD_A: str = 'a'
FIELD_B: str = 'b'


def _type(fields: list[dict[str, Any]] | None = None, sections: list[dict[str, Any]] | None = None,
          **render_meta: Any) -> dict[str, Any]:
    """A type document: two text fields in one section unless told otherwise."""
    fields = fields if fields is not None else [{'type': 'text', 'name': FIELD_A, 'label': 'A'},
                                                {'type': 'text', 'name': FIELD_B, 'label': 'B'}]
    sections = sections if sections is not None else [
        {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FIELD_A, FIELD_B]}]

    return {'fields': fields, 'render_meta': {'sections': sections, **render_meta}}


def _external(*field_names: str) -> dict[str, Any]:
    """An external link naming the given fields."""
    return {'name': 'link', 'label': 'Link', 'href': 'https://x/{}', 'icon': 'fa', 'fields': list(field_names)}


class TestTheSharedRuleSet:
    """STRUCTURE_RULES and validate_type_structure"""

    def test_a_sound_type_passes(self) -> None:
        """The control"""
        assert validate_type_structure(_type()) is None

    def test_a_document_that_is_no_mapping_passes_untouched(self) -> None:
        """The shape rules elsewhere answer for that"""
        assert validate_type_structure(['x']) is None

    def test_every_finding_is_joined(self) -> None:
        """One round trip, every problem"""
        document = _type(fields=[{'type': 'nonsense', 'name': FIELD_A, 'label': ''}],
                         sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FIELD_A]}])

        assert validate_type_structure(document).count(STRUCTURE_ERROR_SEPARATOR) == 1

    def test_the_harmless_rules_are_not_in_the_set(self) -> None:
        """No rule for orphan fields, empty sections or option-less selects"""
        names = {rule.__name__ for rule in STRUCTURE_RULES}

        assert not names & {'_unassigned_fields_error', '_empty_sections_error', '_missing_field_options_error'}


class TestAllowedOnPurpose:
    """What breaks no read is allowed"""

    def test_a_field_no_section_shows(self) -> None:
        """It renders nowhere"""
        assert validate_type_structure(_type(sections=[
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FIELD_A]}])) is None

    def test_a_section_showing_no_field(self) -> None:
        """An empty box"""
        sections = [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FIELD_A, FIELD_B]},
                    {'type': 'section', 'name': 'empty', 'label': 'Empty', 'fields': []}]

        assert validate_type_structure(_type(sections=sections)) is None

    @pytest.mark.parametrize('field_type', ['select', 'radio'])
    def test_a_choice_field_without_options(self, field_type: str) -> None:
        """It holds no value until options are added"""
        fields = [{'type': field_type, 'name': FIELD_A, 'label': 'A', 'options': []}]

        assert validate_type_structure(_type(fields=fields, sections=[
            {'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [FIELD_A]}])) is None


class TestExternalLinks:
    """The external links name declared fields or the object's own object_id"""

    @pytest.mark.parametrize('names', [('object_id',), (FIELD_A, 'object_id'), (FIELD_A,)],
                             ids=['object-id', 'field-and-object-id', 'field'])
    def test_declared_fields_and_the_object_id_pass(self, names: tuple[str, ...]) -> None:
        """What the type builder offers"""
        assert validate_type_structure(_type(externals=[_external(*names)])) is None

    def test_an_undeclared_field_is_refused(self) -> None:
        """Its href could not be filled in"""
        assert validate_type_structure(_type(externals=[_external('object_id', 'ghost')])) == \
            TypeStructureError.EXTERNAL_FIELD_NOT_DEFINED.format(names=['ghost'])

    def test_the_legacy_spelling_is_judged_too(self) -> None:
        """'external' instead of 'externals'"""
        assert validate_type_structure(_type(external=[_external('ghost')])) == \
            TypeStructureError.EXTERNAL_FIELD_NOT_DEFINED.format(names=['ghost'])


class TestSummaryLine:
    """The summary names declared fields, each once"""

    def test_a_repeated_field_is_refused(self) -> None:
        """The value would show twice"""
        assert validate_type_structure(_type(summary={'fields': [FIELD_A, FIELD_B, FIELD_A]})) == \
            TypeStructureError.SUMMARY_FIELD_REPEATED.format(names=[FIELD_A])

    def test_each_field_once_passes(self) -> None:
        """The control"""
        assert validate_type_structure(_type(summary={'fields': [FIELD_A, FIELD_B]})) is None

    @pytest.mark.parametrize('summary', [None, 'x', {'fields': None}], ids=['none', 'string', 'no-fields'])
    def test_an_unreadable_summary_is_skipped(self, summary: Any) -> None:
        """Nothing to judge"""
        assert validate_type_structure(_type(summary=summary)) is None
