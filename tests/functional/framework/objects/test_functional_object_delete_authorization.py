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
Functional coverage of the authorization order on the two object delete routes

A delete removes more than the object: its location node (with the children promoted), its rack and
port state, and - on the bulk route - its risk assessments, before the object itself goes. None of
that is undone when the type's ACL or its deactivation refuses the delete, so both routes authorize
EVERY target first. What is pinned: a refused delete answers 403 and leaves the object, its location
node and its risk assessment in place; a bulk selection with one refused target deletes nothing; a
permitted delete still deletes. Also the group-by route's field whitelist.

The caller is the default test client, an administrator holding ``base.framework.object.delete`` - so
the refusal can only come from the type
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType
from cmdb.models.object_model import CmdbObject
from cmdb.models.location_model.cmdb_location import CmdbLocation
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.security.acl.permission import AccessControlPermission
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'

DENYING_TYPE_ID: int = 96810      # ACL grants the admin group READ only
PERMITTING_TYPE_ID: int = 96811   # ACL grants READ and DELETE
DEACTIVATED_TYPE_ID: int = 96812  # no ACL, but deactivated
TYPE_IDS: list[int] = [DENYING_TYPE_ID, PERMITTING_TYPE_ID, DEACTIVATED_TYPE_ID]

DENIED_OBJECT_ID: int = 96813
PERMITTED_OBJECT_ID: int = 96814
DEACTIVATED_OBJECT_ID: int = 96815
OBJECT_IDS: list[int] = [DENIED_OBJECT_ID, PERMITTED_OBJECT_ID, DEACTIVATED_OBJECT_ID]
MISSING_OBJECT_ID: int = 96816

# location public_id = object id + LOCATION_OFFSET, risk assessment id = object id + RISK_ASSESSMENT_OFFSET
LOCATION_OFFSET: int = 100
RISK_ASSESSMENT_OFFSET: int = 200


def _type_doc(public_id: int, acl: dict[str, Any], active: bool = True) -> dict[str, Any]:
    """A field-less CmdbType with the given ACL."""
    return {
        'public_id': public_id,
        'name': f'delete-authorization-{public_id}',
        'label': f'Delete Authorization {public_id}',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': active,
        'fields': [],
        'render_meta': {'icon': '', 'sections': [], 'summary': {'fields': []}},
        'acl': acl,
        'version': '1.0.0',
    }


def _acl(*permissions: AccessControlPermission) -> dict[str, Any]:
    """An activated ACL granting the admin group exactly the given permissions."""
    return {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): [p.value for p in permissions]}}}


