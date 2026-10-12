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
Functional tests of ``POST /objects/?clone_ports_from=<id>`` - creating an object with copies of another object's
ports

The new object gets one new port per source port, with the same side, name, number and field values, and the
source's INTERNAL pairing remapped onto the new ports; the source's cable and interface links stay with the
source. Every refusal happens before anything is written, and a clone that fails part-way leaves neither the
object nor any port behind
"""
import base64
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.port_interface_link_model.cmdb_port_interface_link import CmdbPortInterfaceLink
from cmdb.models.port_interface_link_model.port_interface_link_constants import PortInterfaceLinkKey
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.models.user_model import CmdbUser
from cmdb.errors.manager.port_connections_manager import PortConnectionsManagerInsertError
from cmdb.errors.security import AccessDeniedError
from cmdb.interface import route_utils
from cmdb.interface.route_utils import API_KEY_HEADER
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.routes.port_routes import port_object_hooks
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PortCloneError, PortRight
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.cloud_mode import enable_hosted_cloud_mode
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects/'
PORT_TYPE_ID: int = 98310
PLAIN_TYPE_ID: int = 98311
SOURCE_ID: int = 98312
NEW_ID: int = 98313
PEER_ID: int = 98314
EMPTY_SOURCE_ID: int = 98315
MISSING_ID: int = 98316
F1_ID, R1_ID, F2_ID, R2_ID, PEER_PORT_ID = 98320, 98321, 98322, 98323, 98324
LINK_ID: int = 98330
STATUS_OPTION, TYPE_OPTION, SPEED_OPTION = 98340, 98341, 98342
SOURCE_AUTHOR_ID: int = 77
CLOUD_USER_ID: int = 98360
CLOUD_EMAIL: str = 'cloud-port-clone@x.io'
CLOUD_PASSWORD: str = 'portal-password'
CLOUD_ITEM_LIMIT: int = 1_000_000
ADMIN_GROUP_ID: int = 1
API_KEY_ENVIRON: str = f'HTTP_{API_KEY_HEADER.upper().replace("-", "_")}'
NAME_FIELD: str = 'dg-name'
SOURCE_PORT_IDS: list[int] = [F1_ID, R1_ID, F2_ID, R2_ID]
OBJECT_IDS: list[int] = [SOURCE_ID, NEW_ID, PEER_ID, EMPTY_SOURCE_ID]
TYPE_IDS: list[int] = [PORT_TYPE_ID, PLAIN_TYPE_ID]
PANEL: list[tuple[int, str, str, int]] = [
    (F1_ID, PortSide.FRONT.value, 'F1', 1), (R1_ID, PortSide.REAR.value, 'R1', 1),
    (F2_ID, PortSide.FRONT.value, 'F2', 2), (R2_ID, PortSide.REAR.value, 'R2', 2),
]


def _type_doc(public_id: int, uses_ports: bool) -> dict[str, Any]:
    """A CmdbType with one text field."""
    return {
        'public_id': public_id, 'name': f'clone-type-{public_id}', 'label': f'Clone {public_id}', 'author_id': 1,
        'active': True, 'version': '1.0.0', 'uses_ports': uses_ports, 'selectable_as_parent': True,
        'global_template_ids': [], 'fields': [{'type': FieldType.TEXT.value, 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {'icon': 'fa-cube', 'externals': [], 'summary': {'fields': [NAME_FIELD]},
                        'sections': [{'type': SectionType.SECTION.value, 'name': 'main', 'label': 'Main',
                                      'fields': [NAME_FIELD]}]},
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int = PORT_TYPE_ID) -> dict[str, Any]:
    """A CmdbObject - stored, or the create body."""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'fields': [{'name': NAME_FIELD, 'value': f'device-{public_id}', 'type': FieldType.TEXT.value}]}


def _port_doc(public_id: int, side: str, name: str, number: int, object_id: int = SOURCE_ID) -> dict[str, Any]:
    """A stored port with every field value set."""
    return {
        PortKey.PUBLIC_ID.value: public_id, PortKey.OBJECT_ID.value: object_id, PortKey.SIDE.value: side,
        PortKey.NAME.value: name, PortKey.PORT_NUMBER.value: number, PortKey.STATUS.value: STATUS_OPTION,
        PortKey.PORT_TYPE.value: TYPE_OPTION, PortKey.SPEED.value: SPEED_OPTION,
        PortKey.DESCRIPTION.value: f'{name} of the source', PortKey.AUTHOR_ID.value: SOURCE_AUTHOR_ID,
    }


def _connection_doc(public_id: int, endpoints: list[int], connection_type: ConnectionType) -> dict[str, Any]:
    """A stored connection."""
    return {PortConnectionKey.PUBLIC_ID.value: public_id, PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
            PortConnectionKey.CONNECTION_TYPE.value: connection_type.value, PortConnectionKey.AUTHOR_ID.value: 1}


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """IPAM licensed, unless a test locks it."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


