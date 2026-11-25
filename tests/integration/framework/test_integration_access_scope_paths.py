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
Integration tests: the generic object paths take the access engine's own filter, against the test MongoDB

With a role on every Type assigned to another group, every Type is restricted: the user sees only the Type its own
role grants. Through ``BaseManager.iterate_query`` (rows and total) and ``ObjectsManager.apply_acl_to_criteria`` an
object of a gone Type is kept out too - the engine admits the granted Types instead of excluding the denied ones. The
paths handing a denied-Type id list along (``resolve_denied_type_ids``: an exclusion by it, a mask testing ``type_id
in`` it) keep it out as well: the list names the gone Type's id the object carries (T580). History - an object log,
a relation log, a webhook event - judges its stamped Type by the engine's denial (``resolve_denied_types``): a gone
Type no object carries, or none, is denied too (T581)
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.access_model import CmdbAccessAssignment, CmdbScopeRole
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.access_engine import id_criteria
from cmdb.security.acl.builder import resolve_denied_type_ids, resolve_denied_types
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

# ManagerProvider reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

GRANTED_TYPE_ID: int = 9971
OTHER_TYPE_ID: int = 9972
GONE_TYPE_ID: int = 9979
HISTORY_ONLY_TYPE_ID: int = 9980
HISTORY_SCRATCH: str = 'scope-paths.history'
USER_GROUP_ID: int = 9973
OTHER_GROUP_ID: int = 9974
OBJECT_TYPES: dict[int, int] = {9975: GRANTED_TYPE_ID, 9976: OTHER_TYPE_ID, 9977: GONE_TYPE_ID}
GRANTED_OBJECT_ID: int = 9975
USER: CmdbUser = CmdbUser(public_id=9978, user_name='scope-paths', active=True, group_ids=[USER_GROUP_ID])
OWN_SCOPE: dict[str, Any] = {'public_id': {'$in': list(OBJECT_TYPES)}}


@pytest.fixture(autouse=True)
def fixture_seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Two Types, an object of each and one of a gone Type; a role on every Type for the other group, the user views
    the granted Type"""
    database = database_manager.connector.client[database_name]
    types: list[dict[str, Any]] = [{'public_id': type_id, 'name': f'scope-paths-{type_id}', 'label': str(type_id),
                                    'fields': []} for type_id in (GRANTED_TYPE_ID, OTHER_TYPE_ID)]
    objects: list[dict[str, Any]] = [{'public_id': object_id, 'type_id': type_id, 'fields': [], 'active': True}
                                     for object_id, type_id in OBJECT_TYPES.items()]
    database[CmdbType.COLLECTION].insert_many(types)
    database[CmdbObject.COLLECTION].insert_many(objects)
    database[CmdbScopeRole.COLLECTION].insert_many([
        {'public_id': 9981, 'name': 'every', 'types': '*', 'operations': ['view'], 'write_regular_fields': True,
         'field_classes': []},
        {'public_id': 9982, 'name': 'granted', 'types': [GRANTED_TYPE_ID], 'operations': ['view'],
         'write_regular_fields': True, 'field_classes': []},
    ])
    database[CmdbAccessAssignment.COLLECTION].insert_many([
        {'public_id': 9983, 'group_id': OTHER_GROUP_ID, 'role_id': 9981, 'scope': '*'},
        {'public_id': 9984, 'group_id': USER_GROUP_ID, 'role_id': 9982, 'scope': '*'},
    ])

    yield

    database[CmdbType.COLLECTION].delete_many({'public_id': {'$in': [GRANTED_TYPE_ID, OTHER_TYPE_ID]}})
    database[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': list(OBJECT_TYPES)}})
    database[CmdbScopeRole.COLLECTION].delete_many({})
    database[CmdbAccessAssignment.COLLECTION].delete_many({})


def _objects_manager() -> ObjectsManager:
    """The request's objects manager"""
    return ManagerProvider.get_manager(ManagerType.OBJECTS, USER)


