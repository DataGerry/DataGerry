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
Functional tests for the port name preview route

The assertion that matters most in this file is the simplest one: **the route writes nothing.** It is a
POST because it carries a body, and a POST that created 48 ports when the customer only wanted to look
at the names would be the worst possible failure of an assistant.

Everything else is the request contract - the device kind, the two syntaxes a patch panel needs, the
collisions reported against the ports that already exist, and that a preview WITH collisions is still a
200 because the names are what that syntax produces and the customer needs to see them
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.ports_manager import PortsManager
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.security import AccessDeniedError
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.port.name_syntax_constants import (
    PortCollisionKey,
    PortDeviceKind,
    PortPreviewKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

PORTS_URL: str = '/ports'

PORT_TYPE_ID: int = 9990
PLAIN_TYPE_ID: int = 9991
OWNER_OBJECT_ID: int = 9992
PLAIN_OBJECT_ID: int = 9993
MISSING_OBJECT_ID: int = 9994

EXISTING_PORT_ID: int = 9995

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

    def _purge() -> None:
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the route writes nothing                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
class TestThePreviewWritesNothing:
    """The single most important property of this route."""

    def test_no_ports_are_created(self, rest_api, ports) -> None:
        """
        A POST that created the ports it was asked to preview would be the worst failure available

        It is a POST because it carries a body - a syntax, two counts, a prefix and a slot would be
        unreadable in a query string - not because it changes anything.
        """
        assert _preview(rest_api, count=48).status_code == HTTPStatus.OK
        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_a_panel_preview_creates_neither_ports_nor_connections(self, rest_api, ports) -> None:
        """The panel path builds a pairing too, and that must stay equally imaginary"""
        _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=24,
        )

        assert ports.count_documents({PortKey.OBJECT_ID.value: OWNER_OBJECT_ID}) == 0

    def test_previewing_twice_gives_the_same_answer(self, rest_api) -> None:
        """Nothing is consumed - no counter moves, no id is reserved"""
        first = _preview(rest_api).get_json()
        second = _preview(rest_api).get_json()

        assert first == second


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 a standard device                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStandardPreview:
    """n plain ports."""

    def test_the_names_are_generated(self, rest_api) -> None:
        """The ordinary case"""
        preview = _preview(rest_api).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.NAMES.value] == [
            'Gi0/1', 'Gi0/2', 'Gi0/3',
        ]
        assert preview[PortPreviewKey.TOTAL.value] == 3

    def test_the_prefix_the_slot_and_the_padding_are_applied(self, rest_api) -> None:
        """Every token the concept names, in one request"""
        preview = _preview(
            rest_api, syntax='{prefix}-{slot}/{n:02}', count=2, prefix='SW1', slot='3',
        ).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.NAMES.value] == [
            'SW1-3/01', 'SW1-3/02',
        ]

    def test_the_start_index_is_honoured(self, rest_api) -> None:
        """So a second batch continues where the first stopped"""
        preview = _preview(rest_api, count=2, start_index=25).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.NAMES.value] == [
            'Gi0/25', 'Gi0/26',
        ]

    def test_a_standard_preview_carries_no_pairing(self, rest_api) -> None:
        """Only a panel has pairs"""
        assert PortPreviewKey.PAIRS.value not in _preview(rest_api).get_json()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  a patch panel                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPanelPreview:
    """Two faces and the pairing."""

    def test_both_faces_are_previewed_with_their_own_syntax(self, rest_api) -> None:
        """The concept's two syntaxes"""
        preview = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n:02}', rear_syntax='R{n:02}', count=2,
        ).get_json()

        faces = preview[PortPreviewKey.FACES.value]

        assert [face[PortPreviewKey.SIDE.value] for face in faces] == [
            PortSide.FRONT.value, PortSide.REAR.value,
        ]
        assert faces[0][PortPreviewKey.NAMES.value] == ['F01', 'F02']
        assert faces[1][PortPreviewKey.NAMES.value] == ['R01', 'R02']
        assert preview[PortPreviewKey.TOTAL.value] == 4

    def test_the_pairing_is_shown(self, rest_api) -> None:
        """So the customer can check it before anything is written"""
        preview = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{n}', count=2,
        ).get_json()

        assert preview[PortPreviewKey.PAIRS.value] == [
            {PortPreviewKey.FRONT.value: 'F1', PortPreviewKey.REAR.value: 'R1'},
            {PortPreviewKey.FRONT.value: 'F2', PortPreviewKey.REAR.value: 'R2'},
        ]

    def test_a_panel_without_a_rear_syntax_is_refused(self, rest_api) -> None:
        """Its two faces are named separately, so one syntax does not describe it"""
        response = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value, syntax='F{n}', count=2,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'rear syntax' in response.get_json()['message']

    def test_an_unusable_rear_syntax_is_refused(self, rest_api) -> None:
        """Both faces are validated, not just the first"""
        response = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='F{n}', rear_syntax='R{slt}', count=2,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_identical_syntaxes_produce_no_collision(self, rest_api, ports) -> None:
        """
        Front 1 and rear 1 are two different ports

        The unique index keys on the side, so the same name on the two faces is not a duplicate.
        """
        preview = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='{n}', rear_syntax='{n}', count=2,
        ).get_json()

        for face in preview[PortPreviewKey.FACES.value]:
            assert face[PortPreviewKey.COLLISIONS.value][PortCollisionKey.EXISTING.value] == []

    def test_an_existing_front_port_does_not_collide_with_the_rear_face(self, rest_api, ports) -> None:
        """The two faces are checked separately, which is what makes a panel buildable at all"""
        _seed_port(ports, '1', PortSide.FRONT.value)

        preview = _preview(
            rest_api, device_kind=PortDeviceKind.PATCH_PANEL.value,
            syntax='{n}', rear_syntax='{n}', count=1,
        ).get_json()

        faces = preview[PortPreviewKey.FACES.value]

        assert faces[0][PortPreviewKey.COLLISIONS.value][PortCollisionKey.EXISTING.value] == ['1']
        assert faces[1][PortPreviewKey.COLLISIONS.value][PortCollisionKey.EXISTING.value] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   collisions                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollisions:
    """Found before anything is created, and reported rather than refused."""

    def test_an_existing_name_is_reported(self, rest_api, ports) -> None:
        """The customer learns which names clash BEFORE half a batch is written"""
        _seed_port(ports, 'Gi0/2')

        preview = _preview(rest_api).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.COLLISIONS.value][
            PortCollisionKey.EXISTING.value] == ['Gi0/2']

    def test_a_syntax_repeating_itself_is_reported(self, rest_api) -> None:
        """It would be refused mid-batch by the unique index, leaving a half-created device"""
        preview = _preview(rest_api, syntax='uplink', count=3).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.COLLISIONS.value][
            PortCollisionKey.DUPLICATES.value] == ['uplink']

    def test_a_preview_with_collisions_is_still_a_200(self, rest_api, ports) -> None:
        """
        The names ARE what that syntax produces, and the customer needs to see them to fix it

        Refusing here would show them nothing. Only the creation refuses.
        """
        _seed_port(ports, 'Gi0/1')

        assert _preview(rest_api).status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the refusals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestRefusals:
    """What the route will not preview at all."""

    @pytest.mark.parametrize('device_kind', [None, '', 'STANDARD_DEVICE', 5], ids=str)
    def test_a_missing_or_unknown_device_kind_is_refused(self, rest_api, device_kind: Any) -> None:
        """
        The assistant's first question, deliberately not defaulted

        Guessing STANDARD for a typo would preview the wrong device - a panel's two faces would
        collapse into one.
        """
        response = _preview(rest_api, device_kind=device_kind)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_token_is_refused_by_name(self, rest_api) -> None:
        """The customer is told which token, and which ones exist"""
        response = _preview(rest_api, syntax='Gi0/{slt}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert '{slt}' in response.get_json()['message']

    @pytest.mark.parametrize('count', [0, -1, 'four'], ids=str)
    def test_an_unusable_count_is_refused(self, rest_api, count: Any) -> None:
        """A batch of nothing is not a batch"""
        assert _preview(rest_api, count=count).status_code == HTTPStatus.BAD_REQUEST

    def test_an_empty_syntax_is_refused(self, rest_api) -> None:
        """It is what the names are generated from"""
        assert _preview(rest_api, syntax='').status_code == HTTPStatus.BAD_REQUEST

    def test_a_type_that_does_not_use_ports_is_refused(self, rest_api) -> None:
        """
        Previewing ports for a device that cannot have them is not a useful answer

        The same guard the create route applies, for the same reason: the ports would be invisible.
        """
        response = _preview(rest_api, object_id=PLAIN_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'does not use ports' in response.get_json()['message']

    def test_a_missing_object_is_a_404(self, rest_api) -> None:
        """Nothing to preview against"""
        assert _preview(rest_api, object_id=MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   error mapping                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(error: Exception):
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


class TestErrorMapping:
    """
    A database failure is a 400, anything unexpected a 500 - never the other way round

    The preview reads the object's existing ports to find collisions, so it has a manager error to map
    like every other route; a failure there must not be reported as a preview the customer can trust.
    """

    def test_a_denied_owner_is_403(self, rest_api, monkeypatch) -> None:
        """
        Previewing names against an object reports what that object already has

        That is the same information the ports list gives, so it is governed by the same ACL.
        """
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert _preview(rest_api).status_code == HTTPStatus.FORBIDDEN

    def test_a_manager_error_reading_the_existing_ports_is_400(self, rest_api, monkeypatch) -> None:
        """A failed read is reported as a bad request, not as a crash"""
        monkeypatch.setattr(
            PortsManager, 'get_ports_of_object', _raiser(PortsManagerGetError('boom')),
        )

        assert _preview(rest_api).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request"""
        monkeypatch.setattr(PortsManager, 'get_ports_of_object', _raiser(RuntimeError('boom')))

        assert _preview(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_port_row_with_a_drifted_side_is_ignored(self, rest_api, ports) -> None:
        """
        The uncovered branch of the per-face grouping

        A row whose side is not a PortSide value belongs to no face, so it can not make a name look
        taken - and it must not raise while reading the ones that do.
        """
        ports.insert_one({
            PortKey.PUBLIC_ID.value: EXISTING_PORT_ID,
            PortKey.OBJECT_ID.value: OWNER_OBJECT_ID,
            PortKey.SIDE.value: 'sideways',
            PortKey.NAME.value: 'Gi0/1',
            PortKey.AUTHOR_ID.value: 1,
        })

        preview = _preview(rest_api).get_json()

        assert preview[PortPreviewKey.FACES.value][0][PortPreviewKey.COLLISIONS.value][
            PortCollisionKey.EXISTING.value] == []
