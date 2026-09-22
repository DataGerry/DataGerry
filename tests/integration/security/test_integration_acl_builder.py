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
from cmdb.security.acl.builder import build_denied_types_criteria, build_permitted_types_criteria
from cmdb.security.acl.helpers import has_type_document_access
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
    # No 'activated' key at all: NOT activated, so both of these grant - the model's reading, adopted
    # by the query builder on 2026-09-17 (tier 2 T208). 96008 used to be denied here
    (96007, {'groups': {'includes': {str(GROUP_ID): ['READ']}}}, True),
    (96008, {'groups': {'includes': {str(OTHER_GROUP_ID): ['READ']}}}, True),
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

    def test_an_acl_without_an_activated_key_denies_nothing(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        A stored ACL carrying no `activated` key is not activated, so it grants

        96008's ACL names only the *other* group, which under an activated ACL would deny - it is
        granted here purely because the flag is absent. This is the model's reading
        (`AccessControlList.from_data` defaults it to False) and the query builder adopted it on
        2026-09-17, so `GET /objects/<id>` and `GET /objects/` stop disagreeing on this document.
        """
        denied = _denied_ids(database_manager, database_name, GROUP_ID)

        assert 96008 not in denied
        assert 96007 not in denied

    def test_an_activated_acl_naming_another_group_is_still_denied(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The counterpart: with the flag present and on, the same shape denies."""
        assert 96005 in _denied_ids(database_manager, database_name, GROUP_ID)

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


class TestPermittedTypesCriteria:
    """The types-listing half of the same rule, run against the seeded ACL shapes."""

    @staticmethod
    def _permitted_ids(types_collection, group_id: int) -> list[int]:
        """The seeded type ids the given group may READ, according to the permitted criteria."""
        criteria = {
            '$and': [
                {'public_id': {'$in': ALL_TYPE_IDS}},
                build_permitted_types_criteria(group_id, AccessControlPermission.READ),
            ]
        }

        return sorted(doc['public_id'] for doc in types_collection.find(criteria, {'public_id': 1}))

    def test_permitted_criteria_selects_exactly_the_readable_types(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Every ACL shape lands on the side the matrix says it does."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        assert self._permitted_ids(types, GROUP_ID) == sorted(READABLE_TYPE_IDS)

    def test_permitted_and_denied_criteria_partition_the_collection(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """No seeded type is both permitted and denied, and none is neither."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        denied = sorted(
            doc['public_id'] for doc in types.find(
                {'$and': [
                    {'public_id': {'$in': ALL_TYPE_IDS}},
                    build_denied_types_criteria(GROUP_ID, AccessControlPermission.READ),
                ]},
                {'public_id': 1},
            )
        )
        permitted = self._permitted_ids(types, GROUP_ID)

        assert not set(permitted) & set(denied)
        assert sorted(permitted + denied) == sorted(ALL_TYPE_IDS)

    def test_permitted_criteria_costs_no_second_query(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """It is one filter on framework.types itself - no id resolution round trip."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        criteria = build_permitted_types_criteria(GROUP_ID, AccessControlPermission.READ)

        explained = types.find(criteria).explain()

        assert explained['ok'] == 1

    def test_a_different_group_sees_a_different_set(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """The rule is per group - the other group's grants are not this group's."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        assert self._permitted_ids(types, GROUP_ID) != self._permitted_ids(types, OTHER_GROUP_ID)


class TestPermittedTypesCriteriaOverSeveralPermissions:
    """
    Asking for a permission other than READ, against the same seeded ACL shapes

    Until 2026-09-17 the criteria took exactly one permission and every caller passed READ, so the
    multi-permission form the Angular app has always posted as a client filter had never run
    server-side. These pin what it answers.
    """

    @staticmethod
    def _permitted_ids(types_collection, permission) -> list[int]:
        """The seeded type ids GROUP_ID may access under the given permission(s)."""
        criteria = {
            '$and': [
                {'public_id': {'$in': ALL_TYPE_IDS}},
                build_permitted_types_criteria(GROUP_ID, permission),
            ]
        }

        return sorted(doc['public_id'] for doc in types_collection.find(criteria, {'public_id': 1}))

    def test_asking_for_more_permissions_narrows_the_set(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """`$all` is a conjunction, so [READ, CREATE] is a subset of READ alone."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        read_only = self._permitted_ids(types, AccessControlPermission.READ)
        read_and_create = self._permitted_ids(
            types, [AccessControlPermission.READ, AccessControlPermission.CREATE],
        )

        assert set(read_and_create) <= set(read_only)
        assert 96003 in read_and_create

    def test_an_unflagged_acl_is_permitted_whatever_is_asked(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        A missing `activated` key grants, so no permission list can narrow those two away

        96007 and 96008 carry group entries that would matter under an activated ACL; with the flag
        absent the ACL is off and the entries are never consulted (tier 2 T208).
        """
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        for permission in [AccessControlPermission.READ,
                           [AccessControlPermission.READ, AccessControlPermission.CREATE],
                           AccessControlPermission.DELETE]:
            permitted = self._permitted_ids(types, permission)

            assert 96007 in permitted
            assert 96008 in permitted

    def test_a_different_permission_can_admit_a_type_read_denies(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """
        The consequence of REPLACING READ rather than intersecting with it

        96004 grants the group CREATE and not READ. Asked for READ it is denied; asked for CREATE it
        is permitted - which is why the listing filter is documented as a query rather than an access
        boundary (the single-type read applies no ACL at all, tier 2 T212).
        """
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        read_only = set(self._permitted_ids(types, AccessControlPermission.READ))
        create_only = set(self._permitted_ids(types, AccessControlPermission.CREATE))

        assert 96004 not in read_only
        assert 96004 in create_only

    def test_a_type_with_no_acl_is_permitted_whatever_is_asked(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """Access control stays opt-in no matter which permission the caller names."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        for permission in AccessControlPermission:
            assert 96001 in self._permitted_ids(types, permission)
            assert 96002 in self._permitted_ids(types, permission)

    def test_repeats_do_not_change_the_answer(
        self, database_manager: MongoDatabaseManager, database_name: str
    ) -> None:
        """`?acl=READ,READ` is the same question asked once."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)

        once = self._permitted_ids(types, AccessControlPermission.READ)
        twice = self._permitted_ids(types, [AccessControlPermission.READ, AccessControlPermission.READ])

        assert once == twice


class TestTheQueryAgreesWithTheModel:
    """
    The two implementations of the rule, asked about the same documents

    An ACL is read two ways in this codebase: `acl/helpers.acl_grants_access` decides for one loaded
    document (every `get_object` path), and `acl/builder.build_denied_types_criteria` decides for a
    whole query (every listing). They disagreed on a stored `acl` carrying no `activated` key until
    2026-09-17, so `GET /objects/<id>` and `GET /objects/` answered differently for the same type -
    tier 2 T208. This is the guard that keeps them together: it asks both about every seeded shape.
    """

    @staticmethod
    def _query_permits(types_collection, type_id: int, permission) -> bool:
        """Whether the query builder's criteria admits the seeded type."""
        criteria = {
            '$and': [
                {'public_id': type_id},
                build_permitted_types_criteria(GROUP_ID, permission),
            ]
        }

        return types_collection.count_documents(criteria) == 1

    @pytest.mark.parametrize('type_id', ALL_TYPE_IDS)
    @pytest.mark.parametrize('permission', list(AccessControlPermission))
    def test_both_implementations_agree_on_every_seeded_shape(
        self, database_manager: MongoDatabaseManager, database_name: str,
        type_id: int, permission: AccessControlPermission,
    ) -> None:
        """Forty combinations: ten stored ACL shapes against all four permissions."""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        document = types.find_one({'public_id': type_id})

        model_grants = has_type_document_access(document, _User(GROUP_ID), permission)
        query_permits = self._query_permits(types, type_id, permission)

        assert model_grants == query_permits
