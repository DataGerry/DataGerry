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
Functional tests for every write that names a CmdbUserGroup, and for the group delete that would orphan one

A user write and the auth settings write refuse a group that does not exist (400); a type's ``acl`` names no group
reference any more - a changed one is refused as such (``types.md``). A group
delete is refused while the LDAP settings name the group, and ``GET /groups/<id>/usage`` answers the same census
beforehand. A stored type ACL naming the group neither blocks the delete nor is edited by it - the access engine
decides, not the ACL (the assignment half: ``test_functional_access_lock_open.py``)
"""
import copy
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.routes_helper import UNKNOWN_REFERENCES_MSG
from cmdb.interface.rest_api.routes.user_management_routes.cmdb_groups.groups_constants import (
    GROUP_IN_USE_MSG,
    GROUP_USE_LDAP_DEFAULT,
    GROUP_USE_LDAP_MAPPING,
    USER_GROUP_LABEL,
    GroupUsageKey,
)
from cmdb.manager import SettingsManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE,
)
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.security_models.auth_settings_constants import LDAP_GROUP_NOT_AN_ID_MSG
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

USERS_URL: str = '/users'
GROUPS_URL: str = '/groups'
TYPES_URL: str = '/types'
AUTH_URL: str = '/auth/settings'
AUTH_ID: str = 'auth'
LDAP_CLASS: str = 'LdapAuthenticationProvider'

GROUP: int = 99101
OTHER_GROUP: int = 99102
MISSING_GROUP: int = 99199
STALE_GROUP: int = 99198
USER_NAME: str = 'group-ref-user'
GROUP_DN: str = 'cn=group-ref,dc=example,dc=com'
SOLE_TYPE: int = 99111
SHARED_TYPE: int = 99112
NEW_TYPE: int = 99113
ALL_TYPES: list[int] = [SOLE_TYPE, SHARED_TYPE, NEW_TYPE]
TYPE_NAME_PREFIX: str = 'group-ref-type-'
ADMIN_GROUP: int = 1
NAME_FIELD: str = 'name'
READ: list[str] = ['READ']
ALL_PERMISSIONS: list[str] = ['CREATE', 'READ', 'UPDATE', 'DELETE']


def _acl(includes: dict[int, list[str]], activated: bool = True) -> dict[str, Any]:
    """An acl block."""
    return {'activated': activated, 'groups': {'includes': {str(key): value for key, value in includes.items()}}}


def _type_payload(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A CmdbType payload POST /types/ and PUT /types/<id> accept."""
    return {
        'public_id': public_id, 'name': f'{TYPE_NAME_PREFIX}{public_id}', 'label': 'Group ref', 'author_id': 1,
        'active': True, 'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'summary': {'fields': [NAME_FIELD]},
                        'sections': [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]},
        'acl': acl, 'version': '1.0.0',
    }


@pytest.fixture(name='stores', autouse=True)
def fixture_stores(database_manager: MongoDatabaseManager, database_name: str):
    """Two groups; every user, type and the auth section these tests touch restored after"""
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    stored_auth = settings.find_one({'_id': AUTH_ID})

    def _purge() -> None:
        groups.delete_many({'public_id': {'$in': [GROUP, OTHER_GROUP]}})
        users.delete_many({'user_name': USER_NAME})
        # A created type gets a server-drawn public_id, so the name finds it
        types.delete_many({'$or': [{'public_id': {'$in': ALL_TYPES}}, {'name': {'$regex': f'^{TYPE_NAME_PREFIX}'}}]})

    _purge()
    groups.insert_many([{'public_id': group_id, 'name': f'group-ref-{group_id}', 'label': 'Ref', 'rights': []}
                        for group_id in (GROUP, OTHER_GROUP)])
    yield {'groups': groups, 'users': users, 'types': types, 'settings': settings}
    _purge()
    if stored_auth is None:
        settings.delete_one({'_id': AUTH_ID})
    else:
        settings.replace_one({'_id': AUTH_ID}, stored_auth)


def _unknown(group_id: int) -> str:
    """The refusal naming one unknown group"""
    return UNKNOWN_REFERENCES_MSG.format(entity_label=USER_GROUP_LABEL, unknown=[group_id])


def _ldap_settings(rest_api, default_group: Any, mapped: Any = None) -> dict[str, Any]:
    """The stored auth section with the LDAP entry's default group and one mapping row replaced"""
    section: dict[str, Any] = copy.deepcopy(rest_api.get(AUTH_URL).get_json())
    ldap: dict[str, Any] = next(entry for entry in section['providers'] if entry['class_name'] == LDAP_CLASS)
    ldap['config']['default_group'] = default_group
    ldap['config'].setdefault('groups', {})['mapping'] = [] if mapped is None else [
        {'group_dn': GROUP_DN, 'group_id': mapped}]

    return section


