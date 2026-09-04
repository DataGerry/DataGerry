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
Functional tests for the bulk port creation route

The other half of the creation assistant, and the half that writes. Three things are asserted here that
nothing else can:

* **what is created is exactly what the preview showed** - the same body through both routes produces
  the same names, because they run the same builders
* **a patch panel comes back paired**, with one INTERNAL connection per pair, built from the ports'
  public_ids rather than from their names
* **a batch with collisions is refused before a single row is written**, rather than failing on the
  twelfth port and leaving a half-built device behind

The rollback itself is exercised in tests/integration/, where a failure can be forced mid-batch against
a real database
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.ports_manager import PortsManager
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.security import AccessDeniedError
from cmdb.manager.ports_manager import PortsManager
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.models.port_connection_model import (
    CmdbPortConnection,
    ConnectionType,
    PortConnectionKey,
)
from cmdb.framework.port.bulk_create_constants import BulkCreateKey
from cmdb.framework.port.name_syntax_constants import PortDeviceKind, PortPreviewKey
# -------------------------------------------------------------------------------------------------------------------- #

PORTS_URL: str = '/ports'

PORT_TYPE_ID: int = 9890
PLAIN_TYPE_ID: int = 9891
OWNER_OBJECT_ID: int = 9892
PLAIN_OBJECT_ID: int = 9893
MISSING_OBJECT_ID: int = 9894

