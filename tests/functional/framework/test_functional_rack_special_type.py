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
Functional tests for the RACK SpecialType and the Rack rights, over the REST routes

Covers what the model-level unit tests cannot: that the creation dialog's routes actually offer RACK
and serve its blueprint, that a Rack CmdbType can be created through POST /types/ (which also proves
the write is not gated behind the IPAM license), that the selectable_as_parent invariant is enforced
on create and update, and that the four rack rights are served by the /rights routes
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated Rack View surface is reachable.

    The Rack View is gated behind LicenseFeature.IPAM as an interim decision - a Rack is not an IPAM
    type, see SpecialType.get_license_gated_types - so every /racks route, the RACK type write and
    the Rack object write need the feature unlocked here.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

SPECIAL_TYPES_URL: str = '/special_types'
TYPES_URL: str = '/types'
RIGHTS_URL: str = '/rights'

RACK_LABEL: str = 'Rack View - Rack class'

RACK_TYPE_ID: int = 9611
RACK_TYPE_ID_FOR_UPDATE: int = 9612
RACK_TYPE_ID_REJECTED: int = 9613
ALL_TYPE_IDS: list[int] = [RACK_TYPE_ID, RACK_TYPE_ID_FOR_UPDATE, RACK_TYPE_ID_REJECTED]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

RACK_RIGHT_NAMES: list[str] = [
    'base.framework.rack.view',
    'base.framework.rack.add',
    'base.framework.rack.edit',
    'base.framework.rack.delete',
]


