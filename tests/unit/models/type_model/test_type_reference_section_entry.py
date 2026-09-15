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
Unit tests for cmdb.models.type_model.type_reference_section_entry

``resolve_pulled_field_names`` is what a ref-section actually shows, and both the renderer and the
CmdbType update guard resolve it through this one function - the renderer to build the block, the
guard to refuse an edit that would leave the block empty. The case worth pinning is the one that makes
a plain intersection wrong: an EMPTY selection means "every field of the section", not "no fields"

Pure tests: no Mongo, no Flask
"""
import pytest

from cmdb.models.type_model.type_reference_section_entry import (
    TypeReferenceSectionEntry,
    resolve_pulled_field_names,
)
# -------------------------------------------------------------------------------------------------------------------- #

SECTION_FIELDS: list[str] = ['first', 'second', 'third']


class TestResolvePulledFieldNames:
    """The selection rule."""

    def test_a_selection_keeps_only_the_selected_fields(self) -> None:
        """The ordinary 'limit section output' case"""
        assert resolve_pulled_field_names(['second'], SECTION_FIELDS) == ['second']

    @pytest.mark.parametrize('selected_fields', [[], None], ids=['empty', 'absent'])
    def test_no_selection_means_every_field_of_the_section(self, selected_fields) -> None:
        """
        The case that makes an intersection the wrong implementation

        An unlimited ref-section shows the whole referenced section, so an empty selection must not
        resolve to nothing - reading it that way would blank every unlimited reference section.
        """
        assert resolve_pulled_field_names(selected_fields, SECTION_FIELDS) == SECTION_FIELDS

    def test_the_referenced_sections_order_wins(self) -> None:
        """The block is rendered in the referenced section's order, not the selection's"""
        assert resolve_pulled_field_names(['third', 'first'], SECTION_FIELDS) == ['first', 'third']

    def test_a_selected_field_the_section_no_longer_carries_is_dropped(self) -> None:
        """Exactly how a stale selection stops being displayed rather than erroring"""
        assert resolve_pulled_field_names(['second', 'gone'], SECTION_FIELDS) == ['second']

    def test_resolves_to_nothing_when_no_selected_field_remains(self) -> None:
        """The state the update guard refuses to create: a reference that shows nothing"""
        assert resolve_pulled_field_names(['gone'], SECTION_FIELDS) == []

    def test_an_empty_section_shows_nothing_even_unlimited(self) -> None:
        """An emptied section blanks an unlimited reference too, which stores no field name at all"""
        assert resolve_pulled_field_names([], []) == []

    def test_the_section_field_list_is_not_returned_by_reference(self) -> None:
        """
        The renderer holds a CACHED type: handing back the live list would let a caller mutate it

        The renderer's own comment says the selection must be computed locally for this reason.
        """
        section_fields = list(SECTION_FIELDS)

        result = resolve_pulled_field_names([], section_fields)
        result.append('injected')

        assert section_fields == SECTION_FIELDS


class TestTheEntryMethod:
    """The method the renderer calls on a reference entry."""

    def test_delegates_to_the_shared_rule(self) -> None:
        """One implementation, so the guard and the renderer cannot disagree"""
        entry = TypeReferenceSectionEntry(type_id=1, section_name='s', selected_fields=['second'])

        assert entry.resolve_pulled_field_names(SECTION_FIELDS) == ['second']

    def test_an_entry_without_a_selection_pulls_the_whole_section(self) -> None:
        """selected_fields defaults to [] on the entry, which means 'all'"""
        entry = TypeReferenceSectionEntry(type_id=1, section_name='s')

        assert entry.resolve_pulled_field_names(SECTION_FIELDS) == SECTION_FIELDS
