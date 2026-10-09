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
Functional coverage for what the rack read routes show a caller who may not read every object

A rack editor - the rack rights and the object view/edit rights - whose group the member type's ACL leaves out:

  - the assignable-objects picker offers only what the caller may READ, and its total follows
  - the "in another rack" hint keeps a holding rack's id but blanks its name when the caller may not read racks
  - the overview keeps an unreadable member's row - its slots are occupied - with its summary line and type label
    blank, and tallies its type under a blank legend entry; the height-conflict pre-check reports it the same way
  - an administrator still sees every name
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackRight

from tests.functional.framework.test_functional_rack_locations import (
    MEMBER_WITH_FIELD_ID,
    OTHER_RACK_ID,
    RACK_ID,
    RACK_TYPE_ID,
    WITH_LOCATION_TYPE_ID,
    _mount,
    _object_doc,
    _place_rack,
    _type_doc,
)
# Imported to register them here: the rack suite's licence stub and its two seeding fixtures
from tests.functional.framework.test_functional_rack_locations import (  # noqa: F401 pylint: disable=unused-import
    _ipam_licensed,
    _seed_types,
    fixture_collections,
)
# -------------------------------------------------------------------------------------------------------------------- #

RACKS_URL: str = '/racks'
EDITOR_GROUP_ID: int = 89841
EDITOR_ID: int = 89851
HIDDEN_TYPE_ID: int = 89861
HIDDEN_OBJECT_ID: int = 89871
HIDDEN_NAME: str = 'secret-server'
ADMIN_GROUP: str = '1'

# READ for the administrators only: the editor's group is left out
ADMIN_ONLY_ACL: dict[str, Any] = {
    'activated': True, 'groups': {'includes': {ADMIN_GROUP: ['CREATE', 'READ', 'UPDATE', 'DELETE']}},
}
OPEN_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': None}}

# The candidate height a conflict pre-check is asked about, below the hidden member's slot
LOW_HEIGHT: int = 5
HIDDEN_MEMBER_SLOT: int = 20


@pytest.fixture(name='editor', autouse=True)
def fixture_editor(collections, database_manager: MongoDatabaseManager, database_name: str):
    """The rack editor, a member type it may not read with one object, and a placed rack"""
    objects, locations, mounts = collections
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': HIDDEN_TYPE_ID})
        objects.delete_many({'public_id': HIDDEN_OBJECT_ID})
        mounts.delete_many({'object_id': HIDDEN_OBJECT_ID})
        # The mount mirrors the member into the location tree - its node goes with it
        locations.delete_many({'object_id': HIDDEN_OBJECT_ID})
        groups.delete_many({'public_id': EDITOR_GROUP_ID})
        users.delete_many({'public_id': EDITOR_ID})
        types.update_one({'public_id': RACK_TYPE_ID}, {'$set': {'acl': OPEN_ACL}})

    _purge()
    hidden_type: dict[str, Any] = _type_doc(HIDDEN_TYPE_ID, 'rack-acl-hidden-member', True)
    hidden_type['acl'] = ADMIN_ONLY_ACL
    types.insert_one(hidden_type)
    hidden_object: dict[str, Any] = _object_doc(HIDDEN_OBJECT_ID, WITH_LOCATION_TYPE_ID, HIDDEN_NAME, None)
    hidden_object['type_id'] = HIDDEN_TYPE_ID
    objects.insert_one(hidden_object)
    groups.insert_one({'public_id': EDITOR_GROUP_ID, 'name': 'rack-acl-editor', 'label': 'Rack editor',
                       'rights': [right.value for right in RackRight]
                       + [ObjectRightName.VIEW.value, ObjectRightName.EDIT.value]})
    users.insert_one({'public_id': EDITOR_ID, 'user_name': 'rack-acl-editor', 'active': True,
                      'group_id': EDITOR_GROUP_ID, 'registration_time': datetime.now(timezone.utc)})

    yield CmdbUser(public_id=EDITOR_ID, user_name='rack-acl-editor', active=True, group_id=EDITOR_GROUP_ID)

    _purge()


def _picker_ids(rest_api, rack_id: int, **kwargs: Any) -> tuple[list[int], int]:
    """The candidates the picker offers, and its total"""
    response = rest_api.get(f'{RACKS_URL}/{rack_id}/assignable_objects/', query_string={'limit': 0}, **kwargs)
    assert response.status_code == HTTPStatus.OK, response.get_json()
    body = response.get_json()

    return [row['public_id'] for row in body['results']], body['total']