def _rack_type_payload(public_id: int, selectable_as_parent: bool | None = None) -> dict[str, Any]:
    """
    Builds a Rack CmdbType payload as the frontend would send it after fetching the blueprint

    The blueprint supplies the fields and the section; the identity, label, icon and summary come
    from the creating user, which is why they are spelled out here rather than read from the schema.
    """
    payload: dict[str, Any] = {
        'public_id': public_id,
        'name': f'rack-{public_id}',
        'label': 'Rack',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.RACK.value,
        'fields': [
            {'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
            {'type': 'text', 'name': RackField.NUMBER.value, 'label': 'Racknumber'},
            {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True},
            {'type': 'textarea', 'name': RackField.NOTES.value, 'label': 'Notes'},
            {'type': 'location', 'name': RackField.LOCATION.value, 'label': 'Location'},
        ],
        'render_meta': {
            'icon': 'fa-server',
            'sections': [{
                'type': 'section',
                'name': RackSection.INFORMATION.value,
                'label': 'Information',
                'fields': [
                    RackField.NAME.value,
                    RackField.NUMBER.value,
                    RackField.HEIGHT.value,
                    RackField.NOTES.value,
                    RackField.LOCATION.value,
                ],
            }],
            'summary': {'fields': [RackField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }

    if selectable_as_parent is not None:
        payload[TypeSchemaKey.SELECTABLE_AS_PARENT.value] = selectable_as_parent

    return payload


def _types_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the CmdbType collection of the test database"""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)


@pytest.fixture(autouse=True)
def _clean_rack_types(database_manager: MongoDatabaseManager, database_name: str):
    """
    Removes every seeded Rack type before and after each test

    A SpecialType may exist only once per installation, so a leftover Rack type from one test would
    make the next one's creation fail - and would also hide RACK from the ?available=true listing.
    """
    types = _types_collection(database_manager, database_name)
    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})

    yield

    types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})


def _insert_rack_type(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a Rack CmdbType directly, bypassing the POST route's validation"""
    doc = _rack_type_payload(public_id, selectable_as_parent=True)
    doc['creation_time'] = datetime.now(timezone.utc)
    _types_collection(database_manager, database_name).insert_one(doc)

# -------------------------------------------------------------------------------------------------------------------- #
#                                            the creation dialog's routes                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSpecialTypeListing:
    """GET /special_types/ offers RACK, and stops offering it once one exists"""

    def test_listing_includes_rack_with_its_label(self, rest_api) -> None:
        """The full listing carries the RACK token and its display label"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[SpecialType.RACK.value] == RACK_LABEL

    def test_available_listing_offers_rack_while_unclaimed(self, rest_api) -> None:
        """With no Rack type in the database, RACK is offered by the creation dialog"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/?available=true')

        assert response.status_code == HTTPStatus.OK
        assert SpecialType.RACK.value in response.get_json()

    def test_available_listing_drops_rack_once_claimed(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A SpecialType exists at most once, so an existing Rack type removes it from the offer"""
        _insert_rack_type(database_manager, database_name, RACK_TYPE_ID)

        response = rest_api.get(f'{SPECIAL_TYPES_URL}/?available=true')

        assert response.status_code == HTTPStatus.OK
        assert SpecialType.RACK.value not in response.get_json()

    def test_exist_reports_false_then_true(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The exist check flips once a Rack type is present"""
        before = rest_api.get(f'{SPECIAL_TYPES_URL}/exist?special_type={SpecialType.RACK.value}')
        assert before.get_json() is False

        _insert_rack_type(database_manager, database_name, RACK_TYPE_ID)

        after = rest_api.get(f'{SPECIAL_TYPES_URL}/exist?special_type={SpecialType.RACK.value}')
        assert after.get_json() is True


class TestSpecialTypeSchema:
    """GET /special_types/schema serves the RACK blueprint the dialog builds the type from"""

    def test_schema_route_serves_the_rack_blueprint(self, rest_api) -> None:
        """The blueprint arrives marked as RACK, with all five fields and the single section"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/schema?special_type={SpecialType.RACK.value}')

        assert response.status_code == HTTPStatus.OK
        schema = response.get_json()

        assert schema[TypeSchemaKey.SPECIAL_TYPE.value] == SpecialType.RACK.value
        assert [field['name'] for field in schema['fields']] == [
            RackField.NAME.value,
            RackField.NUMBER.value,
            RackField.HEIGHT.value,
            RackField.NOTES.value,
            RackField.LOCATION.value,
        ]
        assert len(schema['sections']) == 1
        assert schema['sections'][0]['name'] == RackSection.INFORMATION.value

    def test_schema_route_still_rejects_an_unknown_special_type(self, rest_api) -> None:
        """Adding a member must not loosen the validation of the query parameter"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/schema?special_type=NOT_A_SPECIAL_TYPE')

        assert response.status_code == HTTPStatus.BAD_REQUEST

# -------------------------------------------------------------------------------------------------------------------- #
#                                                creating a Rack type                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateRackType:
    """POST /types/ creates the Rack type and enforces its invariants"""

    def test_creates_the_rack_type(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        A Rack type is created through the ordinary type route

        That this succeeds is also the proof the write is not IPAM-gated: the license guard aborts
        403 for an IPAM special type, and the test suite runs without a license.
        """
        response = rest_api.post(f'{TYPES_URL}/', json=_rack_type_payload(RACK_TYPE_ID))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = _types_collection(database_manager, database_name).find_one({'public_id': RACK_TYPE_ID})
        assert stored is not None
        assert stored[TypeSchemaKey.SPECIAL_TYPE.value] == SpecialType.RACK.value

    def test_created_rack_type_is_selectable_as_parent(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        A payload that omits the flag gets it filled in

        Without it the Rack's location node could never parent the mounted objects' nodes.
        """
        rest_api.post(f'{TYPES_URL}/', json=_rack_type_payload(RACK_TYPE_ID))

        stored = _types_collection(database_manager, database_name).find_one({'public_id': RACK_TYPE_ID})
        assert stored[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True

    def test_create_rejects_a_rack_that_is_not_selectable_as_parent(self, rest_api) -> None:
        """Explicitly disabling the flag on a Rack is refused with 400, not silently corrected"""
        payload = _rack_type_payload(RACK_TYPE_ID_REJECTED, selectable_as_parent=False)

        response = rest_api.post(f'{TYPES_URL}/', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST


class TestUpdateRackType:
    """PUT /types/<id> keeps the Rack's selectable_as_parent invariant"""

    def test_update_rejects_disabling_selectable_as_parent(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The invariant holds on update too, even with no object placed yet

        guard_selectable_as_parent_change alone would allow this, because it only blocks the flip
        while objects are already placed in the tree.
        """
        _insert_rack_type(database_manager, database_name, RACK_TYPE_ID_FOR_UPDATE)
        payload = _rack_type_payload(RACK_TYPE_ID_FOR_UPDATE, selectable_as_parent=False)

        response = rest_api.put(f'{TYPES_URL}/{RACK_TYPE_ID_FOR_UPDATE}', json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST

        stored = _types_collection(database_manager, database_name).find_one(
            {'public_id': RACK_TYPE_ID_FOR_UPDATE}
        )
        assert stored[TypeSchemaKey.SELECTABLE_AS_PARENT.value] is True

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    rack rights                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRackRights:
    """The four rack rights are part of the static rights tree served by /rights"""

    @pytest.mark.parametrize('right_name', RACK_RIGHT_NAMES)
    def test_each_rack_right_is_served(self, rest_api, right_name: str) -> None:
        """Every rack right resolves by name"""
        response = rest_api.get(f'{RIGHTS_URL}/{right_name}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['name'] == right_name

    def test_rack_rights_appear_in_the_flat_listing(self, rest_api) -> None:
        """The rights list carries the rack group and its four members"""
        response = rest_api.get(f'{RIGHTS_URL}/?limit=0')

        assert response.status_code == HTTPStatus.OK
        names = {right['name'] for right in response.get_json()['results']}

        assert set(RACK_RIGHT_NAMES) <= names
        assert 'base.framework.rack.*' in names