@pytest.fixture(name='db', autouse=True)
def fixture_db(database_manager: MongoDatabaseManager, database_name: str):
    """A panel source (two pairs, a cable on F1, an interface link on F1), a peer and an empty source"""
    def _collection(name: str):
        return database_manager.get_collection(name, database_name)

    collections = {name: _collection(name) for name in (CmdbType.COLLECTION, CmdbObject.COLLECTION,
                                                         CmdbPort.COLLECTION, CmdbPortConnection.COLLECTION,
                                                         CmdbPortInterfaceLink.COLLECTION)}

    def _purge() -> None:
        ports = collections[CmdbPort.COLLECTION]
        port_ids = [row[PortKey.PUBLIC_ID.value] for row in ports.find({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})]
        collections[CmdbPortConnection.COLLECTION].delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}})
        collections[CmdbPortInterfaceLink.COLLECTION].delete_many(
            {PortInterfaceLinkKey.PORT_ID.value: {'$in': port_ids}})
        ports.delete_many({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})
        collections[CmdbObject.COLLECTION].delete_many({'public_id': {'$in': OBJECT_IDS}})
        collections[CmdbType.COLLECTION].delete_many({'public_id': {'$in': TYPE_IDS}})

    _purge()
    collections[CmdbType.COLLECTION].insert_many([_type_doc(PORT_TYPE_ID, True), _type_doc(PLAIN_TYPE_ID, False)])
    collections[CmdbObject.COLLECTION].insert_many(
        [_object_doc(SOURCE_ID), _object_doc(PEER_ID), _object_doc(EMPTY_SOURCE_ID)])
    collections[CmdbPort.COLLECTION].insert_many(
        [_port_doc(*row) for row in PANEL] + [_port_doc(PEER_PORT_ID, PortSide.SINGLE.value, 'P1', 1, PEER_ID)])
    collections[CmdbPortConnection.COLLECTION].insert_many([
        _connection_doc(98350, [F1_ID, R1_ID], ConnectionType.INTERNAL),
        _connection_doc(98351, [F2_ID, R2_ID], ConnectionType.INTERNAL),
        _connection_doc(98352, [F1_ID, PEER_PORT_ID], ConnectionType.CABLE),
    ])
    collections[CmdbPortInterfaceLink.COLLECTION].insert_one({
        PortInterfaceLinkKey.PUBLIC_ID.value: LINK_ID, PortInterfaceLinkKey.PORT_ID.value: F1_ID,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: SOURCE_ID,
    })

    yield collections

    _purge()


def _clone(rest_api, source: Any = SOURCE_ID, type_id: int = PORT_TYPE_ID):
    """POST /objects/?clone_ports_from=<source> creating NEW_ID"""
    return rest_api.post(f'{OBJECTS_URL}?clone_ports_from={source}', json=_object_doc(NEW_ID, type_id))


def _new_ports(db) -> list[dict[str, Any]]:
    """The new object's ports, by number then side."""
    return list(db[CmdbPort.COLLECTION].find({PortKey.OBJECT_ID.value: NEW_ID}, {'_id': 0}).sort(
        [(PortKey.PORT_NUMBER.value, 1), (PortKey.SIDE.value, 1)]))


def _connections_of(db, port_ids: list[int]) -> list[dict[str, Any]]:
    """The connections touching any of the ports."""
    return list(db[CmdbPortConnection.COLLECTION].find({PortConnectionKey.ENDPOINTS.value: {'$in': port_ids}}))


def _assert_nothing_written(db) -> None:
    """Neither the object nor a port"""
    assert db[CmdbObject.COLLECTION].find_one({'public_id': NEW_ID}) is None
    assert not _new_ports(db)


