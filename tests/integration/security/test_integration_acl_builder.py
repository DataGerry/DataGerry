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
Integration tests for the access-control filter against a real MongoDB

The filter replaced a per-document ``$lookup`` on ``framework.types`` with a single query resolving
the denied types plus a ``type_id: {$nin: ...}`` exclusion. These tests pin the resulting document
set for every ACL shape a stored CmdbType can carry - including the two awkward ones the old
implementation handled by accident: a type whose ``acl`` has no ``activated`` key, and an object
whose ``type_id`` matches no CmdbType at all.

They also pin the stage ORDER of the built query: the ACL filter must run before ``$skip``, or
pagination silently drops rows a restricted user is allowed to see.
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.query_builder.base_query_builder import BaseQueryBuilder
from cmdb.manager.query_builder.builder_parameters import BuilderParameters
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.security.acl.builder import build_denied_types_criteria
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 1
OTHER_GROUP_ID: int = 2

# (type public_id, acl document or None, expected to be readable by GROUP_ID)
TYPE_MATRIX: list[tuple[int, dict[str, Any] | None, bool]] = [
    (96001, None, True),
    (96002, {'activated': False, 'groups': {'includes': {}}}, True),
    (96003, {'activated': True, 'groups': {'includes': {str(GROUP_ID): ['READ', 'CREATE']}}}, True),
    (96004, {'activated': True, 'groups': {'includes': {str(GROUP_ID): ['CREATE']}}}, False),
    (96005, {'activated': True, 'groups': {'includes': {str(OTHER_GROUP_ID): ['READ']}}}, False),
    (96006, {'activated': True, 'groups': {'includes': {}}}, False),
    (96007, {'groups': {'includes': {str(GROUP_ID): ['READ']}}}, True),
    (96008, {'groups': {'includes': {str(OTHER_GROUP_ID): ['READ']}}}, False),
    (96009, {'activated': True, 'groups': {'includes': {str(GROUP_ID): []}}}, False),
    (96010, {'activated': True}, False),
]

ORPHAN_OBJECT_ID: int = 96099
ORPHAN_TYPE_ID: int = 96999

ALL_TYPE_IDS: list[int] = [type_id for type_id, _acl, _readable in TYPE_MATRIX]
DENIED_TYPE_IDS: list[int] = [type_id for type_id, _acl, readable in TYPE_MATRIX if not readable]
READABLE_TYPE_IDS: list[int] = [type_id for type_id, _acl, readable in TYPE_MATRIX if readable]


def _object_id_for(type_id: int) -> int:
    """The seeded object carrying the given type."""
    return type_id + 100


class _User:
    """Minimal stand-in for CmdbUser: the filter reads nothing but group_id."""

    def __init__(self, group_id: int) -> None:
        self.group_id = group_id


