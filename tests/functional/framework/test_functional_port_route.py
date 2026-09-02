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
Functional tests for the ``/ports`` REST routes

Covers the whole surface over HTTP: create / read single / read per object / update / delete, plus the
four invariants the routes exist to hold - the owner's Type must declare ``uses_ports``, the identity
and audit fields are server-owned, ``object_id`` and ``side`` are immutable after creation, and a port
name is unique per face of an object (both through the pre-check and through the unique index, which
is the half that covers concurrent writes).

Note the test database never goes through CollectionValidator, so its collections carry no declared
index. The suite builds the CmdbPort indexes itself where the index is the thing under test; without
that the duplicate-name assertions would pass on a collection with no constraint at all
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.errors.manager.types_manager import TypesManagerGetError
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.errors.manager.ports_manager import (
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerUpdateError,
)
from cmdb.errors.security import AccessDeniedError
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ports'

PORT_TYPE_ID: int = 9820          # a Type that uses ports
PLAIN_TYPE_ID: int = 9821         # a Type that does not
OWNER_OBJECT_ID: int = 9830
PLAIN_OBJECT_ID: int = 9831
SECOND_OWNER_OBJECT_ID: int = 9832
MISSING_OBJECT_ID: int = 9899
MISSING_PORT_ID: int = 9898

STATUS_OPTION_ID: int = 9840
SPEED_OPTION_ID: int = 9841

