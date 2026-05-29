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
Unit tests for cmdb.framework.ci_explorer.relations
"""
from typing import Any

from cmdb.framework.ci_explorer.relations import (
    DirectionalEdge,
    build_relation_criteria,
    collect_linked_object_ids,
    split_object_relation_direction,
)
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_ID: int = 100
LINKED_ID: int = 200
TARGET_TYPE_ID: int = 10
LINKED_TYPE_ID: int = 11


def _relation_doc(public_id: int = 500) -> dict[str, Any]:
    """Builds a CmdbRelation doc with distinct parent/child labels for direction assertions."""
    return {
        'public_id': public_id,
        'relation_name': 'connected',
        'relation_name_parent': 'hosts',
        'relation_name_child': 'hosted_by',
        'relation_icon_parent': 'fa-arrow-right',
        'relation_icon_child': 'fa-arrow-left',
        'relation_color_parent': '#33aa33',
        'relation_color_child': '#aa3333',
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_relation_criteria                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_relation_criteria_no_filters_emits_plain_or_clause() -> None:
    """No filters: criteria is just the two-clause $or over parent/child id"""
    criteria = build_relation_criteria(TARGET_ID, frozenset(), frozenset())

    assert criteria == {
        '$or': [
            {'relation_parent_id': TARGET_ID},
            {'relation_child_id': TARGET_ID},
        ],
    }


def test_build_relation_criteria_with_types_filter_constrains_other_side() -> None:
    """types_filter is applied to the OPPOSITE side of each $or clause"""
    criteria = build_relation_criteria(TARGET_ID, frozenset({7, 9}), frozenset())

    or_clauses = criteria['$or']
    parent_branch = next(c for c in or_clauses if 'relation_parent_id' in c)
    child_branch = next(c for c in or_clauses if 'relation_child_id' in c)
    assert parent_branch['relation_parent_id'] == TARGET_ID
    assert set(parent_branch['relation_child_type_id']['$in']) == {7, 9}
    assert child_branch['relation_child_id'] == TARGET_ID
    assert set(child_branch['relation_parent_type_id']['$in']) == {7, 9}


def test_build_relation_criteria_with_relations_filter_ands_relation_id() -> None:
    """relations_filter becomes a top-level relation_id $in alongside the $or"""
    criteria = build_relation_criteria(TARGET_ID, frozenset(), frozenset({500, 501}))

    assert '$or' in criteria
    assert set(criteria['relation_id']['$in']) == {500, 501}


def test_build_relation_criteria_combines_both_filters() -> None:
    """Both filters AND together: types restrict $or clauses, relations restrict relation_id"""
    criteria = build_relation_criteria(TARGET_ID, frozenset({7}), frozenset({500}))

    assert set(criteria['relation_id']['$in']) == {500}
    for clause in criteria['$or']:
        assert clause.get('relation_parent_type_id') or clause.get('relation_child_type_id')


# -------------------------------------------------------------------------------------------------------------------- #
#                                          collect_linked_object_ids                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_linked_object_ids_returns_empty_for_empty_input() -> None:
    """No object_relations means no linked ids"""
    assert collect_linked_object_ids([], TARGET_ID) == set()


def test_collect_linked_object_ids_collects_child_when_target_is_parent() -> None:
    """When the target is the parent, the child id is collected as linked"""
    rels = [{'relation_parent_id': TARGET_ID, 'relation_child_id': LINKED_ID}]

    assert collect_linked_object_ids(rels, TARGET_ID) == {LINKED_ID}


def test_collect_linked_object_ids_collects_parent_when_target_is_child() -> None:
    """When the target is the child, the parent id is collected as linked"""
    rels = [{'relation_parent_id': LINKED_ID, 'relation_child_id': TARGET_ID}]

    assert collect_linked_object_ids(rels, TARGET_ID) == {LINKED_ID}


def test_collect_linked_object_ids_collects_distinct_ids_across_multiple_relations() -> None:
    """Multiple object_relations contribute their non-target end; duplicates collapse"""
    rels = [
        {'relation_parent_id': TARGET_ID, 'relation_child_id': 200},
        {'relation_parent_id': TARGET_ID, 'relation_child_id': 201},
        {'relation_parent_id': 202, 'relation_child_id': TARGET_ID},
        {'relation_parent_id': TARGET_ID, 'relation_child_id': 200},
    ]

    assert collect_linked_object_ids(rels, TARGET_ID) == {200, 201, 202}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       split_object_relation_direction                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_split_direction_returns_child_edge_when_target_is_parent() -> None:
    """Target as parent → linked_is_child=True, edge points target→linked, uses parent-side labels"""
    obj_rel = {
        'relation_parent_id': TARGET_ID,
        'relation_parent_type_id': TARGET_TYPE_ID,
        'relation_child_id': LINKED_ID,
        'relation_child_type_id': LINKED_TYPE_ID,
    }

    result = split_object_relation_direction(obj_rel, TARGET_ID, _relation_doc())

    assert isinstance(result, DirectionalEdge)
    assert result.linked_is_child is True
    assert result.linked_id == LINKED_ID
    assert result.linked_type_id == LINKED_TYPE_ID
    assert result.edge_from == TARGET_ID
    assert result.edge_to == LINKED_ID
    assert result.relation_color == '#33aa33'
    assert result.edge_relation_name == 'hosts'
    assert result.edge_relation_icon == 'fa-arrow-right'


def test_split_direction_returns_parent_edge_when_target_is_child() -> None:
    """Target as child → linked_is_child=False, edge points linked→target, uses child-side labels"""
    obj_rel = {
        'relation_parent_id': LINKED_ID,
        'relation_parent_type_id': LINKED_TYPE_ID,
        'relation_child_id': TARGET_ID,
        'relation_child_type_id': TARGET_TYPE_ID,
    }

    result = split_object_relation_direction(obj_rel, TARGET_ID, _relation_doc())

    assert isinstance(result, DirectionalEdge)
    assert result.linked_is_child is False
    assert result.linked_id == LINKED_ID
    assert result.edge_from == LINKED_ID
    assert result.edge_to == TARGET_ID
    assert result.relation_color == '#aa3333'
    assert result.edge_relation_name == 'hosted_by'
    assert result.edge_relation_icon == 'fa-arrow-left'


def test_split_direction_returns_none_when_target_on_neither_side() -> None:
    """Defensive guard: a malformed object_relation where target appears on neither end yields None"""
    obj_rel = {
        'relation_parent_id': 999,
        'relation_parent_type_id': 88,
        'relation_child_id': 998,
        'relation_child_type_id': 77,
    }

    assert split_object_relation_direction(obj_rel, TARGET_ID, _relation_doc()) is None
