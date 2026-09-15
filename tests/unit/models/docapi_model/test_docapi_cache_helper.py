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
Unit tests for cmdb.models.docapi_model.docapi_cache_helper.cache_objects_and_types

Pure tests with mocked managers: verifies missing objects and their referenced types are bulk-loaded
into the shared caches, and that nothing is fetched when both caches are already warm.
"""
from unittest.mock import Mock

from cmdb.models.docapi_model.docapi_cache_helper import cache_objects_and_types
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: str = 'public_id'
TYPE_ID: str = 'type_id'

SERVER_TYPE: int = 10
APP_TYPE: int = 20


def _managers(objects: list[dict], types: list[dict]) -> tuple[Mock, Mock]:
    """Returns (objects_manager, types_manager) mocks whose find() yields the given docs."""
    objects_manager = Mock()
    objects_manager.find.return_value = objects
    types_manager = Mock()
    types_manager.find.return_value = types
    return objects_manager, types_manager


class TestCacheObjectsAndTypes:
    """cache_objects_and_types fills both caches in place with minimal queries."""

    def test_loads_missing_objects_and_types(self) -> None:
        """A missing object is fetched, then its type is fetched into the type cache."""
        object_cache = {}
        type_cache = {}
        objects_manager, types_manager = _managers(
            [{PUBLIC_ID: 2, TYPE_ID: APP_TYPE}],
            [{PUBLIC_ID: APP_TYPE}],
        )

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager)

        assert object_cache == {2: {PUBLIC_ID: 2, TYPE_ID: APP_TYPE}}
        assert type_cache == {APP_TYPE: {PUBLIC_ID: APP_TYPE}}
        objects_manager.find.assert_called_once_with(criteria={PUBLIC_ID: {'$in': [2]}})

    def test_already_cached_object_not_refetched(self) -> None:
        """An object already in the cache triggers no object query."""
        object_cache = {1: {PUBLIC_ID: 1, TYPE_ID: SERVER_TYPE}}
        type_cache = {SERVER_TYPE: {PUBLIC_ID: SERVER_TYPE}}
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([1], object_cache, type_cache, objects_manager, types_manager)

        objects_manager.find.assert_not_called()
        types_manager.find.assert_not_called()

    def test_type_query_covers_all_cached_objects(self) -> None:
        """Types are resolved for every cached object still missing a type, in one bulk query."""
        object_cache = {1: {PUBLIC_ID: 1, TYPE_ID: SERVER_TYPE}}
        type_cache = {}
        objects_manager, types_manager = _managers(
            [{PUBLIC_ID: 2, TYPE_ID: APP_TYPE}],
            [{PUBLIC_ID: SERVER_TYPE}, {PUBLIC_ID: APP_TYPE}],
        )

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager)

        types_manager.find.assert_called_once()
        assert set(type_cache) == {SERVER_TYPE, APP_TYPE}

    def test_objects_without_type_id_skipped_for_types(self) -> None:
        """An object carrying no type_id contributes no type lookup."""
        object_cache = {}
        type_cache = {}
        objects_manager, types_manager = _managers([{PUBLIC_ID: 2}], [])

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager)

        types_manager.find.assert_not_called()