class TestTheClone:
    """What the new object gets"""

    def test_every_port_is_copied_under_a_new_id(self, rest_api, db) -> None:
        """Side, name, number and field values; owner, author and id its own"""
        assert _clone(rest_api).status_code == HTTPStatus.OK

        cloned = _new_ports(db)
        copied = [PortKey.SIDE, PortKey.NAME, PortKey.PORT_NUMBER, PortKey.STATUS, PortKey.PORT_TYPE,
                  PortKey.SPEED, PortKey.DESCRIPTION]
        sources = {row[0]: _port_doc(*row) for row in PANEL}

        assert sorted((port[PortKey.SIDE.value], port[PortKey.NAME.value]) for port in cloned) == sorted(
            (side, name) for _, side, name, _ in PANEL)
        for port in cloned:
            source = next(doc for doc in sources.values() if doc[PortKey.NAME.value] == port[PortKey.NAME.value])
            assert {key: port[key.value] for key in copied} == {key: source[key.value] for key in copied}
            assert port[PortKey.PUBLIC_ID.value] not in SOURCE_PORT_IDS
            assert port[PortKey.AUTHOR_ID.value] == 1

    def test_the_pairing_is_remapped_onto_the_new_ports(self, rest_api, db) -> None:
        """F1-R1 and F2-R2 again, as two INTERNAL connections; no cable"""
        _clone(rest_api)
        by_name = {port[PortKey.NAME.value]: port[PortKey.PUBLIC_ID.value] for port in _new_ports(db)}

        connections = _connections_of(db, list(by_name.values()))

        assert sorted(tuple(row[PortConnectionKey.ENDPOINTS.value]) for row in connections) == sorted([
            tuple(sorted([by_name['F1'], by_name['R1']])), tuple(sorted([by_name['F2'], by_name['R2']]))])
        assert {row[PortConnectionKey.CONNECTION_TYPE.value] for row in connections} == {
            ConnectionType.INTERNAL.value}

    def test_interface_links_are_not_copied(self, rest_api, db) -> None:
        """They name the source's interface rows"""
        _clone(rest_api)
        new_ids = [port[PortKey.PUBLIC_ID.value] for port in _new_ports(db)]

        assert db[CmdbPortInterfaceLink.COLLECTION].count_documents(
            {PortInterfaceLinkKey.PORT_ID.value: {'$in': new_ids}}) == 0

    def test_the_source_keeps_everything(self, rest_api, db) -> None:
        """Its ports, its pairing, its cable and its link"""
        _clone(rest_api)

        assert db[CmdbPort.COLLECTION].count_documents({PortKey.OBJECT_ID.value: SOURCE_ID}) == len(PANEL)
        assert len(_connections_of(db, SOURCE_PORT_IDS)) == 3
        assert db[CmdbPortInterfaceLink.COLLECTION].find_one({PortInterfaceLinkKey.PUBLIC_ID.value: LINK_ID})

    def test_a_source_without_ports_needs_neither_licence_nor_right(self, rest_api, db, monkeypatch) -> None:
        """The object is created, with no port"""
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)
        monkeypatch.setattr(port_object_hooks, 'user_has_right', lambda _right, _user: False)

        assert _clone(rest_api, EMPTY_SOURCE_ID, PLAIN_TYPE_ID).status_code == HTTPStatus.OK
        assert db[CmdbObject.COLLECTION].find_one({'public_id': NEW_ID}) and not _new_ports(db)

    def test_without_the_parameter_no_port_is_copied(self, rest_api, db) -> None:
        """The ordinary create"""
        assert rest_api.post(OBJECTS_URL, json=_object_doc(NEW_ID)).status_code == HTTPStatus.OK
        assert not _new_ports(db)


