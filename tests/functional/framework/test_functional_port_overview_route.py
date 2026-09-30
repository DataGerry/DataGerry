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
Functional tests for `GET /ports/object/<object_id>/overview`

The wiring view of an object's ports, as opposed to the stored view `GET /ports/object/<object_id>`
answers. What is asserted here is what the panel cannot get anywhere else: the row shape chosen by
`device_kind`, the front/rear pairing read off the INTERNAL connection, the option labels resolved
server-side, and the CI at the end of a cable - one hop, and withheld when its ACL says so.

Documents are seeded directly rather than through the write routes: the overview is a read, and the
states it has to render (a half-paired panel, a cable into another object) are quicker to state than
to build through the assistant.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.framework.port.name_syntax_constants import PortDeviceKind
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort
from cmdb.models.port_model.port_constants import PortKey, PortSide
from cmdb.models.port_connection_model import CmdbPortConnection
from cmdb.models.port_connection_model.port_connection_constants import ConnectionType, PortConnectionKey
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.database import MongoDatabaseManager

from cmdb.interface.rest_api.routes.port_routes.port_overview_constants import (
    ConnectedObjectKey,
    ConnectedPortKey,
    PortOverviewEntryKey,
    PortOverviewKey,
    PortOverviewOptionKey,
    PortOverviewRowKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/ports'

PORT_TYPE_ID: int = 9860
DEVICE_OBJECT_ID: int = 9870
PANEL_OBJECT_ID: int = 9871
PEER_OBJECT_ID: int = 9872
DENIED_TYPE_ID: int = 9861
DENIED_OBJECT_ID: int = 9873
NO_PORTS_OBJECT_ID: int = 9874
MISSING_OBJECT_ID: int = 9899

DEVICE_PORT_ID: int = 9880
PANEL_FRONT_ID: int = 9881
PANEL_REAR_ID: int = 9882
PANEL_LONE_FRONT_ID: int = 9883
PEER_PORT_ID: int = 9884
DENIED_PORT_ID: int = 9885

CABLE_CONNECTION_ID: int = 9890
INTERNAL_CONNECTION_ID: int = 9891
DENIED_CABLE_CONNECTION_ID: int = 9892

STATUS_OPTION_ID: int = 9850
STATUS_LABEL: str = 'Up'

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, DENIED_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [
    DEVICE_OBJECT_ID, PANEL_OBJECT_ID, PEER_OBJECT_ID, DENIED_OBJECT_ID, NO_PORTS_OBJECT_ID,
]
ALL_PORT_IDS: list[int] = [
    DEVICE_PORT_ID, PANEL_FRONT_ID, PANEL_REAR_ID, PANEL_LONE_FRONT_ID, PEER_PORT_ID, DENIED_PORT_ID,
]
ALL_CONNECTION_IDS: list[int] = [CABLE_CONNECTION_ID, INTERNAL_CONNECTION_ID, DENIED_CABLE_CONNECTION_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM, which the whole /ports surface is gated behind."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, acl: dict[str, Any] | None = None) -> dict[str, Any]:
    """A port-bearing CmdbType, optionally carrying an ACL that denies the admin group."""
    return {
        'public_id': public_id,
        'name': f'overview-type-{public_id}',
        'label': f'Overview Type {public_id}',
        'author_id': 1,
        'active': True,
        'version': '1.0.0',
        'uses_ports': True,
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
        'acl': acl or {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, type_id: int = PORT_TYPE_ID) -> dict[str, Any]:
    """A CmdbObject whose summary line is its name field."""
    return {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }


def _port_doc(public_id: int, object_id: int, side: PortSide, name: str, **overrides: Any) -> dict[str, Any]:
    """A stored CmdbPort."""
    document: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side.value,
        PortKey.NAME.value: name,
        PortKey.PORT_NUMBER.value: 1,
        PortKey.STATUS.value: None,
        PortKey.PORT_TYPE.value: None,
        PortKey.SPEED.value: None,
        PortKey.DESCRIPTION.value: None,
        PortKey.AUTHOR_ID.value: 1,
    }
    document.update(overrides)

    return document


def _connection_doc(public_id: int, endpoints: list[int], connection_type: ConnectionType) -> dict[str, Any]:
    """A stored CmdbPortConnection; a cable carries its name inline."""
    document: dict[str, Any] = {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: connection_type.value,
        PortConnectionKey.AUTHOR_ID.value: 1,
    }

    if connection_type is ConnectionType.CABLE:
        document[PortConnectionKey.CABLE_NAME.value] = 'Patch 3m'

    return document


def _denied_acl() -> dict[str, Any]:
    """An ACL that grants READ to a group the requesting admin is not in."""
    return {'activated': True, 'groups': {'includes': {'99': ['READ']}}}


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds a standard device, a patch panel, the CIs their cables reach and one option."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        options.delete_many({'public_id': STATUS_OPTION_ID})
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': ALL_PORT_IDS}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': ALL_CONNECTION_IDS}})

    _purge()

    types.insert_many([_type_doc(PORT_TYPE_ID), _type_doc(DENIED_TYPE_ID, _denied_acl())])
    objects.insert_many([
        _object_doc(DEVICE_OBJECT_ID),
        _object_doc(PANEL_OBJECT_ID),
        _object_doc(PEER_OBJECT_ID),
        _object_doc(DENIED_OBJECT_ID, DENIED_TYPE_ID),
        _object_doc(NO_PORTS_OBJECT_ID),
    ])
    options.insert_one({
        'public_id': STATUS_OPTION_ID, 'value': STATUS_LABEL,
        'option_type': OptionType.PORT_STATUS.value, 'predefined': True,
    })
    ports.insert_many([
        _port_doc(DEVICE_PORT_ID, DEVICE_OBJECT_ID, PortSide.SINGLE, 'Gi0/1',
                  **{PortKey.STATUS.value: STATUS_OPTION_ID}),
        _port_doc(PANEL_FRONT_ID, PANEL_OBJECT_ID, PortSide.FRONT, 'F01'),
        _port_doc(PANEL_REAR_ID, PANEL_OBJECT_ID, PortSide.REAR, 'R01'),
        _port_doc(PANEL_LONE_FRONT_ID, PANEL_OBJECT_ID, PortSide.FRONT, 'F02',
                  **{PortKey.PORT_NUMBER.value: 2}),
        _port_doc(PEER_PORT_ID, PEER_OBJECT_ID, PortSide.SINGLE, 'Gi1/1'),
        _port_doc(DENIED_PORT_ID, DENIED_OBJECT_ID, PortSide.SINGLE, 'Gi2/1'),
    ])
    connections.insert_many([
        _connection_doc(CABLE_CONNECTION_ID, [DEVICE_PORT_ID, PEER_PORT_ID], ConnectionType.CABLE),
        _connection_doc(INTERNAL_CONNECTION_ID, [PANEL_FRONT_ID, PANEL_REAR_ID], ConnectionType.INTERNAL),
        _connection_doc(DENIED_CABLE_CONNECTION_ID, [PANEL_REAR_ID, DENIED_PORT_ID], ConnectionType.CABLE),
    ])

    yield

    _purge()


