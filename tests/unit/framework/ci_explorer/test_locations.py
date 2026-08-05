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
Unit tests for cmdb.framework.ci_explorer.locations

Uses MagicMock managers so the unit tests don't touch the DB; the live-DB integration
of the location grafters is covered by the functional smoke test
``test_with_locations_flips_location_semantics``
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from cmdb.framework.ci_explorer.locations import (
    ROOT_LOCATION_SENTINEL_PARENT,
    collect_location_children_objects,
    collect_location_parent_object,
)
# -------------------------------------------------------------------------------------------------------------------- #

TARGET_LOCATION_ID: int = 1001
PARENT_LOCATION_ID: int = 1000
TARGET_TYPE_ID: int = 10
PARENT_OBJECT_ID: int = 200


def _target_location_with_parent(parent_id: int) -> dict[str, Any]:
    """Builds a target location dict whose 'parent' attribute is configurable per test."""
    return {'public_id': TARGET_LOCATION_ID, 'parent': parent_id, 'object_id': 100}


# -------------------------------------------------------------------------------------------------------------------- #
#                                       collect_location_parent_object                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_location_parent_object_returns_none_when_parent_is_root_sentinel() -> None:
    """When target_location.parent == 1 (root sentinel), no parent object is grafted"""
    locations_manager = MagicMock()
    objects_manager = MagicMock()

    result = collect_location_parent_object(
        _target_location_with_parent(ROOT_LOCATION_SENTINEL_PARENT),
        frozenset(), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result is None
    locations_manager.get_location.assert_not_called()


def test_collect_location_parent_object_returns_none_when_no_remaining_slots() -> None:
    """When item_limit is active and remaining<=0, the parent is not loaded"""
    locations_manager = MagicMock()
    objects_manager = MagicMock()

    result = collect_location_parent_object(
        _target_location_with_parent(PARENT_LOCATION_ID),
        frozenset(), remaining=0, item_limit_active=True,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result is None
    locations_manager.get_location.assert_not_called()


def test_collect_location_parent_object_returns_none_when_parent_location_missing() -> None:
    """A missing parent location row short-circuits to None"""
    locations_manager = MagicMock()
    locations_manager.get_location.return_value = None
    objects_manager = MagicMock()

    result = collect_location_parent_object(
        _target_location_with_parent(PARENT_LOCATION_ID),
        frozenset(), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result is None
    objects_manager.get_object.assert_not_called()


def test_collect_location_parent_object_returns_none_when_types_filter_excludes() -> None:
    """When types_filter is active and the parent object's type_id is not in it, returns None"""
    locations_manager = MagicMock()
    locations_manager.get_location.return_value = {'public_id': PARENT_LOCATION_ID, 'object_id': PARENT_OBJECT_ID}
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = {'public_id': PARENT_OBJECT_ID, 'type_id': 999}

    result = collect_location_parent_object(
        _target_location_with_parent(PARENT_LOCATION_ID),
        frozenset({TARGET_TYPE_ID}), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result is None


def test_collect_location_parent_object_returns_parent_object_in_happy_path() -> None:
    """The fully-resolved parent CmdbObject is returned for the orchestrator to enrich"""
    expected = {'public_id': PARENT_OBJECT_ID, 'type_id': TARGET_TYPE_ID}
    locations_manager = MagicMock()
    locations_manager.get_location.return_value = {'public_id': PARENT_LOCATION_ID, 'object_id': PARENT_OBJECT_ID}
    objects_manager = MagicMock()
    objects_manager.get_object.return_value = expected

    result = collect_location_parent_object(
        _target_location_with_parent(PARENT_LOCATION_ID),
        frozenset({TARGET_TYPE_ID}), remaining=10, item_limit_active=True,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result is expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                      collect_location_children_objects                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_location_children_objects_returns_empty_when_no_remaining_slots() -> None:
    """When item_limit is active and remaining<=0, no DB call is made"""
    locations_manager = MagicMock()
    objects_manager = MagicMock()

    result = collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset(), remaining=0, item_limit_active=True,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result == []
    locations_manager.get_locations_by.assert_not_called()


def test_collect_location_children_objects_returns_empty_when_no_child_locations() -> None:
    """No child locations under the target → empty result, no objects query"""
    locations_manager = MagicMock()
    locations_manager.get_locations_by.return_value = []
    objects_manager = MagicMock()

    result = collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset(), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert result == []
    objects_manager.find.assert_not_called()


def test_collect_location_children_objects_passes_object_ids_to_find() -> None:
    """The object_ids on child locations become the public_id $in clause"""
    locations_manager = MagicMock()
    locations_manager.get_locations_by.return_value = [
        SimpleNamespace(object_id=201),
        SimpleNamespace(object_id=202),
    ]
    objects_manager = MagicMock()
    objects_manager.find.return_value = [
        {'public_id': 201, 'type_id': TARGET_TYPE_ID},
        {'public_id': 202, 'type_id': TARGET_TYPE_ID},
    ]

    result = collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset(), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert [obj['public_id'] for obj in result] == [201, 202]
    criteria = objects_manager.find.call_args.kwargs['criteria']
    assert set(criteria['public_id']['$in']) == {201, 202}
    assert 'type_id' not in criteria


def test_collect_location_children_objects_adds_type_id_filter_to_mongo_query() -> None:
    """B2 fix: types_filter is applied at the Mongo query level, not post-load"""
    locations_manager = MagicMock()
    locations_manager.get_locations_by.return_value = [SimpleNamespace(object_id=201)]
    objects_manager = MagicMock()
    objects_manager.find.return_value = []

    collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset({TARGET_TYPE_ID}), remaining=10, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    criteria = objects_manager.find.call_args.kwargs['criteria']
    assert criteria['type_id']['$in'] == [TARGET_TYPE_ID]


def test_collect_location_children_objects_caps_at_remaining_when_item_limit_active() -> None:
    """When item_limit is active the post-filter list is sliced to remaining"""
    locations_manager = MagicMock()
    locations_manager.get_locations_by.return_value = [
        SimpleNamespace(object_id=201),
        SimpleNamespace(object_id=202),
        SimpleNamespace(object_id=203),
    ]
    objects_manager = MagicMock()
    objects_manager.find.return_value = [
        {'public_id': 201, 'type_id': TARGET_TYPE_ID},
        {'public_id': 202, 'type_id': TARGET_TYPE_ID},
        {'public_id': 203, 'type_id': TARGET_TYPE_ID},
    ]

    result = collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset(), remaining=2, item_limit_active=True,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert len(result) == 2


def test_collect_location_children_objects_skips_cap_when_item_limit_inactive() -> None:
    """When item_limit is inactive the full post-filter list is returned"""
    locations_manager = MagicMock()
    locations_manager.get_locations_by.return_value = [
        SimpleNamespace(object_id=201),
        SimpleNamespace(object_id=202),
        SimpleNamespace(object_id=203),
    ]
    objects_manager = MagicMock()
    objects_manager.find.return_value = [
        {'public_id': 201, 'type_id': TARGET_TYPE_ID},
        {'public_id': 202, 'type_id': TARGET_TYPE_ID},
        {'public_id': 203, 'type_id': TARGET_TYPE_ID},
    ]

    result = collect_location_children_objects(
        {'public_id': TARGET_LOCATION_ID, 'parent': PARENT_LOCATION_ID},
        frozenset(), remaining=0, item_limit_active=False,
        locations_manager=locations_manager, objects_manager=objects_manager,
    )

    assert len(result) == 3
