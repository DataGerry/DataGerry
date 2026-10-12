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
Unit tests for cmdb.framework.ci_explorer.persons

Pure tests: the managers are stubs answering find() from a callable, so the two queries are told apart by
their criteria. Pinned here:

  - children: the persons and groups the focal object's person fields select (top-level and MDS rows), each
    labelled with the selecting field's label - for a group, its members
  - parents: the objects whose person fields select the focal object, labelled with THEIR field's label
  - the focal object never neighbours itself; the type filter and the slot budget are honoured
  - the edge carries metadata.source='person' and the field label as both relation name and label
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.ci_explorer.persons import (
    PERSON_METADATA_SOURCE,
    PERSON_RELATION_COLOR,
    PERSON_RELATION_ICON,
    PERSON_RELATION_LABEL,
    PersonNeighbour,
    collect_person_neighbours,
    compose_person_edge,
)
from tests.utils.person_stubs import group_object, person_field, person_object, selection
# -------------------------------------------------------------------------------------------------------------------- #

ASSET_TYPE: int = 60
TICKET_TYPE: int = 61
GROUP_TYPE: int = 502

ASSET: int = 700
ADA: int = 701
BOB: int = 702
SECURITY: int = 703
TICKET: int = 704

ASSET_TYPE_DOC: dict[str, Any] = {
    'public_id': ASSET_TYPE,
    'fields': [
        {'type': 'text', 'name': 'hostname', 'label': 'Hostname'},
        person_field('owner', 'Owner', ref_kind='BOTH'),
        person_field('team', 'Team', ref_kind='PERSON', multiple=True),
        person_field('contact', '', ref_kind='PERSON'),
    ],
}
TICKET_TYPE_DOC: dict[str, Any] = {'public_id': TICKET_TYPE, 'fields': [person_field('assignee', 'Assignee')]}
GROUP_TYPE_DOC: dict[str, Any] = {
    'public_id': GROUP_TYPE,
    'fields': [person_field('dg-person-group-members', 'Members', ref_kind='PERSON', multiple=True)],
}

ALL_DOCS: list[dict[str, Any]] = [
    person_object(ADA, 'Ada'),
    person_object(BOB, 'Bob'),
    group_object(SECURITY, 'Security', [ADA]),
]


def _asset(**values: Any) -> dict[str, Any]:
    return {'public_id': ASSET, 'type_id': ASSET_TYPE,
            'fields': [{'name': name, 'type': 'person', 'value': value} for name, value in values.items()]}


def _managers(parents: list[dict[str, Any]] | None = None) -> tuple[MagicMock, MagicMock]:
    """find() answers the children query from ALL_DOCS by '$in', the parent query ('$or') with the given parents"""
    types = {doc['public_id']: doc for doc in (ASSET_TYPE_DOC, TICKET_TYPE_DOC, GROUP_TYPE_DOC)}
    types_manager = MagicMock()
    types_manager.get_type.side_effect = types.get

    def find(criteria: dict[str, Any]) -> list[dict[str, Any]]:
        type_ids = (criteria.get('type_id') or {}).get('$in')

        if '$or' in criteria:
            found = list(parents or [])
        else:
            found = [doc for doc in ALL_DOCS if doc['public_id'] in criteria['public_id']['$in']]

        return [doc for doc in found if type_ids is None or doc['type_id'] in type_ids]

    objects_manager = MagicMock()
    objects_manager.find.side_effect = find

    return objects_manager, types_manager


def _collect(target: dict[str, Any], objects_manager: Any, types_manager: Any, **overrides: Any) -> list[PersonNeighbour]:
    arguments: dict[str, Any] = {
        'target_id': target['public_id'],
        'target_object': target,
        'include_parents': True,
        'include_children': True,
        'types_filter': frozenset(),
        'remaining': 0,
        'item_limit_active': False,
        'objects_manager': objects_manager,
        'types_manager': types_manager,
    }
    arguments.update(overrides)

    return collect_person_neighbours(**arguments)


