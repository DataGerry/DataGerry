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
Unit tests for cmdb.models.type_model.type_structure_repairs

Without a stored Type (an import) every name in a section, the summary or an external link that resolves to no
declared field is dropped. With one (an update) only a name the stored Type carried in the same list, or one naming
a field it declared, is dropped - a name the update newly writes stays for the rules to refuse. Declared names,
``object_id`` in a link and entries the rules do not read as names are never touched
"""
import copy
from typing import Any

import pytest

from cmdb.models.type_model.section_key_enum import SectionKey
from cmdb.models.type_model.type_constants import LEGACY_EXTERNALS_KEY, TypeReferencePlace
from cmdb.models.type_model.type_structure_repairs import (
    DroppedReference,
    drop_unresolvable_references,
    reference_lists,
    resolves,
)
from cmdb.models.type_model.type_structure_rules import validate_type_structure
# -------------------------------------------------------------------------------------------------------------------- #

FIELDS: str = 'fields'
HIDDEN: str = SectionKey.HIDDEN_FIELDS.value
DECLARED: set[str] = {'a', 'b'}


def _type(fields: list[str], sections: list[dict[str, Any]] | None = None, summary: list[Any] | None = None,
          externals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A type document with text fields of the given names."""
    return {
        'fields': [{'type': 'text', 'name': name, 'label': name.upper()} for name in fields],
        'render_meta': {'sections': sections or [], 'summary': {'fields': summary or []},
                        'externals': externals or []},
    }


def _section(name: str, fields: list[Any], hidden: list[Any] | None = None) -> dict[str, Any]:
    """A section; an MDS one when it hides fields."""
    section: dict[str, Any] = {'type': 'section', 'name': name, 'label': name, 'fields': fields}

    if hidden is not None:
        section.update(type='multi-data-section', hidden_fields=hidden)

    return section


def _link(name: str, fields: list[Any]) -> dict[str, Any]:
    """An external link."""
    return {'name': name, 'label': name, 'href': 'https://x/{}', 'icon': 'x', 'fields': fields}


class TestResolves:
    """resolves - read the way the structure rules read"""

    @pytest.mark.parametrize('place, name, expected', [
        (TypeReferencePlace.SECTION, 'a', True), (TypeReferencePlace.SECTION, 'ghost', False),
        (TypeReferencePlace.SECTION, 5, True), (TypeReferencePlace.SUMMARY, 'a', True),
        (TypeReferencePlace.SUMMARY, 'ghost', False), (TypeReferencePlace.SUMMARY, 5, False),
        (TypeReferencePlace.SUMMARY, 'object_id', False), (TypeReferencePlace.EXTERNAL, 'object_id', True),
        (TypeReferencePlace.EXTERNAL, 'ghost', False),
    ], ids=['section-declared', 'section-unknown', 'section-non-string', 'summary-declared', 'summary-unknown',
            'summary-non-string', 'summary-object-id', 'external-object-id', 'external-unknown'])
    def test_each_place(self, place: TypeReferencePlace, name: Any, expected: bool) -> None:
        """A section entry only as a string; object_id only in a link"""
        assert resolves(place, name, DECLARED) is expected


class TestReferenceLists:
    """reference_lists"""

    def test_every_list_is_found_with_its_place(self) -> None:
        """Sections (fields + hidden fields), the summary, each link"""
        entry = _type(['a'], [_section('main', ['a']), _section('mds', [], ['a'])], ['a'], [_link('wiki', ['a'])])

        assert [ref.identity for ref in reference_lists(entry)] == [
            (TypeReferencePlace.SECTION, 'main', FIELDS), (TypeReferencePlace.SECTION, 'mds', FIELDS),
            (TypeReferencePlace.SECTION, 'mds', HIDDEN), (TypeReferencePlace.SUMMARY, None, FIELDS),
            (TypeReferencePlace.EXTERNAL, 'wiki', FIELDS)]

    def test_the_legacy_externals_key_is_read(self) -> None:
        """When the current key is absent"""
        entry = {'render_meta': {LEGACY_EXTERNALS_KEY: [_link('old', ['a'])]}}

        assert [ref.identity for ref in reference_lists(entry)] == [(TypeReferencePlace.EXTERNAL, 'old', FIELDS)]

    @pytest.mark.parametrize('entry', [
        None, 'x', {}, {'render_meta': 'x'},
        {'render_meta': {'sections': [None, 'x', {'name': 's', 'fields': 'a'}], 'summary': {'fields': 'a'},
                         'externals': 'x'}},
        {'render_meta': {'summary': 'x', 'externals': [None, {'name': 'l', 'fields': None}]}},
    ], ids=['none', 'string', 'empty', 'render-meta-string', 'malformed-lists', 'malformed-holders'])
    def test_a_malformed_document_yields_nothing(self, entry: Any) -> None:
        """Left for the rules to answer"""
        assert not list(reference_lists(entry))