@pytest.fixture(name='seed_acl_types', autouse=True)
def fixture_seed_acl_types(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds one CmdbType per ACL shape plus one object each, and an orphan object."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': [_object_id_for(t) for t in ALL_TYPE_IDS]}})
        objects.delete_many({'public_id': ORPHAN_OBJECT_ID})

    _purge()

    for type_id, acl, _readable in TYPE_MATRIX:
        type_doc: dict[str, Any] = {'public_id': type_id, 'name': f'acl-type-{type_id}'}

        if acl is not None:
            type_doc['acl'] = acl

        types.insert_one(type_doc)
        objects.insert_one({'public_id': _object_id_for(type_id), 'type_id': type_id})

    objects.insert_one({'public_id': ORPHAN_OBJECT_ID, 'type_id': ORPHAN_TYPE_ID})
    yield
    _purge()


def _denied_ids(database_manager: MongoDatabaseManager, database_name: str, group_id: int) -> list[int]:
    """Runs the denied-types criteria against the seeded types only."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    criteria = build_denied_types_criteria(group_id, AccessControlPermission.READ)
    scoped = {'$and': [criteria, {'public_id': {'$in': ALL_TYPE_IDS}}]}

    return sorted(doc['public_id'] for doc in types.find(scoped, {'public_id': 1}))


def _readable_object_ids(
    database_manager: MongoDatabaseManager, database_name: str, group_id: int
) -> list[int]:
    """Applies the full ACL pipeline to the seeded objects and returns the surviving ids."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    denied = _denied_ids(database_manager, database_name, group_id)
    seeded = [_object_id_for(t) for t in ALL_TYPE_IDS] + [ORPHAN_OBJECT_ID]

    pipeline: list[dict[str, Any]] = [{'$match': {'public_id': {'$in': seeded}}}]

    if denied:
        pipeline.append({'$match': {'type_id': {'$nin': denied}}})

    return sorted(doc['public_id'] for doc in objects.aggregate(pipeline))


class TestDeniedTypesResolution:
    """The single framework.types query behind the filter."""

    def test_resolves_exactly_the_denied_types(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Every ACL shape lands on the right side of the allowed/denied split."""
        assert _denied_ids(database_manager, database_name, GROUP_ID) == sorted(DENIED_TYPE_IDS)

    def test_a_type_without_an_acl_is_never_denied(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The overwhelmingly common case: no ACL document at all."""
        assert 96001 not in _denied_ids(database_manager, database_name, GROUP_ID)

    def test_a_deactivated_acl_is_not_denied(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Switching an ACL off restores access without clearing its groups."""
        assert 96002 not in _denied_ids(database_manager, database_name, GROUP_ID)

    def test_an_acl_without_an_activated_key_is_enforced(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A stored ACL missing `activated` still denies a group that lacks the permission."""
        assert 96008 in _denied_ids(database_manager, database_name, GROUP_ID)

    def test_another_group_gets_a_different_denied_set(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The filter is per group: what group 1 may not read, group 2 may."""
        assert _denied_ids(database_manager, database_name, OTHER_GROUP_ID) != DENIED_TYPE_IDS

    @pytest.mark.parametrize('permission', list(AccessControlPermission))
    def test_every_permission_resolves(
        self, database_manager: MongoDatabaseManager, database_name: str,
        permission: AccessControlPermission
    ) -> None:
        """The criteria is valid Mongo for each of the four permissions."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        criteria = build_denied_types_criteria(GROUP_ID, permission)

        assert isinstance(list(types.find(criteria, {'public_id': 1})), list)


class TestFilteredObjects:
    """The object set the filter lets through."""

    def test_only_readable_types_survive(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Objects of readable types pass, objects of denied types do not."""
        expected = sorted([_object_id_for(t) for t in READABLE_TYPE_IDS] + [ORPHAN_OBJECT_ID])

        assert _readable_object_ids(database_manager, database_name, GROUP_ID) == expected

    def test_an_orphan_object_still_passes(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """An object whose type_id matches no CmdbType is not hidden - the filter is an exclusion.

        The previous $lookup implementation let it through via preserveNullAndEmptyArrays, and this
        pins that the $nin rewrite kept that behaviour rather than silently hiding such objects.
        """
        assert ORPHAN_OBJECT_ID in _readable_object_ids(database_manager, database_name, GROUP_ID)


class TestQueryStageOrder:
    """The built query must filter before it paginates."""

    @staticmethod
    def _stage_ops(query: list[dict[str, Any]]) -> list[str]:
        """The operator of each stage, in order."""
        return [next(iter(stage)) for stage in query]

    def test_acl_match_precedes_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: $skip used to run before the ACL filter, so a page could omit visible rows."""
        monkeypatch.setattr(
            'cmdb.security.acl.builder.resolve_denied_type_ids', lambda *_a, **_k: DENIED_TYPE_IDS
        )
        params = BuilderParameters(criteria={}, limit=10, skip=10, sort='public_id', order=1)

        query = BaseQueryBuilder().build(params, _User(GROUP_ID), AccessControlPermission.READ)
        ops = self._stage_ops(query)

        assert ops.index('$match') < ops.index('$skip')

    def test_acl_match_precedes_sort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Filtering first also shrinks the set that has to be sorted."""
        monkeypatch.setattr(
            'cmdb.security.acl.builder.resolve_denied_type_ids', lambda *_a, **_k: DENIED_TYPE_IDS
        )
        params = BuilderParameters(criteria={}, limit=10, skip=0, sort='public_id', order=1)

        query = BaseQueryBuilder().build(params, _User(GROUP_ID), AccessControlPermission.READ)
        ops = self._stage_ops(query)

        assert ops.index('$match') < ops.index('$sort')

    def test_no_lookup_stage_remains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The per-document join is gone from the built query entirely."""
        monkeypatch.setattr(
            'cmdb.security.acl.builder.resolve_denied_type_ids', lambda *_a, **_k: DENIED_TYPE_IDS
        )
        params = BuilderParameters(criteria={}, limit=10, skip=0, sort='public_id', order=1)

        query = BaseQueryBuilder().build(params, _User(GROUP_ID), AccessControlPermission.READ)

        assert '$lookup' not in self._stage_ops(query)

    def test_pagination_is_applied_to_the_filtered_set(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """A restricted user's first page holds readable rows only, with no gaps from early skipping."""
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
        seeded = [_object_id_for(t) for t in ALL_TYPE_IDS] + [ORPHAN_OBJECT_ID]
        page_size = 3

        pipeline: list[dict[str, Any]] = [
            {'$match': {'public_id': {'$in': seeded}}},
            {'$match': {'type_id': {'$nin': DENIED_TYPE_IDS}}},
            {'$sort': {'public_id': 1}},
            {'$skip': 0},
            {'$limit': page_size},
        ]
        page = [doc['public_id'] for doc in objects.aggregate(pipeline)]
        readable = sorted([_object_id_for(t) for t in READABLE_TYPE_IDS] + [ORPHAN_OBJECT_ID])

        assert len(page) == page_size
        assert page == readable[:page_size]
