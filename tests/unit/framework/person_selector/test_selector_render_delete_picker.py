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
Unit tests for the render, delete and picker modules of cmdb.framework.person_selector

The managers are stubs; the statements run against MongoDB in the integration tier. Pinned:

  - render: a flat selector keeps the visible ids and gets its ``persons``; a row keeps the visible ids; an unreadable,
    deleted or unmarked object is withheld; nothing is read without a selector or a selection
  - delete: the scrub reads no object without a selector type, and its update matches only the selector types' objects
    holding a deleted id; the blocker reads no object without a required selector
  - picker: hidden types are never offered; browsing asks for active objects and escapes the search; ``ids`` resolves
    without the active filter; the page is skipped and limited
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from cmdb.framework.rendering.render_result import RenderResult
from cmdb.framework.person_selector.selector_render import apply_person_selector_render, selection_entry
from cmdb.framework.person_selector.selector_delete import (
    build_selector_scrub_update,
    find_required_selector_blockers,
    scrub_person_selectors,
)
from cmdb.framework.person_selector.selector_picker import PickerQuery, find_person_choices
from cmdb.models.special_type_model.special_type_enum import SpecialType
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_TYPE: int = 31
GROUP_TYPE: int = 32
HIDDEN_TYPE: int = 33
PERSON: int = 101
GROUP: int = 102
HIDDEN: int = 103
GONE: int = 109
OWNER: str = 'owner'
MEMBERS: str = 'members'

OBJECT_DOCUMENTS: dict[int, dict[str, Any]] = {
    PERSON: {'public_id': PERSON, 'type_id': PERSON_TYPE, 'fields': [{'name': 'display_name', 'value': 'Ada'}]},
    GROUP: {'public_id': GROUP, 'type_id': GROUP_TYPE, 'fields': [{'name': 'name', 'value': 'Ops'}]},
    HIDDEN: {'public_id': HIDDEN, 'type_id': HIDDEN_TYPE, 'fields': [{'name': 'display_name', 'value': 'Eve'}]},
}
TYPE_DOCUMENTS: dict[int, dict[str, Any]] = {
    PERSON_TYPE: {'public_id': PERSON_TYPE, 'label': 'Person', 'special_type': 'PERSON'},
    GROUP_TYPE: {'public_id': GROUP_TYPE, 'label': 'Team', 'special_type': 'PERSON_GROUP'},
    HIDDEN_TYPE: {'public_id': HIDDEN_TYPE, 'label': 'Secret', 'special_type': 'PERSON'},
}


def _managers() -> tuple[MagicMock, MagicMock]:
    """Stub managers answering the projected reads"""
    objects, types = MagicMock(), MagicMock()
    objects.find.side_effect = lambda criteria, **_kwargs: [
        OBJECT_DOCUMENTS[object_id] for object_id in criteria['public_id']['$in'] if object_id in OBJECT_DOCUMENTS
    ]
    types.find.side_effect = lambda criteria, **_kwargs: [
        TYPE_DOCUMENTS[type_id] for type_id in criteria['public_id']['$in'] if type_id in TYPE_DOCUMENTS
    ]

    return objects, types


def _selector_type() -> Any:
    """A type with a single and a multiple selector"""
    return SimpleNamespace(fields=[
        {'type': 'person', 'name': OWNER, 'selectable': ['PERSON'], 'multiple': False},
        {'type': 'person', 'name': MEMBERS, 'selectable': ['PERSON', 'PERSON_GROUP'], 'multiple': True},
    ])


def _result(owner: Any, members: Any, row: Any) -> RenderResult:
    """A rendered object holding both selectors flat and the multiple one in a row"""
    result = RenderResult()
    result.fields = [{'name': OWNER, 'type': 'person', 'value': owner},
                     {'name': MEMBERS, 'type': 'person', 'value': members}]
    result.multi_data_sections = [{'section_id': 's', 'values': [
        {'multi_data_id': 0, 'data': [{'name': MEMBERS, 'value': row}]},
    ]}]

    return result