NAME_FIELD: str = 'dg-name'
PORT_NAME: str = 'Gi0/1'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [OWNER_OBJECT_ID, PLAIN_OBJECT_ID, SECOND_OWNER_OBJECT_ID]
ALL_OPTION_IDS: list[int] = [STATUS_OPTION_ID, SPEED_OPTION_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """
    Licenses IPAM so the gated /ports surface is reachable

    Port Connectivity is gated behind LicenseFeature.IPAM by decision D6 - a Type cannot declare
    `uses_ports` without it either - so every /ports route needs the feature unlocked here. That the
    gate really blocks the surface is asserted in tests/functional/license/.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, uses_ports: bool) -> dict[str, Any]:
    """A CmdbType document, port-bearing or not."""
    return {
        'public_id': public_id,
        'name': f'port-type-{public_id}',
        'label': f'Port Type {public_id}',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'uses_ports': uses_ports,
        'selectable_as_parent': True,
        'global_template_ids': [],
        'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'externals': [],
            'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
                          'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int) -> dict[str, Any]:
    """A CmdbObject document of the given type."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }


def _option_doc(public_id: int, option_type: str, value: str) -> dict[str, Any]:
    """A CmdbExtendableOption a port select field can point at."""
    return {'public_id': public_id, 'value': value, 'option_type': option_type, 'predefined': True}


def _port_payload(object_id: int = OWNER_OBJECT_ID, name: str = PORT_NAME, **overrides: Any) -> dict[str, Any]:
    """A create/update body for a port."""
    payload: dict[str, Any] = {'object_id': object_id, 'name': name}
    payload.update(overrides)

    return payload


def _ports(database_manager: MongoDatabaseManager, database_name: str):
    """The raw port collection."""
    return database_manager.get_collection(CmdbPort.COLLECTION, database_name)


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the two types, their objects and two extendable options; clears the ports around each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
    ports = _ports(database_manager, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        options.delete_many({'public_id': {'$in': ALL_OPTION_IDS}})
        ports.delete_many({PortKey.OBJECT_ID.value: {'$in': ALL_OBJECT_IDS}})

    _purge()

    types.insert_many([_type_doc(PORT_TYPE_ID, True), _type_doc(PLAIN_TYPE_ID, False)])
    objects.insert_many([
        _object_doc(OWNER_OBJECT_ID, PORT_TYPE_ID),
        _object_doc(SECOND_OWNER_OBJECT_ID, PORT_TYPE_ID),
        _object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID),
    ])
    options.insert_many([
        _option_doc(STATUS_OPTION_ID, OptionType.PORT_STATUS.value, 'Up'),
        _option_doc(SPEED_OPTION_ID, OptionType.PORT_SPEED.value, '1G'),
    ])

    yield ports

    _purge()


@pytest.fixture(name='indexed_ports')
def fixture_indexed_ports(database_manager: MongoDatabaseManager, database_name: str, seeded):
    """
    Builds the model's declared indexes, for the assertions where the index IS the thing under test

    The application does this at startup through CollectionValidator; the test database never goes
    through it, so without this a duplicate-name write would simply succeed.
    """
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    return seeded


def _create(rest_api, **kwargs: Any):
    """POSTs a port."""
    return rest_api.post(f'{ROUTE_URL}/', json=_port_payload(**kwargs))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreatePort:
    """POST /ports/"""

    def test_creates_a_port_and_stamps_the_server_owned_fields(self, rest_api, seeded) -> None:
        """The author and the creation time come from the request, never from the body."""
        response = _create(rest_api, port_number=1, description='uplink')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = seeded.find_one({PortKey.NAME.value: PORT_NAME})
        assert stored[PortKey.OBJECT_ID.value] == OWNER_OBJECT_ID
        assert stored[PortKey.SIDE.value] == PortSide.SINGLE.value
        assert stored[PortKey.AUTHOR_ID.value] == 1
        assert stored[PortKey.CREATION_TIME.value] is not None
        assert stored[PortKey.LAST_EDIT_TIME.value] is None

    def test_a_payload_public_id_is_ignored(self, rest_api, seeded) -> None:
        """The identity is server-owned: a body may not choose the port's public_id."""
        response = rest_api.post(f'{ROUTE_URL}/', json={**_port_payload(), 'public_id': 4242})

        new_id = response.get_json()['result_id']

        assert new_id != 4242
        assert seeded.find_one({PortKey.PUBLIC_ID.value: 4242}) is None

    def test_accepts_a_panel_side(self, rest_api, seeded) -> None:
        """front/rear is what the patch-panel assistant will send."""
        assert _create(rest_api, name='1', side=PortSide.FRONT.value).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        assert seeded.find_one({PortKey.NAME.value: '1'})[PortKey.SIDE.value] == PortSide.FRONT.value

    def test_refuses_an_unknown_side(self, rest_api) -> None:
        """The unique index keys on the side, so a free-text value would be its own name space."""
        assert _create(rest_api, side='middle').status_code == HTTPStatus.BAD_REQUEST

    def test_refuses_a_type_that_does_not_use_ports(self, rest_api) -> None:
        """Step 1's flag: a port on a type without it would be invisible in the UI."""
        response = _create(rest_api, object_id=PLAIN_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'does not use ports' in response.get_json()['message']

    def test_refuses_a_missing_owner(self, rest_api) -> None:
        """A port cannot belong to an object that does not exist."""
        assert _create(rest_api, object_id=MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND

    @pytest.mark.parametrize('object_id', [None, 'x'], ids=['none', 'string'])
    def test_refuses_a_body_without_a_usable_owner(self, rest_api, object_id: Any) -> None:
        """No owner, no port - and no query either."""
        assert _create(rest_api, object_id=object_id).status_code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('name', [None, '', '  '], ids=['absent', 'empty', 'blank'])
    def test_refuses_a_blank_name(self, rest_api, name: Any) -> None:
        """The name is the port's identifier within its face."""
        payload = _port_payload()

        if name is None:
            payload.pop('name')
        else:
            payload['name'] = name

        assert rest_api.post(f'{ROUTE_URL}/', json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_accepts_valid_select_values(self, rest_api, seeded) -> None:
        """A status and a speed from the right lists are stored as given."""
        response = _create(rest_api, status=STATUS_OPTION_ID, speed=SPEED_OPTION_ID)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = seeded.find_one({PortKey.NAME.value: PORT_NAME})
        assert stored[PortKey.STATUS.value] == STATUS_OPTION_ID
        assert stored[PortKey.SPEED.value] == SPEED_OPTION_ID

    def test_refuses_an_option_from_the_wrong_list(self, rest_api) -> None:
        """
        A PORT_STATUS id in the speed field would be stored and then rendered AS a speed

        The check is per field, against the OptionType that field draws from.
        """
        response = _create(rest_api, speed=STATUS_OPTION_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'PORT_SPEED' in response.get_json()['message']

    def test_refuses_an_unknown_option(self, rest_api) -> None:
        """An id nothing answers to is refused rather than stored."""
        assert _create(rest_api, status=999999).status_code == HTTPStatus.BAD_REQUEST

    def test_refuses_a_duplicate_name_on_the_same_side(self, rest_api) -> None:
        """The readable half of the uniqueness rule."""
        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        response = _create(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already exists' in response.get_json()['message']

    def test_the_same_name_is_free_on_the_other_side(self, rest_api, seeded) -> None:
        """A patch panel legitimately has a front 1 and a rear 1."""
        assert _create(rest_api, name='1', side=PortSide.FRONT.value).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert _create(rest_api, name='1', side=PortSide.REAR.value).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        assert seeded.count_documents({PortKey.NAME.value: '1'}) == 2

    def test_the_same_name_is_free_on_another_object(self, rest_api, seeded) -> None:
        """Port names are unique per object, not globally - every switch has a port 1."""
        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        assert _create(rest_api, object_id=SECOND_OWNER_OBJECT_ID).status_code \
            in (HTTPStatus.OK, HTTPStatus.CREATED)

        assert seeded.count_documents({PortKey.NAME.value: PORT_NAME}) == 2

    def test_a_duplicate_only_the_index_catches_is_still_a_400(self, rest_api, indexed_ports,
                                                              monkeypatch) -> None:
        """
        The race the index exists for: the pre-check passes, the write is refused anyway

        The pre-check is a read followed by a write, so a concurrent create can store the name in
        between. Patching the pre-check to miss reproduces that without threads - the route must
        answer the same readable 400, not a 500 about a database error.
        """
        indexed_ports.insert_one({
            PortKey.PUBLIC_ID.value: 9850,
            PortKey.OBJECT_ID.value: OWNER_OBJECT_ID,
            PortKey.SIDE.value: PortSide.SINGLE.value,
            PortKey.NAME.value: PORT_NAME,
        })
        monkeypatch.setattr(PortsManager, 'get_port_by_name', lambda *_a, **_k: None)

        response = _create(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already exists' in response.get_json()['message']
        assert indexed_ports.count_documents({PortKey.NAME.value: PORT_NAME}) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadPort:
    """GET /ports/<id> and GET /ports/object/<object_id>"""

    def test_reads_a_single_port(self, rest_api) -> None:
        """The ordinary case."""
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.get(f'{ROUTE_URL}/{new_id}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result'][PortKey.NAME.value] == PORT_NAME

    def test_a_missing_port_is_404(self, rest_api) -> None:
        """Not an empty 200."""
        assert rest_api.get(f'{ROUTE_URL}/{MISSING_PORT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_reads_the_ports_of_one_object_in_order(self, rest_api) -> None:
        """Ordered by port number, then by name - a port without a number still has a place."""
        _create(rest_api, name='second', port_number=2)
        _create(rest_api, name='first', port_number=1)
        _create(rest_api, name='unnumbered')

        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        # DefaultResponse hands the payload back as-is, so the body IS the list
        names = [port[PortKey.NAME.value] for port in response.get_json()]
        assert names == ['unnumbered', 'first', 'second']

    def test_an_object_without_ports_answers_with_an_empty_list(self, rest_api) -> None:
        """'No ports yet' is a normal state, not a 404."""
        response = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_reads_only_the_addressed_object_s_ports(self, rest_api) -> None:
        """Another object's ports must not leak into the list."""
        _create(rest_api)
        _create(rest_api, object_id=SECOND_OWNER_OBJECT_ID, name='other')

        result = rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').get_json()

        assert [port[PortKey.NAME.value] for port in result] == [PORT_NAME]

    def test_the_ports_of_a_missing_object_are_404(self, rest_api) -> None:
        """The owner is resolved before its ports are listed, so its ACL applies."""
        assert rest_api.get(f'{ROUTE_URL}/object/{MISSING_OBJECT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_a_type_without_the_flag_may_still_be_read(self, rest_api) -> None:
        """
        The flag guards CREATING a port, not reading one

        A type whose flag was turned off after its ports were created must still show them, otherwise
        they become unreachable rows nobody can clean up.
        """
        assert rest_api.get(f'{ROUTE_URL}/object/{PLAIN_OBJECT_ID}').status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdatePort:
    """PUT /ports/<id>"""

    def test_updates_the_user_facing_fields_and_stamps_the_edit(self, rest_api, seeded) -> None:
        """The creation stamp survives, the edit stamp is set."""
        new_id = _create(rest_api).get_json()['result_id']
        created = seeded.find_one({PortKey.PUBLIC_ID.value: new_id})

        response = rest_api.put(f'{ROUTE_URL}/{new_id}',
                                json=_port_payload(name='renamed', description='now with a description'))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        stored = seeded.find_one({PortKey.PUBLIC_ID.value: new_id})
        assert stored[PortKey.NAME.value] == 'renamed'
        assert stored[PortKey.DESCRIPTION.value] == 'now with a description'
        assert stored[PortKey.CREATION_TIME.value] == created[PortKey.CREATION_TIME.value]
        assert stored[PortKey.LAST_EDIT_TIME.value] is not None

    def test_keeping_the_name_is_allowed(self, rest_api) -> None:
        """A port must not clash with itself."""
        new_id = _create(rest_api).get_json()['result_id']

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload()).status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_refuses_a_name_another_port_holds(self, rest_api) -> None:
        """The uniqueness rule applies to updates too."""
        _create(rest_api, name='taken')
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload(name='taken'))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_refuses_moving_the_port_to_another_object(self, rest_api) -> None:
        """Refused rather than ignored, so the caller learns the edit did nothing."""
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.put(f'{ROUTE_URL}/{new_id}',
                                json=_port_payload(object_id=SECOND_OWNER_OBJECT_ID))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'can not be changed' in response.get_json()['message']

    def test_refuses_changing_the_side(self, rest_api) -> None:
        """Changing it would move the port into another face's name space."""
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload(side=PortSide.REAR.value))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_payload_repeating_the_immutable_values_is_accepted(self, rest_api) -> None:
        """The routes take the whole port, so round-tripping a GET must work."""
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.put(f'{ROUTE_URL}/{new_id}',
                                json=_port_payload(side=PortSide.SINGLE.value))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_refuses_an_invalid_select_value(self, rest_api) -> None:
        """The same per-field option check as on create."""
        new_id = _create(rest_api).get_json()['result_id']

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload(status=999999)).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_a_missing_port_is_404(self, rest_api) -> None:
        """Nothing to update."""
        assert rest_api.put(f'{ROUTE_URL}/{MISSING_PORT_ID}', json=_port_payload()).status_code \
            == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeletePort:
    """DELETE /ports/<id>"""

    def test_deletes_the_port_and_leaves_the_object_alone(self, rest_api, seeded,
                                                          database_manager, database_name) -> None:
        """Deleting a port never touches its owner."""
        new_id = _create(rest_api).get_json()['result_id']

        response = rest_api.delete(f'{ROUTE_URL}/{new_id}')

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert seeded.find_one({PortKey.PUBLIC_ID.value: new_id}) is None
        assert database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
            .find_one({'public_id': OWNER_OBJECT_ID}) is not None

    def test_a_missing_port_is_404(self, rest_api) -> None:
        """Nothing to delete."""
        assert rest_api.delete(f'{ROUTE_URL}/{MISSING_PORT_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_the_name_is_free_again_afterwards(self, rest_api) -> None:
        """The uniqueness rule is about live ports only."""
        new_id = _create(rest_api).get_json()['result_id']
        rest_api.delete(f'{ROUTE_URL}/{new_id}')

        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    OBJECT CASCADE                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestObjectDeleteCascade:
    """Deleting the owner CmdbObject takes its ports with it."""

    def test_deleting_the_object_removes_its_ports(self, rest_api, seeded) -> None:
        """
        Nothing else would: a port lives outside its owner's document

        Without the cascade every deleted object would leave rows behind that no route can reach.
        """
        _create(rest_api, name='first')
        _create(rest_api, name='second')

        assert rest_api.delete(f'/objects/{OWNER_OBJECT_ID}').status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        assert seeded.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_another_object_s_ports_survive(self, rest_api, seeded) -> None:
        """The cascade is scoped to the deleted object."""
        _create(rest_api)
        _create(rest_api, object_id=SECOND_OWNER_OBJECT_ID, name='survivor')

        rest_api.delete(f'/objects/{OWNER_OBJECT_ID}')

        assert seeded.count_documents({PortKey.OBJECT_ID.value: SECOND_OWNER_OBJECT_ID}) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  THE OWNER'S ACL                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _access_denied(*_args: Any, **_kwargs: Any) -> None:
    """Stands in for the owner object's ACL refusing the caller."""
    raise AccessDeniedError('nope')


class TestOwnerAcl:
    """
    Every route resolves the owner object through the ACL-aware getter, and maps its refusal to 403

    A port is stored outside its owner's document, so nothing about it inherits the object's access
    control - without these the port rights alone would let a caller read and write the ports of an
    object they cannot see. Each case patches ObjectsManager.get_object to refuse, the same seam the
    /objects routes' own 403 tests use.
    """

    def test_create_is_403_when_the_owner_is_denied(self, rest_api, monkeypatch) -> None:
        """Creating a port needs UPDATE on the owner."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _access_denied)

        assert _create(rest_api).status_code == HTTPStatus.FORBIDDEN

    def test_single_read_is_403_when_the_owner_is_denied(self, rest_api, monkeypatch) -> None:
        """Reading a port means reading part of its owner."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(ObjectsManager, 'get_object', _access_denied)

        assert rest_api.get(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.FORBIDDEN

    def test_object_read_is_403_when_the_owner_is_denied(self, rest_api, monkeypatch) -> None:
        """The ports panel of an invisible object stays invisible."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _access_denied)

        assert rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').status_code == HTTPStatus.FORBIDDEN

    def test_update_is_403_when_the_owner_is_denied(self, rest_api, monkeypatch) -> None:
        """Editing a port needs UPDATE on the owner."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(ObjectsManager, 'get_object', _access_denied)

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload()).status_code \
            == HTTPStatus.FORBIDDEN

    def test_delete_is_403_when_the_owner_is_denied(self, rest_api, monkeypatch, seeded) -> None:
        """A refused delete must leave the port in place."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(ObjectsManager, 'get_object', _access_denied)

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.FORBIDDEN
        assert seeded.find_one({PortKey.PUBLIC_ID.value: new_id}) is not None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   ERROR MAPPING                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


class TestErrorMapping:
    """
    A database failure is a 400, anything unexpected a 500 - never the other way round

    A manager error surfacing as a 500 hides a recoverable problem; an unexpected error surfacing as a
    400 tells the caller their request was wrong when it was not.
    """

    def test_create_retrieval_of_the_created_port_failing_is_404(self, rest_api, monkeypatch) -> None:
        """The insert worked but the read-back did not, so the response would be empty."""
        monkeypatch.setattr(PortsManager, 'get_item', lambda *_a, **_k: None)

        assert _create(rest_api).status_code == HTTPStatus.NOT_FOUND

    def test_create_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request."""
        monkeypatch.setattr(PortsManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert _create(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_single_read_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed read is reported as a bad request, not as a crash."""
        monkeypatch.setattr(PortsManager, 'get_item', _raiser(PortsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/1').status_code == HTTPStatus.BAD_REQUEST

    def test_single_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(PortsManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/1').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_object_read_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """The list route maps its own manager error."""
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(PortsManagerGetError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').status_code == HTTPStatus.BAD_REQUEST

    def test_object_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{ROUTE_URL}/object/{OWNER_OBJECT_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed write is reported as a bad request."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(PortsManager, 'update_item', _raiser(PortsManagerUpdateError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload()).status_code \
            == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(PortsManager, 'update_item', _raiser(RuntimeError('boom')))

        assert rest_api.put(f'{ROUTE_URL}/{new_id}', json=_port_payload()).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed delete is reported as a bad request."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(PortsManager, 'delete_item', _raiser(PortsManagerDeleteError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id = _create(rest_api).get_json()['result_id']
        monkeypatch.setattr(PortsManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{ROUTE_URL}/{new_id}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                       THE uses_ports TRUE -> FALSE GUARD                                             #
# -------------------------------------------------------------------------------------------------------------------- #
TYPES_URL: str = '/types'


def _type_payload(public_id: int, uses_ports: bool) -> dict[str, Any]:
    """A CmdbType update payload carrying the uses_ports flag."""
    payload = _type_doc(public_id, uses_ports)
    payload.pop('creation_time', None)

    return payload


class TestUsesPortsGuard:
    """
    A Type may only stop using ports once none of its Objects has one

    The mirror of dropping the virtual template: the frontend renders the ports panel for a
    port-bearing Type only, so clearing the flag would leave those ports as rows nothing in the UI can
    reach - and the port create route would refuse to recreate them.
    """

    def test_the_usage_route_reports_a_free_type(self, rest_api) -> None:
        """in_use false is the type builder's green light to remove the section."""
        response = rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}')

        assert response.status_code == HTTPStatus.OK
        body = response.get_json()
        assert body['in_use'] is False
        assert body['port_count'] == 0
        assert body['object_count'] == 0

    def test_the_usage_route_reports_the_counts(self, rest_api) -> None:
        """Two ports on one object, and a second object of the same type with one more."""
        _create(rest_api, name='1')
        _create(rest_api, name='2')
        _create(rest_api, object_id=SECOND_OWNER_OBJECT_ID, name='1')

        body = rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}').get_json()

        assert body['in_use'] is True
        assert body['port_count'] == 3
        assert body['object_count'] == 2

    def test_the_usage_route_carries_no_id_list(self, rest_api) -> None:
        """Counts only - the equivalent location payload is unbounded (backlog #187)."""
        _create(rest_api)

        body = rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}').get_json()

        assert set(body) == {'in_use', 'port_count', 'object_count'}

    def test_the_usage_route_404s_for_a_missing_type(self, rest_api) -> None:
        """Consistent with the other pre-check routes on the types blueprint."""
        assert rest_api.get(f'{TYPES_URL}/uses_ports_usage/999999').status_code == HTTPStatus.NOT_FOUND

    def test_the_usage_route_is_not_license_gated(self, rest_api, monkeypatch) -> None:
        """
        Turning the flag off is the cleanup direction, which a lapsed license must not block

        Gating the pre-check would blind exactly the users who need it. Asserted with EVERY feature
        locked, which is what a free installation looks like.
        """
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

        assert rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}').status_code == HTTPStatus.OK

    def test_the_usage_route_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed read is reported as a bad request, not as a crash."""
        monkeypatch.setattr(TypesManager, 'get_type_instance',
                            _raiser(TypesManagerGetError('boom')))

        assert rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}').status_code \
            == HTTPStatus.BAD_REQUEST

    def test_the_usage_route_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error, not a masked 400."""
        monkeypatch.setattr(TypesManager, 'get_type_instance', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{TYPES_URL}/uses_ports_usage/{PORT_TYPE_ID}').status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_the_update_refuses_turning_the_flag_off_while_ports_exist(self, rest_api) -> None:
        """The server-side half of the same rule, naming both counts."""
        _create(rest_api)

        response = rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}',
                                json=_type_payload(PORT_TYPE_ID, uses_ports=False))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        message = response.get_json()['message']
        assert "Cannot disable 'uses ports'" in message
        assert '1 Port(s)' in message

    def test_the_refused_update_persists_nothing(self, rest_api, database_manager, database_name) -> None:
        """A refused update must not write the allowed half of its payload either."""
        _create(rest_api)

        payload = _type_payload(PORT_TYPE_ID, uses_ports=False)
        payload['label'] = 'Renamed by a refused update'

        rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}', json=payload)

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': PORT_TYPE_ID})

        assert stored['uses_ports'] is True
        assert stored['label'] != 'Renamed by a refused update'

    def test_the_update_allows_turning_the_flag_off_without_ports(self, rest_api, database_manager,
                                                                 database_name) -> None:
        """Nothing to lose, so the section may be removed."""
        response = rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}',
                                json=_type_payload(PORT_TYPE_ID, uses_ports=False))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        stored = database_manager.get_collection(CmdbType.COLLECTION, database_name)\
            .find_one({'public_id': PORT_TYPE_ID})

        assert stored['uses_ports'] is False

    def test_deleting_the_ports_unblocks_the_transition(self, rest_api) -> None:
        """The documented way out: remove the ports, then clear the flag."""
        new_id = _create(rest_api).get_json()['result_id']

        assert rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}',
                            json=_type_payload(PORT_TYPE_ID, uses_ports=False)).status_code \
            == HTTPStatus.BAD_REQUEST

        rest_api.delete(f'{ROUTE_URL}/{new_id}')

        assert rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}',
                            json=_type_payload(PORT_TYPE_ID, uses_ports=False)).status_code \
            in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_a_port_of_another_type_does_not_block(self, rest_api, database_manager,
                                                  database_name) -> None:
        """
        The usage question is scoped to the Type's own objects

        A filter that forgot the $in over those ids would count every port in the installation and
        make the flag impossible to clear anywhere.
        """
        ports = _ports(database_manager, database_name)
        ports.insert_one({
            PortKey.PUBLIC_ID.value: 9855,
            PortKey.OBJECT_ID.value: PLAIN_OBJECT_ID,
            PortKey.SIDE.value: PortSide.SINGLE.value,
            PortKey.NAME.value: 'foreign',
        })

        response = rest_api.put(f'{TYPES_URL}/{PORT_TYPE_ID}',
                                json=_type_payload(PORT_TYPE_ID, uses_ports=False))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