class TestRefusals:
    """Nothing is written"""

    @pytest.mark.parametrize('value', ['abc', '0', '-1', '1.5'], ids=['text', 'zero', 'negative', 'decimal'])
    def test_a_source_that_is_no_id_is_400(self, rest_api, db, value: str) -> None:
        """Named in the message"""
        response = _clone(rest_api, value)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PortCloneError.SOURCE_INVALID.format(
            param='clone_ports_from', value=value)
        _assert_nothing_written(db)

    def test_a_missing_source_is_404(self, rest_api, db) -> None:
        """The source is named"""
        response = _clone(rest_api, MISSING_ID)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == PortCloneError.SOURCE_NOT_FOUND.format(object_id=MISSING_ID)
        _assert_nothing_written(db)

    def test_an_unreadable_source_is_403(self, rest_api, db, monkeypatch) -> None:
        """The source's ACL denies READ"""
        original = ObjectsManager.get_object

        def _deny_source(self, public_id: int, *args: Any, **kwargs: Any):
            if public_id == SOURCE_ID and AccessControlPermission.READ in args:
                raise AccessDeniedError('denied')
            return original(self, public_id, *args, **kwargs)

        monkeypatch.setattr(ObjectsManager, 'get_object', _deny_source)
        response = _clone(rest_api)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == PortCloneError.SOURCE_NOT_READABLE.format(object_id=SOURCE_ID)
        _assert_nothing_written(db)

    def test_an_unlicensed_installation_is_403(self, rest_api, db, monkeypatch) -> None:
        """The source has ports"""
        monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: False)

        assert _clone(rest_api).status_code == HTTPStatus.FORBIDDEN
        _assert_nothing_written(db)

    def test_a_caller_without_the_port_add_right_is_403(self, rest_api, db, monkeypatch) -> None:
        """Naming the right"""
        monkeypatch.setattr(port_object_hooks, 'user_has_right', lambda right, _user: right != PortRight.ADD.value)
        response = _clone(rest_api)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == PortCloneError.RIGHT_MISSING.format(
            object_id=SOURCE_ID, right=PortRight.ADD.value)
        _assert_nothing_written(db)

    def test_a_new_object_whose_type_has_no_ports_is_400(self, rest_api, db) -> None:
        """Its ports would be invisible"""
        response = _clone(rest_api, type_id=PLAIN_TYPE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PortCloneError.TYPE_WITHOUT_PORTS.format(object_id=SOURCE_ID)
        _assert_nothing_written(db)

    def test_more_ports_than_a_bulk_create_may_write_is_400(self, rest_api, db, monkeypatch) -> None:
        """The cap lowered below the source's four ports"""
        limit: int = len(PANEL) - 1
        monkeypatch.setattr(port_object_hooks, 'MAX_BULK_PORT_COUNT', limit)
        response = _clone(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == PortCloneError.TOO_MANY.format(object_id=SOURCE_ID, limit=limit)
        _assert_nothing_written(db)


class TestAllOrNothing:
    """A clone failing part-way"""

    def test_a_failed_pairing_takes_the_ports_and_the_object_with_it(self, rest_api, db, monkeypatch) -> None:
        """The ports were written, the connections were not"""
        def _fail(*_args: Any, **_kwargs: Any) -> None:
            raise PortConnectionsManagerInsertError('write failed')

        monkeypatch.setattr(PortConnectionsManager, 'insert_many_items', _fail)

        assert _clone(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        _assert_nothing_written(db)
        assert len(_connections_of(db, SOURCE_PORT_IDS)) == 3


@pytest.fixture(name='cloud')
def fixture_cloud(rest_api, monkeypatch: pytest.MonkeyPatch, database_manager: MongoDatabaseManager,
                  database_name: str):
    """A hosted-cloud app, a stored tenant admin and a portal that accepts it at ADMIN level"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    users.delete_many({'public_id': CLOUD_USER_ID})
    users.insert_one({
        'public_id': CLOUD_USER_ID, 'user_name': 'cloud-port-clone', 'email': CLOUD_EMAIL, 'active': True,
        'group_id': ADMIN_GROUP_ID, 'database': database_name, 'api_level': ApiLevel.ADMIN,
        'registration_time': datetime.now(timezone.utc),
    })
    portal = {
        'email': CLOUD_EMAIL, 'user_name': 'cloud-port-clone', 'password': CLOUD_PASSWORD, 'api_level': ApiLevel.ADMIN,
        'subscriptions': [{'id': 1, 'name': 'sub', 'database': database_name, 'api_level': ApiLevel.ADMIN,
                           'config_item_limit': CLOUD_ITEM_LIMIT}],
    }

    enable_hosted_cloud_mode(rest_api, monkeypatch, database_manager)
    monkeypatch.setattr(route_utils, 'check_user_in_service_portal', lambda *_args, **_kwargs: portal)

    yield

    users.delete_many({'public_id': CLOUD_USER_ID})


@pytest.mark.usefixtures('cloud')
class TestTheCloudApiKey:
    """The port routes are closed to the cloud API key, and so is cloning ports through the object create"""

    def test_a_source_with_ports_is_403(self, rest_api, db) -> None:
        """An ADMIN-level key reaches the object create, not the ports"""
        basic: str = base64.b64encode(f'{CLOUD_EMAIL}:{CLOUD_PASSWORD}'.encode('utf-8')).decode('utf-8')
        environ = {'HTTP_AUTHORIZATION': f'Basic {basic}', API_KEY_ENVIRON: 'subscription-key'}

        response = rest_api.post(f'{OBJECTS_URL}?clone_ports_from={SOURCE_ID}', json=_object_doc(NEW_ID),
                                 environ_overrides=environ)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == PortCloneError.API_KEY_LOCKED.format(object_id=SOURCE_ID)
        _assert_nothing_written(db)