def _summary(neighbours: list[PersonNeighbour]) -> list[tuple[int, bool, str]]:
    return [(n.neighbour_object['public_id'], n.is_child_of_target, n.field_label) for n in neighbours]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       children                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_selected_persons_and_groups_are_children_labelled_by_their_field() -> None:
    """A group as owner, two persons in the team"""
    objects_manager, types_manager = _managers()
    target = _asset(owner=selection('PERSON_GROUP', SECURITY), team=[selection('PERSON', ADA), selection('PERSON', BOB)])

    neighbours = _collect(target, objects_manager, types_manager, include_parents=False)

    assert sorted(_summary(neighbours)) == [(ADA, True, 'Team'), (BOB, True, 'Team'), (SECURITY, True, 'Owner')]


def test_a_person_selected_twice_is_labelled_by_the_first_field() -> None:
    """One child per neighbour, not one per selecting field"""
    objects_manager, types_manager = _managers()
    target = _asset(owner=selection('PERSON', ADA), team=[selection('PERSON', ADA)])

    assert _summary(_collect(target, objects_manager, types_manager, include_parents=False)) == [(ADA, True, 'Owner')]


def test_a_field_without_a_label_is_labelled_by_its_name() -> None:
    """The edge always has text"""
    objects_manager, types_manager = _managers()

    neighbours = _collect(_asset(contact=selection('PERSON', BOB)), objects_manager, types_manager, include_parents=False)

    assert _summary(neighbours) == [(BOB, True, 'contact')]


def test_a_selection_inside_a_multi_data_section_counts() -> None:
    """The MDS rows are read like the top-level fields"""
    objects_manager, types_manager = _managers()
    target = {'public_id': ASSET, 'type_id': ASSET_TYPE, 'fields': [], 'multi_data_sections': [
        {'section_id': 's', 'values': [{'multi_data_id': 0, 'data': [{'name': 'team', 'value': [selection('PERSON', BOB)]}]}]},
    ]}

    assert _summary(_collect(target, objects_manager, types_manager, include_parents=False)) == [(BOB, True, 'Team')]


def test_a_group_has_its_members_as_children() -> None:
    """Membership is the group's MEMBERS person field"""
    objects_manager, types_manager = _managers()
    group = group_object(SECURITY, 'Security', [ADA, BOB], type_id=GROUP_TYPE)

    neighbours = _collect(group, objects_manager, types_manager, include_parents=False)

    assert sorted(_summary(neighbours)) == [(ADA, True, 'Members'), (BOB, True, 'Members')]


def test_an_object_without_selections_queries_no_children() -> None:
    """Nothing selected, nothing read"""
    objects_manager, types_manager = _managers()

    assert _collect(_asset(owner=None, team=[]), objects_manager, types_manager, include_parents=False) == []
    objects_manager.find.assert_not_called()


def test_the_focal_object_is_never_its_own_neighbour() -> None:
    """A person field selecting the object it sits on is skipped"""
    objects_manager, types_manager = _managers()
    target = _asset(owner=selection('PERSON', ASSET))

    assert _collect(target, objects_manager, types_manager, include_parents=False) == []


def test_the_type_filter_reaches_the_children_query() -> None:
    """A neighbour of a filtered-out type is not collected"""
    objects_manager, types_manager = _managers()
    target = _asset(owner=selection('PERSON_GROUP', SECURITY), team=[selection('PERSON', ADA)])

    neighbours = _collect(target, objects_manager, types_manager, include_parents=False,
                          types_filter=frozenset({GROUP_TYPE}))

    assert _summary(neighbours) == [(SECURITY, True, 'Owner')]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        parents                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_objects_selecting_the_person_are_parents_labelled_by_their_field() -> None:
    """The asset's owner field and the ticket's assignee field both select Ada"""
    asset = _asset(owner=selection('PERSON', ADA))
    ticket = {'public_id': TICKET, 'type_id': TICKET_TYPE,
              'fields': [{'name': 'assignee', 'type': 'person', 'value': selection('PERSON', ADA)}]}
    objects_manager, types_manager = _managers(parents=[asset, ticket])

    neighbours = _collect(person_object(ADA, 'Ada'), objects_manager, types_manager, include_children=False)

    assert _summary(neighbours) == [(ASSET, False, 'Owner'), (TICKET, False, 'Assignee')]