def test_iterate_query_keeps_the_gone_type_out_of_rows_and_total() -> None:
    """Only the granted Type's object - the rows and the count governed by one filter"""
    rows, total = _objects_manager().iterate_query(BuilderParameters(criteria=dict(OWN_SCOPE)), USER,
                                                   AccessControlPermission.READ)

    assert [row['public_id'] for row in rows] == [GRANTED_OBJECT_ID]
    assert total == 1


def test_apply_acl_to_criteria_keeps_the_gone_type_out() -> None:
    """The narrowed criteria finds the granted Type's object alone"""
    criteria: dict[str, Any] = ObjectsManager.apply_acl_to_criteria(dict(OWN_SCOPE), USER,
                                                                    AccessControlPermission.READ)

    assert [document['public_id'] for document in _objects_manager().find(criteria=criteria)] == [GRANTED_OBJECT_ID]


def test_without_a_user_nothing_is_narrowed() -> None:
    """An internal caller reads every object, the gone Type's too"""
    assert ObjectsManager.apply_acl_to_criteria(OWN_SCOPE, None, AccessControlPermission.READ) is OWN_SCOPE


class TestTheIdListPaths:
    """resolve_denied_type_ids names the gone Type too - an exclusion and a mask by it keep its object out (T580)"""

    @staticmethod
    def _denied() -> list[int]:
        """The user's denied Type ids for READ"""
        return resolve_denied_type_ids(USER, AccessControlPermission.READ)

    def test_the_list_names_the_other_and_the_gone_type(self) -> None:
        """Not the granted one"""
        denied = self._denied()

        assert {OTHER_TYPE_ID, GONE_TYPE_ID} <= set(denied) and GRANTED_TYPE_ID not in denied

    def test_an_exclusion_by_it_keeps_the_gone_type_out(self) -> None:
        """ObjectsManager.narrow_criteria_by_denied_types - the IPAM overviews, the reference pages"""
        criteria = ObjectsManager.narrow_criteria_by_denied_types(dict(OWN_SCOPE), self._denied())

        assert [document['public_id'] for document in _objects_manager().find(criteria=criteria)] == [
            GRANTED_OBJECT_ID]

    def test_a_mask_by_it_hides_the_gone_types_object(self) -> None:
        """type_id in denied - the CI Explorer, the location tree, the relation listings"""
        denied = set(self._denied())

        assert [object_id for object_id, type_id in OBJECT_TYPES.items() if type_id not in denied] == [
            GRANTED_OBJECT_ID]


class TestTheHistoryDenial:
    """resolve_denied_types judges a stamp of a gone Type no object carries, or of none - the history paths (T581)"""

    def test_the_granted_type_alone_is_readable(self) -> None:
        """The other, a gone one never seen, and none are denied"""
        denied = resolve_denied_types(USER, AccessControlPermission.READ)

        assert [type_id for type_id in (GRANTED_TYPE_ID, OTHER_TYPE_ID, HISTORY_ONLY_TYPE_ID, None)
                if not denied.denies(type_id)] == [GRANTED_TYPE_ID]

    def test_its_filter_keeps_only_the_granted_stamp(self, database_manager: MongoDatabaseManager,
                                                     database_name: str) -> None:
        """id_criteria on a stamped key: null, missing and gone stamps are out"""
        scratch = database_manager.connector.client[database_name][HISTORY_SCRATCH]
        scratch.insert_many([{'_id': 1, 'type_id': GRANTED_TYPE_ID}, {'_id': 2, 'type_id': HISTORY_ONLY_TYPE_ID},
                             {'_id': 3, 'type_id': None}, {'_id': 4}])

        try:
            denied = resolve_denied_types(USER, AccessControlPermission.READ)
            found = [document['_id'] for document in scratch.find(id_criteria('type_id', denied))]
        finally:
            scratch.drop()

        assert found == [1]