class TestAnImportDropsEveryStaleName:
    """drop_unresolvable_references without a stored Type"""

    def test_each_place_loses_its_stale_names_and_keeps_the_rest(self) -> None:
        """In document order, object_id kept"""
        entry = _type(['a', 'b'], [_section('main', ['a', 'ghost']), _section('mds', ['b'], ['old'])],
                      ['gone', 'a'], [_link('wiki', ['object_id', 'lost'])])

        dropped = drop_unresolvable_references(entry)

        assert dropped == [
            DroppedReference(TypeReferencePlace.SECTION, 'main', FIELDS, 'ghost'),
            DroppedReference(TypeReferencePlace.SECTION, 'mds', HIDDEN, 'old'),
            DroppedReference(TypeReferencePlace.SUMMARY, None, FIELDS, 'gone'),
            DroppedReference(TypeReferencePlace.EXTERNAL, 'wiki', FIELDS, 'lost')]
        meta = entry['render_meta']
        assert [meta['sections'][0][FIELDS], meta['sections'][1][HIDDEN], meta['summary'][FIELDS],
                meta['externals'][0][FIELDS]] == [['a'], [], ['a'], ['object_id']]
        assert validate_type_structure(entry) is None

    def test_a_sound_type_is_left_as_it_is(self) -> None:
        """Nothing dropped, every list the same object"""
        entry = _type(['a'], [_section('main', ['a'])], ['a'], [_link('wiki', ['a'])])
        lists = [ref.names for ref in reference_lists(entry)]

        assert not drop_unresolvable_references(entry)
        assert [ref.names for ref in reference_lists(entry)] == lists
        assert all(new is old for new, old in zip((ref.names for ref in reference_lists(entry)), lists))

    def test_a_non_string_section_entry_is_left_for_the_rules(self) -> None:
        """Not a name"""
        entry = _type(['a'], [_section('main', ['a', 5])])

        drop_unresolvable_references(entry)

        assert entry['render_meta']['sections'][0][FIELDS] == ['a', 5]

    @pytest.mark.parametrize('entry', [None, 'x', []], ids=['none', 'string', 'list'])
    def test_no_document_drops_nothing(self, entry: Any) -> None:
        """Nothing to repair"""
        assert not drop_unresolvable_references(entry)


class TestAnUpdateDropsOnlyWhatItInherited:
    """drop_unresolvable_references with the stored Type"""

    def test_a_name_the_stored_type_carried_in_the_same_list_is_dropped(self) -> None:
        """The stale stored type, sent back as read"""
        stored = _type(['a'], [_section('main', ['a', 'ghost'])], ['ghost'], [_link('wiki', ['ghost'])])
        payload = copy.deepcopy(stored)

        assert len(drop_unresolvable_references(payload, stored)) == 3
        assert validate_type_structure(payload) is None

    def test_a_name_of_a_field_the_update_removes_is_dropped_everywhere(self) -> None:
        """Section, summary and link lose the removed field"""
        stored = _type(['a', 'b'], [_section('main', ['a', 'b'])], ['b'], [_link('wiki', ['b'])])
        payload = copy.deepcopy(stored)
        payload['fields'] = payload['fields'][:1]

        dropped = drop_unresolvable_references(payload, stored)

        assert [(ref.place, ref.name) for ref in dropped] == [
            (TypeReferencePlace.SECTION, 'b'), (TypeReferencePlace.SUMMARY, 'b'), (TypeReferencePlace.EXTERNAL, 'b')]

    def test_a_renamed_link_still_loses_the_removed_field(self) -> None:
        """Matched by its name, the link is a new list - the removed field still goes"""
        stored = _type(['a', 'b'], [_section('main', ['a', 'b'])], externals=[_link('wiki', ['b', 'a'])])
        payload = _type(['a'], [_section('main', ['a'])], externals=[_link('docs', ['b', 'a'])])

        dropped = drop_unresolvable_references(payload, stored)

        assert dropped == [DroppedReference(TypeReferencePlace.EXTERNAL, 'docs', FIELDS, 'b')]
        assert payload['render_meta']['externals'][0][FIELDS] == ['a']

    def test_a_name_the_update_newly_writes_is_kept_for_the_rules(self) -> None:
        """Never declared, never carried - the rules refuse it"""
        stored = _type(['a'], [_section('main', ['a'])], ['a'], [_link('wiki', ['a'])])
        payload = _type(['a'], [_section('main', ['a', 'ghost'])], ['a', 'ghost'], [_link('wiki', ['ghost'])])

        assert not drop_unresolvable_references(payload, stored)
        assert validate_type_structure(payload) is not None

    def test_a_stale_name_moved_to_another_list_is_kept(self) -> None:
        """Carried, but not in that section"""
        stored = _type(['a'], [_section('main', ['a', 'ghost']), _section('other', [])])
        payload = _type(['a'], [_section('main', ['a']), _section('other', ['ghost'])])

        assert not drop_unresolvable_references(payload, stored)