EXISTING_PORT_ID: int = 9895

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, PLAIN_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [OWNER_OBJECT_ID, PLAIN_OBJECT_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated preview surface is reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, uses_ports: bool) -> dict[str, Any]:
    """A CmdbType document, port-bearing or not."""
    return {
        'public_id': public_id,
        'name': f'preview-type-{public_id}',
        'label': f'Preview Type {public_id}',
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
        'fields': [{'name': NAME_FIELD, 'value': f'device-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }


def _preview_body(
        device_kind: str = PortDeviceKind.STANDARD.value,
        syntax: str = 'Gi0/{n}',
        count: int = 3,
        **overrides: Any) -> dict[str, Any]:
    """A preview request body."""
    body: dict[str, Any] = {'device_kind': device_kind, 'syntax': syntax, 'count': count}
    body.update(overrides)

    return body


@pytest.fixture(name='ports', autouse=True)
def fixture_ports(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the two types and their objects; gives the port collection, cleared around each test."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)

    def _purge() -> None:
        # The connections go FIRST, and by the ports that own them: a panel creation leaves one
        # INTERNAL connection per pair, and they are unreachable once their ports are deleted
        doomed = [
            row[PortKey.PUBLIC_ID.value]
            for row in ports.find({PortKey.OBJECT_ID.value: {'$in': ALL_OBJECT_IDS}})
        ]
        connections.delete_many({PortConnectionKey.ENDPOINTS.value: {'$in': doomed}})

        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        ports.delete_many({PortKey.OBJECT_ID.value: {'$in': ALL_OBJECT_IDS}})

    _purge()

    types.insert_many([_type_doc(PORT_TYPE_ID, True), _type_doc(PLAIN_TYPE_ID, False)])
    objects.insert_many([
        _object_doc(OWNER_OBJECT_ID, PORT_TYPE_ID),
        _object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID),
    ])

    yield ports

    _purge()


def _seed_port(ports, name: str, side: str = PortSide.SINGLE.value) -> None:
    """Stores one existing port on the owner object."""
    ports.insert_one({
        PortKey.PUBLIC_ID.value: EXISTING_PORT_ID,
        PortKey.OBJECT_ID.value: OWNER_OBJECT_ID,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: name,
        PortKey.AUTHOR_ID.value: 1,
    })


def _preview(rest_api, object_id: int = OWNER_OBJECT_ID, **kwargs: Any):
    """POSTs a preview request."""
    return rest_api.post(f'{PORTS_URL}/object/{object_id}/name_preview', json=_preview_body(**kwargs))


def _bulk(rest_api, object_id: int = OWNER_OBJECT_ID, **kwargs: Any):
    """POSTs a bulk-creation request - the same body the preview takes."""
    return rest_api.post(f'{PORTS_URL}/object/{object_id}/bulk', json=_preview_body(**kwargs))


# -------------------------------------------------------------------------------------------------------------------- #
#                                   the creation matches what the preview showed                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheCreationMatchesThePreview:
    """
    The reason the two routes share their builders

    A creation that generated its own names would eventually disagree with the preview, and the
    customer would only find out afterwards - with 48 wrongly named ports already stored.
    """

    def test_the_created_names_are_the_previewed_names(self, rest_api) -> None:
        """The same body through both routes"""
        previewed = _preview(rest_api, count=4, start_index=7).get_json()
        created = _bulk(rest_api, count=4, start_index=7).get_json()

        assert [port[PortKey.NAME.value] for port in created[BulkCreateKey.PORTS.value]] == \
            previewed[PortPreviewKey.FACES.value][0][PortPreviewKey.NAMES.value]

    def test_a_panel_creates_both_previewed_faces(self, rest_api) -> None:
        """Front and rear, each from its own syntax"""
        previewed = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n:02}', rear_syntax='R{n:02}', count=2,
        ).get_json()
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n:02}', rear_syntax='R{n:02}', count=2,
        ).get_json()

        previewed_names = [
            name for face in previewed[PortPreviewKey.FACES.value]
            for name in face[PortPreviewKey.NAMES.value]
        ]

        assert [port[PortKey.NAME.value] for port in created[BulkCreateKey.PORTS.value]] == previewed_names


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 a standard device                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStandardBulkCreate:
    """n plain ports, no connections."""

    def test_it_creates_the_ports(self, rest_api, ports) -> None:
        """The ordinary case"""
        response = _bulk(rest_api, count=3)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[BulkCreateKey.TOTAL_PORTS.value] == 3
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 3

    def test_every_port_is_a_single_sided_one(self, rest_api) -> None:
        """A standard device has no faces - the kind decides that, not the user"""
        created = _bulk(rest_api, count=2).get_json()

        assert {port[PortKey.SIDE.value] for port in created[BulkCreateKey.PORTS.value]} == {
            PortSide.SINGLE.value,
        }

    def test_it_creates_no_connections(self, rest_api) -> None:
        """Its ports connect to nothing internally"""
        created = _bulk(rest_api, count=2).get_json()

        assert created[BulkCreateKey.CONNECTIONS.value] == []
        assert created[BulkCreateKey.TOTAL_CONNECTIONS.value] == 0

    def test_the_shared_field_values_reach_every_port(self, rest_api) -> None:
        """A customer creating 48 uplinks wants them all described the same way"""
        created = _bulk(rest_api, count=3, description='Access port').get_json()

        assert {port[PortKey.DESCRIPTION.value] for port in created[BulkCreateKey.PORTS.value]} == {
            'Access port',
        }

    def test_an_invalid_select_value_is_refused_before_anything_is_written(self, rest_api, ports) -> None:
        """The same guard the single create applies - a PORT_TYPE id in the speed field"""
        response = _bulk(rest_api, count=3, speed=999999)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_the_ports_are_returned_in_creation_order(self, rest_api) -> None:
        """
        Mongo answers an $in in index order, not in the order asked for

        A batch read back scrambled would be unreadable beside a panel's pairing.
        """
        created = _bulk(rest_api, count=4).get_json()

        assert [port[PortKey.NAME.value] for port in created[BulkCreateKey.PORTS.value]] == [
            'Gi0/1', 'Gi0/2', 'Gi0/3', 'Gi0/4',
        ]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  a patch panel                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPanelBulkCreate:
    """Two faces, paired by an INTERNAL connection each."""

    def test_it_creates_both_faces_and_one_connection_per_pair(self, rest_api, ports) -> None:
        """24 pairs would be 48 ports and 24 connections; here 2 pairs"""
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=2,
        ).get_json()

        assert created[BulkCreateKey.TOTAL_PORTS.value] == 4
        assert created[BulkCreateKey.TOTAL_CONNECTIONS.value] == 2
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 4

    def test_the_faces_are_stored_as_front_and_rear(self, rest_api) -> None:
        """Panel-ness is derived from the side, so this is what makes it a panel at all"""
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=2,
        ).get_json()

        sides = [port[PortKey.SIDE.value] for port in created[BulkCreateKey.PORTS.value]]

        assert sides == [PortSide.FRONT.value] * 2 + [PortSide.REAR.value] * 2

    def test_each_connection_joins_a_front_port_to_its_rear_counterpart(self, rest_api) -> None:
        """
        The pairing IS the connection, built from public_ids

        Front i is joined to rear i; the names are never consulted.
        """
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=2,
        ).get_json()

        ports_by_name = {
            port[PortKey.NAME.value]: port[PortKey.PUBLIC_ID.value]
            for port in created[BulkCreateKey.PORTS.value]
        }
        endpoints = [
            connection[PortConnectionKey.ENDPOINTS.value]
            for connection in created[BulkCreateKey.CONNECTIONS.value]
        ]

        assert sorted(endpoints) == sorted([
            sorted([ports_by_name['F1'], ports_by_name['R1']]),
            sorted([ports_by_name['F2'], ports_by_name['R2']]),
        ])

    def test_the_pairing_works_with_faces_named_nothing_alike(self, rest_api) -> None:
        """
        The concept forbids deriving the pairing from the names, and this is why it can

        These two faces share no naming scheme at all and still pair correctly.
        """
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='front-{n:02}', rear_syntax='B{n}', count=2,
        ).get_json()

        assert created[BulkCreateKey.TOTAL_CONNECTIONS.value] == 2

    def test_every_connection_is_internal_and_carries_no_cable_info(self, rest_api) -> None:
        """A panel's pairing is not a cable, and cable fields are refused on an INTERNAL connection"""
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=1,
        ).get_json()

        connection = created[BulkCreateKey.CONNECTIONS.value][0]

        assert connection[PortConnectionKey.CONNECTION_TYPE.value] == ConnectionType.INTERNAL.value
        assert connection.get(PortConnectionKey.CABLE_NAME.value) is None
        assert PortConnectionKey.CABLE_CI_ID.value not in connection

    def test_a_panel_without_a_rear_syntax_is_refused(self, rest_api, ports) -> None:
        """Its two faces are named separately"""
        response = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value, syntax='F{n}', count=2,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_the_request_cannot_express_unequal_faces(self, rest_api) -> None:
        """
        §41's equal-front/rear-count rule needs no validator

        One count drives both faces, so an unequal panel is not a request the API accepts and then
        refuses - it is one that cannot be written down. A second count key is simply ignored.
        """
        created = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=3, rear_count=1,
        ).get_json()

        sides = [port[PortKey.SIDE.value] for port in created[BulkCreateKey.PORTS.value]]

        assert sides.count(PortSide.FRONT.value) == sides.count(PortSide.REAR.value) == 3


