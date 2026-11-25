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
Integration tests for the access filters, against the test MongoDB through ManagerProvider

Stored Types, objects (one of a gone Type), roles and assignments: the object filter run on the objects collection
lets the user's objects through and keeps the denied Types out - an object of a gone Type passes an exclusion and is
kept out by a complement; the Type filter run on the Types collection; the existing Types listed for a complement
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.access_engine import denied_type_ids, permitted_types_criteria, scope_filter, type_allows
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole, ScopeOperation
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

SERVER_TYPE_ID: int = 9701
ROUTER_TYPE_ID: int = 9702
FREE_TYPE_ID: int = 9703
GONE_TYPE_ID: int = 9799
SEEDED_TYPE_IDS: list[int] = [SERVER_TYPE_ID, ROUTER_TYPE_ID, FREE_TYPE_ID]
USER_GROUP_ID: int = 9711
OTHER_GROUP_ID: int = 9712
OWN_ROLE_ID: int = 9721
OTHER_ROLE_ID: int = 9722
OBJECT_TYPES: dict[int, int] = {9731: SERVER_TYPE_ID, 9732: ROUTER_TYPE_ID, 9733: FREE_TYPE_ID, 9734: GONE_TYPE_ID}
USER: CmdbUser = CmdbUser(public_id=9741, user_name='access-filter', active=True, group_ids=[USER_GROUP_ID])


@pytest.fixture(name='database', autouse=True)
def fixture_database(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """Three Types, an object of each and one of a gone Type; the user may view servers, routers are restricted"""
    database = database_manager.connector.client[database_name]
    types: list[dict[str, Any]] = [{'public_id': type_id, 'name': f'access-filter-{type_id}', 'label': str(type_id),
                                    'fields': []} for type_id in SEEDED_TYPE_IDS]
    database[CmdbType.COLLECTION].insert_many(types)
    objects: list[dict[str, Any]] = [{'public_id': object_id, 'type_id': type_id, 'fields': []}
                                     for object_id, type_id in OBJECT_TYPES.items()]
    database[CmdbObject.COLLECTION].insert_many(objects)
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': OWN_ROLE_ID, 'name': 'own', 'types': [SERVER_TYPE_ID], 'operations': ['view'],
         'write_regular_fields': True, 'field_classes': []},
        {'public_id': OTHER_ROLE_ID, 'name': 'other', 'types': [ROUTER_TYPE_ID], 'operations': ['view'],
         'write_regular_fields': True, 'field_classes': []},
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': 9751, 'group_id': USER_GROUP_ID, 'role_id': OWN_ROLE_ID, 'scope': '*'},
        {'public_id': 9752, 'group_id': OTHER_GROUP_ID, 'role_id': OTHER_ROLE_ID, 'scope': '*'},
    ])

    yield database

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': SEEDED_TYPE_IDS}})
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': list(OBJECT_TYPES)}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _visible_objects(database: Any, criteria: dict[str, Any]) -> list[int]:
    """The seeded objects the criteria let through"""
    found = database[CmdbObject.COLLECTION].find({'$and': [{'public_id': {'$in': list(OBJECT_TYPES)}}, criteria]})

    return sorted(document['public_id'] for document in found)


def _every_type_restricted(database: Any) -> None:
    """The other group's role now names every Type"""
    database[CmdbScopeRole.COLLECTION].update_one({'public_id': OTHER_ROLE_ID}, {'$set': {'types': '*'}})


class TestObjectFilter:
    """scope_filter on the objects collection"""

    def test_an_exclusion_keeps_the_restricted_type_out(self, database: Any) -> None:
        """Servers, the free Type and the gone Type's object - not the routers"""
        assert _visible_objects(database, scope_filter(USER, ScopeOperation.VIEW)) == [9731, 9733, 9734]

    def test_a_complement_admits_only_the_granted_type(self, database: Any) -> None:
        """Every Type restricted: servers only - the gone Type's object is out (E5)"""
        _every_type_restricted(database)

        assert _visible_objects(database, scope_filter(USER, ScopeOperation.VIEW)) == [9731]

    def test_one_denied_type_matches_no_object(self, database: Any) -> None:
        """Edit is granted nowhere on servers"""
        assert _visible_objects(database, scope_filter(USER, ScopeOperation.EDIT, SERVER_TYPE_ID)) == []


class TestTypeAnswers:
    """permitted_types_criteria, denied_type_ids, type_allows on the stored Types"""

    def test_the_type_filter(self, database: Any) -> None:
        """The routers are left out of the Types collection"""
        found = database[CmdbType.COLLECTION].find({'$and': [{'public_id': {'$in': SEEDED_TYPE_IDS}},
                                                             permitted_types_criteria(USER, ScopeOperation.VIEW)]})

        assert sorted(document['public_id'] for document in found) == [SERVER_TYPE_ID, FREE_TYPE_ID]

    def test_a_complement_lists_every_type_id_but_the_granted(self, database: Any) -> None:
        """The existing Types and the gone Type an object still carries (T580) - not the granted one"""
        _every_type_restricted(database)
        denied: list[int] = denied_type_ids(USER, ScopeOperation.VIEW)

        assert ROUTER_TYPE_ID in denied and FREE_TYPE_ID in denied and GONE_TYPE_ID in denied
        assert SERVER_TYPE_ID not in denied
        assert denied == sorted(denied)

    def test_type_allows(self) -> None:
        """View on servers and the free Type, not on routers"""
        assert type_allows(USER, ScopeOperation.VIEW, SERVER_TYPE_ID)
        assert type_allows(USER, ScopeOperation.VIEW, FREE_TYPE_ID)
        assert not type_allows(USER, ScopeOperation.VIEW, ROUTER_TYPE_ID)


def test_every_type_id_ascending() -> None:
    """TypesManager.get_all_type_ids: the seeded Types among them, ascending"""
    type_ids: list[int] = ManagerProvider.get_manager(ManagerType.TYPES, USER).get_all_type_ids()

    assert set(SEEDED_TYPE_IDS) <= set(type_ids)
    assert type_ids == sorted(type_ids)