class TestRender:
    """apply_person_selector_render"""

    def test_visible_selections_are_expanded_and_the_rest_withheld(self) -> None:
        """Flat: kept ids + persons; row: kept ids; unreadable and deleted ids withheld"""
        objects, types = _managers()
        result = _result(HIDDEN, [GROUP, HIDDEN, PERSON, GONE], [HIDDEN, PERSON])

        apply_person_selector_render([(result, _selector_type())], objects, types, lambda: frozenset({HIDDEN_TYPE}))

        owner, members = result.fields
        assert (owner['value'], owner['persons']) == (None, [])
        assert members['value'] == [GROUP, PERSON]
        assert members['persons'] == [
            {'object_id': GROUP, 'type_id': GROUP_TYPE, 'type_label': 'Team', 'kind': 'PERSON_GROUP', 'label': 'Ops'},
            {'object_id': PERSON, 'type_id': PERSON_TYPE, 'type_label': 'Person', 'kind': 'PERSON', 'label': 'Ada'},
        ]
        assert result.multi_data_sections[0]['values'][0]['data'][0]['value'] == [PERSON]

    def test_nothing_is_read_without_a_selector_or_a_selection(self) -> None:
        """A type without selectors, and selectors holding nothing"""
        objects, types = _managers()
        plain = RenderResult()

        apply_person_selector_render([(plain, SimpleNamespace(fields=[]))], objects, types, frozenset)
        apply_person_selector_render([(_result(None, [], []), _selector_type())], objects, types, frozenset)

        objects.find.assert_not_called()

    def test_the_label_is_the_kinds_base_field(self) -> None:
        """A missing label field is None"""
        entry = selection_entry({'public_id': 1, 'fields': []}, TYPE_DOCUMENTS[GROUP_TYPE])

        assert entry['label'] is None and entry['kind'] == 'PERSON_GROUP'


class TestDelete:
    """scrub_person_selectors, build_selector_scrub_update, find_required_selector_blockers"""

    def test_no_selector_type_reads_no_object(self) -> None:
        """The types are read once; nothing else"""
        objects, types = MagicMock(), MagicMock()
        types.find.return_value = []

        scrub_person_selectors(objects, types, [PERSON])

        objects.apply_raw_updates.assert_not_called()

    def test_the_scrub_matches_only_selector_types_holding_a_deleted_id(self) -> None:
        """Flat or in a row; ids as literals"""
        update = build_selector_scrub_update([7, 5], [PERSON])

        assert update.filter_query['type_id'] == {'$in': [5, 7]}
        assert update.filter_query['$or'] == [
            {'fields': {'$elemMatch': {'type': 'person', 'value': {'$in': [PERSON]}}}},
            {'multi_data_sections.values.data': {'$elemMatch': {'type': 'person', 'value': {'$in': [PERSON]}}}},
        ]
        assert "{'$literal': [101]}" in repr(update.update)

    def test_no_required_selector_reads_no_object(self) -> None:
        """Nothing can block"""
        objects, types = MagicMock(), MagicMock()
        types.find.return_value = []

        assert find_required_selector_blockers(objects, types, [PERSON]) == []
        objects.aggregate_all.assert_not_called()


class TestPicker:
    """find_person_choices"""

    @staticmethod
    def _run(query: PickerQuery, hidden: frozenset[int] = frozenset()) -> tuple[Any, MagicMock]:
        objects, types = MagicMock(), MagicMock()
        types.find.return_value = list(TYPE_DOCUMENTS.values())
        objects.count_documents.return_value = 1
        objects.find.return_value = [OBJECT_DOCUMENTS[PERSON]]

        return find_person_choices(objects, types, lambda: hidden, query), objects

    def test_browsing_asks_for_active_objects_of_visible_types(self) -> None:
        """The search is escaped and matched on each kind's label field"""
        query = PickerQuery([SpecialType.PERSON, SpecialType.PERSON_GROUP], 'a.b', None, 2, 10)
        (results, total), objects = self._run(query, hidden=frozenset({HIDDEN_TYPE}))

        criteria = objects.find.call_args.args[0]
        assert criteria['type_id'] == {'$in': [PERSON_TYPE, GROUP_TYPE]}
        assert criteria['active'] is True
        assert criteria['$or'][0]['fields']['$elemMatch'] == {
            'name': 'display_name', 'value': {'$regex': 'a\\.b', '$options': 'i'}}
        assert objects.find.call_args.kwargs['skip'] == 10 and objects.find.call_args.kwargs['limit'] == 10
        assert (results[0]['label'], total) == ('Ada', 1)

    def test_ids_are_resolved_without_the_active_filter(self) -> None:
        """An inactive person a selector still holds keeps its label"""
        _, objects = self._run(PickerQuery([SpecialType.PERSON], None, [PERSON, PERSON], 1, 25))

        criteria = objects.find.call_args.args[0]
        assert criteria['public_id'] == {'$in': [PERSON]}
        assert 'active' not in criteria

    def test_no_visible_type_reads_no_object(self) -> None:
        """Every marked type hidden"""
        (results, total), objects = self._run(PickerQuery([SpecialType.PERSON], None, None, 1, 25),
                                              hidden=frozenset(TYPE_DOCUMENTS))

        assert (results, total) == ([], 0)
        objects.find.assert_not_called()