def _store_type(stores: dict[str, Any], type_id: int, acl: dict[str, Any]) -> None:
    """A type written straight into the collection, past the routes"""
    stores['types'].insert_one({**_type_payload(type_id, acl), 'creation_time': None})


def _stored_acl(stores: dict[str, Any], type_id: int) -> dict[str, Any]:
    """A type's stored acl"""
    return stores['types'].find_one({'public_id': type_id})['acl']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       USERS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUserGroup:
    """POST /users/ and PUT /users/<id>"""

    def test_a_create_into_a_missing_group_is_refused(self, rest_api, stores) -> None:
        """Nothing stored"""
        response = rest_api.post(f'{USERS_URL}/', json={'user_name': USER_NAME, 'password': 'pw', 'active': True,
                                                         'group_ids': [MISSING_GROUP]})

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST,
                                                                           _unknown(MISSING_GROUP))
        assert stores['users'].count_documents({'user_name': USER_NAME}) == 0

    def test_a_move_into_a_missing_group_is_refused(self, rest_api, stores) -> None:
        """The stored group stays"""
        user_id: int = rest_api.post(f'{USERS_URL}/', json={'user_name': USER_NAME, 'password': 'pw', 'active': True,
                                                            'group_ids': [GROUP]}).get_json()['result_id']
        body: dict[str, Any] = {key: value for key, value in rest_api.get(f'{USERS_URL}/{user_id}').get_json()
                                ['result'].items() if key != 'password'}

        response = rest_api.put(f'{USERS_URL}/{user_id}', json={**body, 'group_ids': [MISSING_GROUP]})

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST,
                                                                           _unknown(MISSING_GROUP))
        assert stores['users'].find_one({'public_id': user_id})['group_ids'] == [GROUP]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   AUTH SETTINGS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAuthSettingsGroups:
    """PUT /auth/settings"""

    @pytest.mark.parametrize('default_group, mapped', [(MISSING_GROUP, None), (GROUP, MISSING_GROUP)],
                             ids=['default', 'mapping'])
    def test_a_missing_group_is_refused(self, rest_api, default_group: int, mapped: int | None) -> None:
        """Whether LDAP is active or not"""
        response = rest_api.put(AUTH_URL, json=_ldap_settings(rest_api, default_group, mapped))

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST,
                                                                           _unknown(MISSING_GROUP))

    def test_a_mapping_value_that_is_no_id_is_refused(self, rest_api) -> None:
        """Named as sent"""
        response = rest_api.put(AUTH_URL, json=_ldap_settings(rest_api, GROUP, 'admins'))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == LDAP_GROUP_NOT_AN_ID_MSG.format(values=['admins'])

    def test_existing_groups_are_stored(self, rest_api, stores) -> None:
        """The control"""
        assert rest_api.put(AUTH_URL, json=_ldap_settings(rest_api, GROUP, OTHER_GROUP)).status_code == HTTPStatus.OK
        ldap = next(entry for entry in stores['settings'].find_one({'_id': AUTH_ID})['providers']
                    if entry['class_name'] == LDAP_CLASS)
        assert ldap['config']['default_group'] == GROUP


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     TYPE ACL                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTypeAclGroups:
    """POST /types/ and PUT /types/<id> - a type acl is no group reference any more (it decides nothing)"""

    def test_a_create_naming_groups_is_refused_as_an_acl_change(self, rest_api, stores) -> None:
        """Missing group or not: an activated acl is refused, naming Access & Data Rules; nothing stored"""
        payload: dict[str, Any] = _type_payload(NEW_TYPE, _acl({GROUP: READ, MISSING_GROUP: READ}))
        response = rest_api.post(f'{TYPES_URL}/', json=payload)

        assert (response.status_code, response.get_json()['message']) == (HTTPStatus.BAD_REQUEST,
                                                                           TYPE_ACL_MANAGED_ELSEWHERE_MESSAGE)
        assert stores['types'].count_documents({'name': f'{TYPE_NAME_PREFIX}{NEW_TYPE}'}) == 0

    def test_a_type_with_a_stale_stored_entry_stays_saveable(self, rest_api, stores) -> None:
        """Sent back as answered, the update passes; the stored block keeps its content (lists written sorted)"""
        acl: dict[str, Any] = _acl({ADMIN_GROUP: ALL_PERMISSIONS, STALE_GROUP: READ})
        _store_type(stores, SHARED_TYPE, acl)
        answered: dict[str, Any] = rest_api.get(f'{TYPES_URL}/{SHARED_TYPE}').get_json()['result']['acl']

        response = rest_api.put(f'{TYPES_URL}/{SHARED_TYPE}', json=_type_payload(SHARED_TYPE, answered))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _stored_acl(stores, SHARED_TYPE) == _acl({ADMIN_GROUP: sorted(ALL_PERMISSIONS), STALE_GROUP: READ})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   GROUP DELETE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestGroupDeleteAndUsage:
    """DELETE /groups/<id> and GET /groups/<id>/usage"""

    @staticmethod
    def _store_ldap(stores: dict[str, Any], default_group: int, mapped: int | None = None) -> None:
        """An auth section naming the given groups, written past the route"""
        rows = [] if mapped is None else [{'group_dn': GROUP_DN, 'group_id': mapped}]
        stores['settings'].replace_one({'_id': AUTH_ID}, {'_id': AUTH_ID, 'providers': [{
            'class_name': LDAP_CLASS, 'config': {'default_group': default_group, 'groups': {'mapping': rows}},
        }]}, upsert=True)

    @staticmethod
    def _refused(rest_api, stores: dict[str, Any], holders: str) -> None:
        """A 400 naming the holders; the group is still there"""
        response = rest_api.delete(f'{GROUPS_URL}/{GROUP}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == GROUP_IN_USE_MSG.format(public_id=GROUP, holders=holders)
        assert stores['groups'].count_documents({'public_id': GROUP}) == 1

    def test_refused_while_it_is_the_ldap_default_group(self, rest_api, stores) -> None:
        """Directory users would be provisioned into nothing"""
        self._store_ldap(stores, GROUP)

        self._refused(rest_api, stores, GROUP_USE_LDAP_DEFAULT)

    def test_refused_while_an_ldap_mapping_names_it(self, rest_api, stores) -> None:
        """Mapped users would be moved into nothing"""
        self._store_ldap(stores, OTHER_GROUP, GROUP)

        self._refused(rest_api, stores, GROUP_USE_LDAP_MAPPING.format(group_dns=[GROUP_DN]))

    def test_a_type_acl_granting_only_it_neither_blocks_nor_is_edited(self, rest_api, stores) -> None:
        """The stored ACL decides nothing - the delete passes and leaves it as it was"""
        self._store_ldap(stores, OTHER_GROUP)
        acl: dict[str, Any] = _acl({GROUP: ALL_PERMISSIONS, STALE_GROUP: READ})
        _store_type(stores, SOLE_TYPE, acl)

        assert rest_api.delete(f'{GROUPS_URL}/{GROUP}').status_code == HTTPStatus.ACCEPTED
        assert _stored_acl(stores, SOLE_TYPE) == acl

    def test_the_usage_route_answers_the_census(self, rest_api, stores) -> None:
        """What the delete would refuse over, beforehand - a type ACL naming the group is no part of it"""
        self._store_ldap(stores, GROUP, GROUP)
        _store_type(stores, SOLE_TYPE, _acl({GROUP: ALL_PERMISSIONS}))

        response = rest_api.get(f'{GROUPS_URL}/{GROUP}/usage')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'] == {
            GroupUsageKey.MEMBERS.value: 0, GroupUsageKey.SOLE_MEMBERS.value: 0,
            GroupUsageKey.LDAP_DEFAULT_GROUP.value: True,
            GroupUsageKey.LDAP_GROUP_MAPPINGS.value: [GROUP_DN],
            GroupUsageKey.LOCKED_TYPE_IDS.value: [], GroupUsageKey.OPENED_TYPE_IDS.value: [],
            GroupUsageKey.ASSIGNMENT_IDS.value: [],
            GroupUsageKey.BLOCKS_DELETE.value: True,
        }

    def test_the_usage_of_an_unused_group_does_not_block(self, rest_api, stores) -> None:
        """The control"""
        self._store_ldap(stores, OTHER_GROUP)

        result = rest_api.get(f'{GROUPS_URL}/{GROUP}/usage').get_json()['result']

        assert result[GroupUsageKey.BLOCKS_DELETE.value] is False

    def test_the_usage_of_a_missing_group_is_a_404(self, rest_api) -> None:
        """Nothing to count"""
        assert rest_api.get(f'{GROUPS_URL}/{MISSING_GROUP}/usage').status_code == HTTPStatus.NOT_FOUND