def _seed_object(database_manager: MongoDatabaseManager, database_name: str, object_id: int, type_id: int) -> None:
    """Stores an object of the type with a location node under the root and a risk assessment on it."""
    now = datetime.now(timezone.utc)
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_one({
        'public_id': object_id, 'type_id': type_id, 'author_id': 1, 'active': True, 'version': '1.0.0',
        'creation_time': now, 'fields': [], 'multi_data_sections': [],
    })
    database_manager.get_collection(CmdbLocation.COLLECTION, database_name).insert_one({
        'public_id': object_id + LOCATION_OFFSET, 'name': f'location-{object_id}',
        'parent': RootLocationDefault.PUBLIC_ID, 'object_id': object_id, 'type_id': type_id,
        'type_label': 'Delete Authorization', 'type_icon': '', 'type_selectable': True,
    })
    database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).insert_one({
        'public_id': object_id + RISK_ASSESSMENT_OFFSET, 'object_id': object_id,
        'object_id_ref_type': 'OBJECT', 'risk_id': 1,
    })


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the three types and one located, risk-assessed object of each; removes all of it afterwards."""
    def collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    _clean(collection)
    collection(CmdbType.COLLECTION).insert_many([
        _type_doc(DENYING_TYPE_ID, _acl(AccessControlPermission.READ)),
        _type_doc(PERMITTING_TYPE_ID, _acl(AccessControlPermission.READ, AccessControlPermission.DELETE)),
        _type_doc(DEACTIVATED_TYPE_ID, {'activated': False, 'groups': {'includes': None}}, active=False),
    ])
    _seed_object(database_manager, database_name, DENIED_OBJECT_ID, DENYING_TYPE_ID)
    _seed_object(database_manager, database_name, PERMITTED_OBJECT_ID, PERMITTING_TYPE_ID)
    _seed_object(database_manager, database_name, DEACTIVATED_OBJECT_ID, DEACTIVATED_TYPE_ID)
    yield collection
    _clean(collection)


def _clean(collection) -> None:
    """Removes every document this module seeds."""
    collection(CmdbType.COLLECTION).delete_many({'public_id': {'$in': TYPE_IDS}})
    collection(CmdbObject.COLLECTION).delete_many({'public_id': {'$in': OBJECT_IDS}})
    collection(CmdbLocation.COLLECTION).delete_many({'object_id': {'$in': OBJECT_IDS}})
    collection(IsmsRiskAssessment.COLLECTION).delete_many({'object_id': {'$in': OBJECT_IDS}})


def _untouched(collection, object_id: int) -> bool:
    """Whether the object, its location node and its risk assessment are all still stored."""
    return all((
        collection(CmdbObject.COLLECTION).find_one({'public_id': object_id}),
        collection(CmdbLocation.COLLECTION).find_one({'public_id': object_id + LOCATION_OFFSET}),
        collection(IsmsRiskAssessment.COLLECTION).find_one({'public_id': object_id + RISK_ASSESSMENT_OFFSET}),
    ))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SINGLE DELETE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSingleDelete:
    """DELETE /objects/<id> authorizes before its first side effect"""

    @pytest.mark.parametrize('object_id', [DENIED_OBJECT_ID, DEACTIVATED_OBJECT_ID])
    def test_a_refused_delete_changes_nothing(self, rest_api, seeded, object_id: int) -> None:
        """An ACL without DELETE, or a deactivated type: 403, and the location node survives too"""
        response = rest_api.delete(f'{ROUTE_URL}/{object_id}')

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _untouched(seeded, object_id)

    def test_a_permitted_delete_still_deletes(self, rest_api, seeded) -> None:
        """The guard lets a DELETE-granting ACL through; object and location node are gone"""
        response = rest_api.delete(f'{ROUTE_URL}/{PERMITTED_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert seeded(CmdbObject.COLLECTION).find_one({'public_id': PERMITTED_OBJECT_ID}) is None
        assert seeded(CmdbLocation.COLLECTION).find_one({'object_id': PERMITTED_OBJECT_ID}) is None

    def test_a_missing_object_is_still_a_404(self, rest_api) -> None:
        """Authorization needs a target; with none there is nothing to refuse"""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   BULK DELETE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkDelete:
    """DELETE /objects/delete/<ids> authorizes every target before the risk-assessment cascade"""

    @pytest.mark.parametrize('object_id', [DENIED_OBJECT_ID, DEACTIVATED_OBJECT_ID])
    def test_a_refused_target_changes_nothing(self, rest_api, seeded, object_id: int) -> None:
        """403, and the risk assessment - cascaded for the whole selection up front - survives"""
        response = rest_api.delete(f'{ROUTE_URL}/delete/{object_id}')

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _untouched(seeded, object_id)

    def test_one_refused_target_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """A permitted target listed first is not deleted either: the selection is all or nothing"""
        response = rest_api.delete(f'{ROUTE_URL}/delete/{PERMITTED_OBJECT_ID},{DENIED_OBJECT_ID}')

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert _untouched(seeded, PERMITTED_OBJECT_ID)
        assert _untouched(seeded, DENIED_OBJECT_ID)

    def test_a_permitted_selection_still_deletes(self, rest_api, seeded) -> None:
        """The guard lets the selection through and every side effect runs"""
        response = rest_api.delete(f'{ROUTE_URL}/delete/{PERMITTED_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['successfully'] == [PERMITTED_OBJECT_ID]
        assert seeded(CmdbObject.COLLECTION).find_one({'public_id': PERMITTED_OBJECT_ID}) is None
        assert seeded(IsmsRiskAssessment.COLLECTION).find_one({'object_id': PERMITTED_OBJECT_ID}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    GROUP BY                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupByWhitelist:
    """GET /objects/group/<field> groups by type_id only"""

    def test_grouping_by_type_id_answers(self, rest_api) -> None:
        """The one field the dashboard sends"""
        assert rest_api.get(f'{ROUTE_URL}/group/type_id').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('field', ['author_id', '$type_id', 'fields.value'])
    def test_any_other_field_is_refused(self, rest_api, field: str) -> None:
        """Every group id is resolved as a type, so another field could never answer"""
        response = rest_api.get(f'{ROUTE_URL}/group/{field}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert field in response.get_json()['message']