def _overview(rest_api, object_id: int):
    """Reads the overview of one object."""
    return rest_api.get(f'{ROUTE_URL}/object/{object_id}/overview')


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  A STANDARD DEVICE                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStandardDeviceOverview:
    """An ordinary device: one row per port."""

    def test_reports_the_device_kind(self, rest_api) -> None:
        """The property the client branches on before it draws a column"""
        response = _overview(rest_api, DEVICE_OBJECT_ID)

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[PortOverviewKey.DEVICE_KIND.value] == PortDeviceKind.STANDARD.value

    def test_answers_one_row_per_port(self, rest_api) -> None:
        """Under `port`, which is the standard row shape"""
        body = _overview(rest_api, DEVICE_OBJECT_ID).get_json()

        assert body[PortOverviewKey.TOTAL.value] == 1
        assert body[PortOverviewKey.ROWS.value][0][PortOverviewRowKey.PORT.value][
            PortOverviewEntryKey.NAME.value
        ] == 'Gi0/1'

    def test_resolves_the_option_label(self, rest_api) -> None:
        """So the panel needs no extendable-option catalog of its own"""
        row = _overview(rest_api, DEVICE_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value][0]
        status = row[PortOverviewRowKey.PORT.value][PortKey.STATUS.value]

        assert status[PortOverviewOptionKey.ID.value] == STATUS_OPTION_ID
        assert status[PortOverviewOptionKey.LABEL.value] == STATUS_LABEL

    def test_names_the_ci_at_the_end_of_the_cable(self, rest_api) -> None:
        """The one thing a client cannot get without a read per port"""
        row = _overview(rest_api, DEVICE_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value][0]
        connected = row[PortOverviewRowKey.PORT.value][PortOverviewEntryKey.CONNECTED_OBJECT.value]

        assert connected[ConnectedObjectKey.OBJECT_ID.value] == PEER_OBJECT_ID
        assert str(PEER_OBJECT_ID) in connected[ConnectedObjectKey.LABEL.value]
        assert connected[ConnectedObjectKey.RESTRICTED.value] is False

    def test_names_the_port_at_the_end_of_the_cable(self, rest_api) -> None:
        """A connection is named port first, device second - the dialog needs no follow-up read"""
        row = _overview(rest_api, DEVICE_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value][0]
        far_port = row[PortOverviewRowKey.PORT.value][PortOverviewEntryKey.CONNECTED_PORT.value]

        assert far_port[ConnectedPortKey.PORT_ID.value] == PEER_PORT_ID
        assert far_port[ConnectedPortKey.NAME.value] == 'Gi1/1'
        assert far_port[ConnectedPortKey.SIDE.value] == PortSide.SINGLE.value

    def test_carries_the_cable_and_its_connection(self, rest_api) -> None:
        """The cable is the column; its connection id is what a disconnect acts on"""
        entry = _overview(rest_api, DEVICE_OBJECT_ID).get_json()[
            PortOverviewKey.ROWS.value][0][PortOverviewRowKey.PORT.value]

        assert entry[PortOverviewEntryKey.CABLE_CONNECTION_ID.value] == CABLE_CONNECTION_ID
        assert entry[PortOverviewEntryKey.CABLE.value]['name'] == 'Patch 3m'
        assert entry[PortOverviewEntryKey.CONNECTED.value] is True

    def test_an_object_without_ports_names_no_kind(self, rest_api) -> None:
        """It is still free to become either kind, so naming one would be a guess"""
        response = _overview(rest_api, NO_PORTS_OBJECT_ID)
        body = response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert body[PortOverviewKey.DEVICE_KIND.value] is None
        assert body[PortOverviewKey.ROWS.value] == []
        assert body[PortOverviewKey.TOTAL.value] == 0


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   A PATCH PANEL                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPatchPanelOverview:
    """A panel: one row per front/rear pairing."""

    def test_reports_the_device_kind(self, rest_api) -> None:
        """Read from the ports' side, which is the one stored signal for it"""
        body = _overview(rest_api, PANEL_OBJECT_ID).get_json()

        assert body[PortOverviewKey.DEVICE_KIND.value] == PortDeviceKind.PATCH_PANEL.value

    def test_pairs_a_front_with_its_rear(self, rest_api) -> None:
        """The INTERNAL connection is the pairing - the names are never consulted"""
        rows = _overview(rest_api, PANEL_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value]
        paired = next(row for row in rows if row[PortOverviewRowKey.PAIRED.value])

        assert paired[PortOverviewRowKey.FRONT.value][PortOverviewEntryKey.NAME.value] == 'F01'
        assert paired[PortOverviewRowKey.REAR.value][PortOverviewEntryKey.NAME.value] == 'R01'

    def test_counts_a_pairing_as_one_row(self, rest_api) -> None:
        """Three ports, two rows: the paired pair and the lone front"""
        body = _overview(rest_api, PANEL_OBJECT_ID).get_json()

        assert body[PortOverviewKey.TOTAL.value] == 2

    def test_an_unpaired_front_is_listed_with_an_empty_rear(self, rest_api) -> None:
        """A half-built panel has to be visible to be fixable"""
        rows = _overview(rest_api, PANEL_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value]
        lone = next(row for row in rows if not row[PortOverviewRowKey.PAIRED.value])

        assert lone[PortOverviewRowKey.FRONT.value][PortOverviewEntryKey.NAME.value] == 'F02'
        assert lone[PortOverviewRowKey.REAR.value] is None

    def test_the_rear_carries_its_own_cable_and_ci(self, rest_api) -> None:
        """Which is what the panel's 'Connected' column reads"""
        rows = _overview(rest_api, PANEL_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value]
        rear = next(row for row in rows if row[PortOverviewRowKey.PAIRED.value])[PortOverviewRowKey.REAR.value]

        assert rear[PortOverviewEntryKey.CABLE_CONNECTION_ID.value] == DENIED_CABLE_CONNECTION_ID
        assert rear[PortOverviewEntryKey.CONNECTED_OBJECT.value][
            ConnectedObjectKey.OBJECT_ID.value
        ] == DENIED_OBJECT_ID
        far_port = rear[PortOverviewEntryKey.CONNECTED_PORT.value]

        assert far_port[ConnectedPortKey.PORT_ID.value] == DENIED_PORT_ID
        # `GET /ports/<id>` answers 403 for that port, so its name may not leak through here either
        assert far_port[ConnectedPortKey.NAME.value] is None

    def test_a_ci_the_user_may_not_read_is_reported_without_its_label(self, rest_api) -> None:
        """The id is implied by the connection the user may read; the summary line is not"""
        rows = _overview(rest_api, PANEL_OBJECT_ID).get_json()[PortOverviewKey.ROWS.value]
        rear = next(row for row in rows if row[PortOverviewRowKey.PAIRED.value])[PortOverviewRowKey.REAR.value]
        connected = rear[PortOverviewEntryKey.CONNECTED_OBJECT.value]

        assert connected[ConnectedObjectKey.RESTRICTED.value] is True
        assert connected[ConnectedObjectKey.LABEL.value] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      ACCESS                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestOverviewAccess:
    """The owner object's ACL and the existence check, like every other /ports read."""

    def test_a_missing_object_is_404(self, rest_api) -> None:
        """The overview is asked for an object, so a missing one is not an empty list"""
        assert _overview(rest_api, MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND

    def test_an_owner_the_user_may_not_read_is_403(self, rest_api) -> None:
        """A port inherits no ACL from its owner, so the owner is checked explicitly"""
        assert _overview(rest_api, DENIED_OBJECT_ID).status_code == HTTPStatus.FORBIDDEN