def _rows(overview: dict[str, Any]) -> list[dict[str, Any]]:
    """Every row of every area of an overview"""
    return [row for rows in overview['areas'].values() for row in rows]


class TestThePicker:
    """GET /racks/<id>/assignable_objects/"""

    def test_an_unreadable_candidate_is_not_offered(self, rest_api, editor: CmdbUser) -> None:
        """It used to be offered, named, to a caller its object route answers 403"""
        assert rest_api.get(f'/objects/{HIDDEN_OBJECT_ID}', user=editor).status_code == HTTPStatus.FORBIDDEN

        offered, total = _picker_ids(rest_api, RACK_ID, user=editor)

        assert HIDDEN_OBJECT_ID not in offered
        assert MEMBER_WITH_FIELD_ID in offered
        assert total == len(offered)

    def test_the_administrator_is_offered_it(self, rest_api) -> None:
        """Their group reads the type"""
        assert HIDDEN_OBJECT_ID in _picker_ids(rest_api, RACK_ID)[0]

    def test_a_rack_the_caller_may_not_read_keeps_its_id_and_loses_its_name(
        self, rest_api, editor: CmdbUser, database_manager: MongoDatabaseManager, database_name: str,
    ) -> None:
        """The member is in the other rack: the hint still warns, without naming the rack"""
        assert _mount(rest_api, MEMBER_WITH_FIELD_ID, rack_id=OTHER_RACK_ID).status_code == HTTPStatus.CREATED
        database_manager.get_collection(CmdbType.COLLECTION, database_name).update_one(
            {'public_id': RACK_TYPE_ID}, {'$set': {'acl': ADMIN_ONLY_ACL}},
        )

        response = rest_api.get(f'{RACKS_URL}/{RACK_ID}/assignable_objects/', query_string={'limit': 0},
                                user=editor)
        row = next(row for row in response.get_json()['results'] if row['public_id'] == MEMBER_WITH_FIELD_ID)

        assert row['assigned_rack_id'] == OTHER_RACK_ID
        assert row['assigned_rack_name'] is None


class TestTheOverview:
    """GET /racks/<id>/overview and the height-conflict pre-check"""

    @pytest.fixture(autouse=True)
    def _mounted(self, rest_api) -> None:
        """The hidden object mounted by the administrator, placed high in the rack"""
        assert _place_rack(rest_api).status_code == HTTPStatus.ACCEPTED
        response = _mount(rest_api, HIDDEN_OBJECT_ID, area='FRONT', start_slot=HIDDEN_MEMBER_SLOT, height=1)
        assert response.status_code == HTTPStatus.CREATED, response.get_json()

    def test_an_unreadable_member_keeps_its_row_without_its_names(self, rest_api, editor: CmdbUser) -> None:
        """The slot is drawn occupied; nothing names the member or its type"""
        overview = rest_api.get(f'{RACKS_URL}/{RACK_ID}/overview', user=editor).get_json()
        row = next(row for row in _rows(overview) if row['object_id'] == HIDDEN_OBJECT_ID)

        assert row['start_slot'] == HIDDEN_MEMBER_SLOT
        assert row['summary_line'] is None
        assert row['type_label'] is None and row['type_icon'] is None
        assert {'type_id': HIDDEN_TYPE_ID, 'type_label': None, 'type_icon': None, 'type_color': None,
                'count': 1} in overview['types_legend']

    def test_the_administrator_sees_the_names(self, rest_api) -> None:
        """The masking is the caller's ACL, not the rack's"""
        overview = rest_api.get(f'{RACKS_URL}/{RACK_ID}/overview').get_json()
        row = next(row for row in _rows(overview) if row['object_id'] == HIDDEN_OBJECT_ID)

        assert HIDDEN_NAME in row['summary_line']
        assert row['type_label'] is not None

    def test_the_height_pre_check_reports_it_blank(self, rest_api, editor: CmdbUser) -> None:
        """The same rows, the same rule"""
        response = rest_api.get(f'{RACKS_URL}/{RACK_ID}/height_conflicts', query_string={'height': LOW_HEIGHT},
                                user=editor)
        conflict = next(row for row in response.get_json()['conflicts'] if row['object_id'] == HIDDEN_OBJECT_ID)

        assert conflict['summary_line'] is None and conflict['type_label'] is None