# -------------------------------------------------------------------------------------------------------------------- #
#                                          refused before anything is written                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollisionsAreRefused:
    """The preview already knows, so the batch never starts."""

    def test_a_name_that_already_exists_refuses_the_whole_batch(self, rest_api, ports) -> None:
        """
        Not 'create the ones that fit'

        Letting the batch start and fail on the twelfth would leave a half-built device behind for no
        benefit, since the preview knew before the first write.
        """
        _seed_port(ports, 'Gi0/2')

        response = _bulk(rest_api, count=3)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 1

    def test_a_syntax_repeating_itself_refuses_the_whole_batch(self, rest_api, ports) -> None:
        """The unique index would refuse the second port mid-batch"""
        response = _bulk(rest_api, syntax='uplink', count=3)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_a_panel_colliding_on_one_face_only_is_still_refused(self, rest_api, ports) -> None:
        """A panel is not creatable if either of its faces is blocked"""
        _seed_port(ports, 'R1', PortSide.REAR.value)

        response = _bulk(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=2,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_second_batch_may_continue_past_the_first(self, rest_api, ports) -> None:
        """The documented way out of a collision, end to end"""
        assert _bulk(rest_api, count=2).status_code == HTTPStatus.OK

        response = _bulk(rest_api, count=2, start_index=3)

        assert response.status_code == HTTPStatus.OK
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 4


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the refusals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRefusals:
    """The request contract, shared with the preview."""

    def test_no_upper_bound_on_the_batch_size(self, rest_api, ports) -> None:
        """
        Q28: the mockup's 1-96 is a hint, not a rule

        A 120-port chassis is a real device, and a cap would have to be lifted the first time somebody
        owned one.
        """
        assert _bulk(rest_api, count=120).status_code == HTTPStatus.OK
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 120

    @pytest.mark.parametrize('count', [0, -1, 'four'], ids=str)
    def test_an_unusable_count_is_refused(self, rest_api, count: Any) -> None:
        """A batch of nothing is not a batch"""
        assert _bulk(rest_api, count=count).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_token_is_refused(self, rest_api, ports) -> None:
        """The syntax validation is the preview's, shared"""
        assert _bulk(rest_api, syntax='Gi0/{slt}').status_code == HTTPStatus.BAD_REQUEST
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_a_missing_device_kind_is_refused(self, rest_api) -> None:
        """The assistant's first question, deliberately not defaulted"""
        assert _bulk(rest_api, device_kind=None).status_code == HTTPStatus.BAD_REQUEST

    def test_a_type_that_does_not_use_ports_is_refused(self, rest_api) -> None:
        """The same guard the single create applies"""
        response = _bulk(rest_api, object_id=PLAIN_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'does not use ports' in response.get_json()['message']

    def test_a_missing_object_is_a_404(self, rest_api) -> None:
        """Nothing to create against"""
        assert _bulk(rest_api, object_id=MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                   error mapping, and the two failure outcomes                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


class TestErrorMapping:
    """
    A database failure is a 400, anything unexpected a 500 - and a failed batch has TWO outcomes

    A batch that was rolled back cleanly is a 400: the database is as it was and the caller may fix
    their request and retry. A batch whose rollback could not finish is a 500 naming every id, because
    the caller cannot fix that by editing anything and somebody has to go and remove them. Conflating
    the two is exactly what §37 forbids.
    """

    def test_a_denied_owner_is_403(self, rest_api, monkeypatch) -> None:
        """Creating ports changes what the owner object IS, so its ACL governs the batch"""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert _bulk(rest_api).status_code == HTTPStatus.FORBIDDEN

    def test_a_manager_error_reading_the_existing_ports_is_400(self, rest_api, monkeypatch) -> None:
        """The collision pre-check reads them, and a failed read is a bad request, not a crash"""
        monkeypatch.setattr(
            PortsManager, 'get_ports_of_object', _raiser(PortsManagerGetError('boom')),
        )

        assert _bulk(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_error_before_the_batch_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request"""
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(RuntimeError('boom')))

        assert _bulk(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_batch_rolled_back_cleanly_is_400(self, rest_api, monkeypatch, ports) -> None:
        """
        The database is as it was, so the caller may fix their request and retry

        The insert is broken AFTER the collision pre-check has passed, which is the only way to reach a
        mid-batch failure through the route.
        """
        monkeypatch.setattr(PortsManager, 'insert_item', _raiser(RuntimeError('write failed')))

        response = _bulk(rest_api, count=3)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'removed again' in response.get_json()['message']
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_a_batch_whose_rollback_failed_is_500_naming_the_residue(
            self, rest_api, monkeypatch, ports) -> None:
        """
        The honest report §37 exists for

        The caller cannot fix this by editing anything, and the message has to name the ids so somebody
        can remove them by hand.
        """
        real_insert = PortsManager.insert_item
        state: dict[str, int] = {'written': 0}

        def _fail_after_two(self, document):
            if state['written'] >= 2:
                raise RuntimeError('write failed')

            state['written'] += 1

            return real_insert(self, document)

        monkeypatch.setattr(PortsManager, 'insert_item', _fail_after_two)
        monkeypatch.setattr(PortsManager, 'delete_many', _raiser(RuntimeError('cleanup failed')))

        response = _bulk(rest_api, count=3)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert 'left behind' in response.get_json()['message']
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 2