def test_the_parent_query_matches_person_rows_and_excludes_the_target() -> None:
    """Top-level and MDS rows typed 'person' selecting the id; the focal object itself is excluded"""
    objects_manager, types_manager = _managers()

    _collect(person_object(ADA, 'Ada'), objects_manager, types_manager, include_children=False)

    criteria = objects_manager.find.call_args.args[0]
    row_match = {'type': 'person', 'value.id': ADA}
    assert criteria['$or'] == [
        {'fields': {'$elemMatch': row_match}},
        {'multi_data_sections.values.data': {'$elemMatch': row_match}},
    ]
    assert criteria['public_id'] == {'$ne': ADA}


def test_a_group_listing_the_person_is_a_parent() -> None:
    """A person's memberships appear as the groups selecting them"""
    group = group_object(SECURITY, 'Security', [ADA], type_id=GROUP_TYPE)
    objects_manager, types_manager = _managers(parents=[group])

    neighbours = _collect(person_object(ADA, 'Ada'), objects_manager, types_manager, include_children=False)

    assert _summary(neighbours) == [(SECURITY, False, 'Members')]


def test_a_parent_whose_field_cannot_be_named_falls_back_to_the_generic_label() -> None:
    """A parent type that lost its person field definition still yields an edge"""
    orphan = {'public_id': TICKET, 'type_id': 999, 'fields': [{'name': 'x', 'type': 'person', 'value': selection('PERSON', ADA)}]}
    objects_manager, types_manager = _managers(parents=[orphan])

    neighbours = _collect(person_object(ADA, 'Ada'), objects_manager, types_manager, include_children=False)

    assert _summary(neighbours) == [(TICKET, False, PERSON_RELATION_LABEL)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    budget / order                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_children_come_before_parents() -> None:
    """Both directions in one call, children first"""
    asset = _asset(owner=selection('PERSON', BOB))
    objects_manager, types_manager = _managers(parents=[{'public_id': TICKET, 'type_id': TICKET_TYPE, 'fields': [
        {'name': 'assignee', 'type': 'person', 'value': selection('PERSON', ASSET)}]}])

    neighbours = _collect(asset, objects_manager, types_manager)

    assert [n.is_child_of_target for n in neighbours] == [True, False]


def test_the_slot_budget_caps_the_result() -> None:
    """Under an item_limit, no more neighbours than slots remain"""
    objects_manager, types_manager = _managers()
    target = _asset(team=[selection('PERSON', ADA), selection('PERSON', BOB)])

    neighbours = _collect(target, objects_manager, types_manager, include_parents=False,
                          remaining=1, item_limit_active=True)

    assert len(neighbours) == 1


def test_an_exhausted_budget_reads_nothing() -> None:
    """No slot left, no query"""
    objects_manager, types_manager = _managers()

    assert _collect(_asset(owner=selection('PERSON', ADA)), objects_manager, types_manager,
                    remaining=0, item_limit_active=True) == []
    objects_manager.find.assert_not_called()


@pytest.mark.parametrize('include_parents, include_children', [(False, False)])
def test_no_direction_reads_nothing(include_parents: bool, include_children: bool) -> None:
    """Neither direction requested"""
    objects_manager, types_manager = _managers()

    assert _collect(_asset(owner=selection('PERSON', ADA)), objects_manager, types_manager,
                    include_parents=include_parents, include_children=include_children) == []
    objects_manager.find.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                         edge                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compose_person_edge() -> None:
    """No CmdbRelation backs it; name and label are the field label; source='person'"""
    assert compose_person_edge(ASSET, ADA, 'Owner') == {
        'from': ASSET,
        'to': ADA,
        'metadata': {
            'relation_id': None,
            'relation_name': 'Owner',
            'relation_label': 'Owner',
            'relation_icon': PERSON_RELATION_ICON,
            'relation_color': PERSON_RELATION_COLOR,
            'source': PERSON_METADATA_SOURCE,
        },
    }
    assert PERSON_METADATA_SOURCE == 'person'
