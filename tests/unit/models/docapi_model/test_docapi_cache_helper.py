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

import pytest

from cmdb.models.docapi_model import docapi_cache_helper
from cmdb.models.docapi_model.docapi_cache_helper import cache_objects_and_types
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: str = 'public_id'
TYPE_ID: str = 'type_id'

SERVER_TYPE: int = 10
APP_TYPE: int = 20

# The user the document is built for; its denied types are stubbed per test
REQUEST_USER: Mock = Mock(name='request_user')


@pytest.fixture(autouse=True)
def _nothing_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller's group may read every type unless a test says otherwise."""
    monkeypatch.setattr(docapi_cache_helper, 'resolve_denied_type_ids', lambda _user, _permission: [])


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

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager, REQUEST_USER)

        assert object_cache == {2: {PUBLIC_ID: 2, TYPE_ID: APP_TYPE}}
        assert type_cache == {APP_TYPE: {PUBLIC_ID: APP_TYPE}}
        objects_manager.find.assert_called_once_with(criteria={PUBLIC_ID: {'$in': [2]}})

    def test_already_cached_object_not_refetched(self) -> None:
        """An object already in the cache triggers no object query."""
        object_cache = {1: {PUBLIC_ID: 1, TYPE_ID: SERVER_TYPE}}
        type_cache = {SERVER_TYPE: {PUBLIC_ID: SERVER_TYPE}}
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([1], object_cache, type_cache, objects_manager, types_manager, REQUEST_USER)

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

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager, REQUEST_USER)

        types_manager.find.assert_called_once()
        assert set(type_cache) == {SERVER_TYPE, APP_TYPE}

    def test_objects_without_type_id_skipped_for_types(self) -> None:
        """An object carrying no type_id contributes no type lookup."""
        object_cache = {}
        type_cache = {}
        objects_manager, types_manager = _managers([{PUBLIC_ID: 2}], [])

        cache_objects_and_types([2], object_cache, type_cache, objects_manager, types_manager, REQUEST_USER)

        types_manager.find.assert_not_called()


DENIED_TYPE: int = 30


class TestTheCallersAcl:
    """Only objects of types the caller may READ enter the cache."""

    def test_the_denied_types_are_excluded_from_the_object_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The object query carries the caller's denied types - a hidden object never reaches the cache"""
        monkeypatch.setattr(docapi_cache_helper, 'resolve_denied_type_ids', lambda _user, _permission: [DENIED_TYPE])
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([2], {}, {}, objects_manager, types_manager, REQUEST_USER)

        criteria: dict = objects_manager.find.call_args.kwargs['criteria']
        assert criteria == {PUBLIC_ID: {'$in': [2]}, TYPE_ID: {'$nin': [DENIED_TYPE]}}

    def test_nothing_denied_leaves_the_query_plain(self) -> None:
        """A group that may read every type costs no extra condition"""
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([2], {}, {}, objects_manager, types_manager, REQUEST_USER)

        assert objects_manager.find.call_args.kwargs['criteria'] == {PUBLIC_ID: {'$in': [2]}}

    def test_the_denied_types_are_resolved_for_read(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A document only reads, so READ is the permission asked"""
        asked: list = []
        monkeypatch.setattr(docapi_cache_helper, 'resolve_denied_type_ids',
                            lambda user, permission: asked.append((user, permission)) or [])
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([2], {}, {}, objects_manager, types_manager, REQUEST_USER)

        assert asked == [(REQUEST_USER, docapi_cache_helper.AccessControlPermission.READ)]

    def test_a_warm_cache_resolves_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing missing, nothing asked - not even the denied types"""
        asked: list = []
        monkeypatch.setattr(docapi_cache_helper, 'resolve_denied_type_ids',
                            lambda user, permission: asked.append(user) or [])
        objects_manager, types_manager = _managers([], [])

        cache_objects_and_types([2], {2: {PUBLIC_ID: 2}}, {}, objects_manager, types_manager, REQUEST_USER)

        assert not asked
