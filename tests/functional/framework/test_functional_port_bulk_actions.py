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
Functional tests for the port BULK ACTIONS - edit, delete, the delete pre-check, and resolve (§30-35)

Three actions over a selection the user ticked in one object's ports table, and the contract they
share: **validated as a whole, applied only if every element passes**. Most of what is asserted here
is therefore what did NOT happen - a refused bulk edit leaves every port as it was, a refused bulk
delete leaves the whole selection standing.

The other half is the cascade honesty. Deleting a port takes its connections and its interface links
with it, neither of which the caller named, so the pre-check lists them beforehand and the action
reports them afterwards - and the two come from the same read, so what the dialog showed is what
happened.

The seeded device is a patch panel joined to a server, which is the case §34 is about: a front port
carries an external connection AND an internal pairing, and resolving one must never take the other.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.port_connections_manager import (
    PortConnectionsManagerDeleteError,
    PortConnectionsManagerGetError,
)
from cmdb.errors.manager.ports_manager import (
    PortsManagerDeleteError,
    PortsManagerGetError,
    PortsManagerUpdateError,
)
from cmdb.errors.security import AccessDeniedError
from cmdb.manager import ObjectsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey, OptionType
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_connection_model import CmdbPortConnection, ConnectionType, PortConnectionKey
from cmdb.models.port_interface_link_model import (
    CmdbPortInterfaceLink,
    InterfaceRelationType,
    PortInterfaceLinkKey,
)
from cmdb.models.special_type_model.ipam_constants import IpamSection
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.port.bulk_action_constants import BulkActionKey, BulkDeletePreviewKey
# -------------------------------------------------------------------------------------------------------------------- #

PORTS_URL: str = '/ports'
CONNECTIONS_URL: str = '/port_connections'

PORT_TYPE_ID: int = 9700
PANEL_OBJECT_ID: int = 9701
SERVER_OBJECT_ID: int = 9702
MISSING_OBJECT_ID: int = 9799

FRONT_PORT_ID: int = 9710
REAR_PORT_ID: int = 9711
SPARE_PORT_ID: int = 9712
SERVER_PORT_ID: int = 9713
MISSING_PORT_ID: int = 9798

INTERNAL_CONNECTION_ID: int = 9720
CABLE_CONNECTION_ID: int = 9721
MISSING_CONNECTION_ID: int = 9797

LINK_ID: int = 9730
ROW_ID: int = 1

SPEED_OPTION_ID: int = 9740
STATUS_OPTION_ID: int = 9741
FOREIGN_OPTION_ID: int = 9742

NAME_FIELD: str = 'dg-name'

ALL_OBJECT_IDS: list[int] = [PANEL_OBJECT_ID, SERVER_OBJECT_ID]
ALL_PORT_IDS: list[int] = [FRONT_PORT_ID, REAR_PORT_ID, SPARE_PORT_ID, SERVER_PORT_ID]
ALL_CONNECTION_IDS: list[int] = [INTERNAL_CONNECTION_ID, CABLE_CONNECTION_ID]
ALL_OPTION_IDS: list[int] = [SPEED_OPTION_ID, STATUS_OPTION_ID, FOREIGN_OPTION_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated port surfaces are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc() -> dict[str, Any]:
    """The port-bearing CmdbType both devices use."""
    return {
        'public_id': PORT_TYPE_ID,
        'name': 'bulk-action-type',
        'label': 'Bulk Action Type',
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
        'acl': {'activated': False, 'groups': {'includes': None}},
    }


def _object_doc(public_id: int, with_interface_row: bool = False) -> dict[str, Any]:
    """A device of that type, optionally carrying the IPAM interface row a link addresses."""
    document: dict[str, Any] = {
        'public_id': public_id,
        'type_id': PORT_TYPE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': f'device-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }

    if with_interface_row:
        document['multi_data_sections'] = [{
            'section_id': IpamSection.INTERFACE.value,
            'values': [{'multi_data_id': ROW_ID,
                        'data': [{'name': 'dg-ipam-interface-ip', 'value': '10.0.0.5'}]}],
        }]

    return document


def _port_doc(public_id: int, object_id: int, name: str, side: str = PortSide.SINGLE.value,
              **overrides: Any) -> dict[str, Any]:
    """A stored port."""
    port: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: side,
        PortKey.NAME.value: name,
        PortKey.DESCRIPTION.value: 'before',
        PortKey.AUTHOR_ID.value: 1,
    }
    port.update(overrides)

    return port


def _connection_doc(public_id: int, endpoints: list[int], connection_type: str) -> dict[str, Any]:
    """A stored connection."""
    return {
        PortConnectionKey.PUBLIC_ID.value: public_id,
        PortConnectionKey.ENDPOINTS.value: sorted(endpoints),
        PortConnectionKey.CONNECTION_TYPE.value: connection_type,
        PortConnectionKey.AUTHOR_ID.value: 1,
    }


def _option_doc(public_id: int, option_type: str, value: str) -> dict[str, Any]:
    """A stored CmdbExtendableOption a select field may name."""
    return {
        ExtendableOptionKey.PUBLIC_ID: public_id,
        ExtendableOptionKey.OPTION_TYPE: option_type,
        ExtendableOptionKey.VALUE: value,
        ExtendableOptionKey.PREDEFINED: False,
    }


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds a patch panel joined to a server: front/rear/spare ports, both connection kinds, one link

    The front port deliberately carries BOTH an external cable and the internal pairing - that is the
    §34 case, and what makes "resolving one never deletes another" assertable.
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    connections = database_manager.get_collection(CmdbPortConnection.COLLECTION, database_name)
    links = database_manager.get_collection(CmdbPortInterfaceLink.COLLECTION, database_name)
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': PORT_TYPE_ID})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': ALL_PORT_IDS}})
        connections.delete_many({PortConnectionKey.PUBLIC_ID.value: {'$in': ALL_CONNECTION_IDS}})
        links.delete_many({PortInterfaceLinkKey.PORT_ID.value: {'$in': ALL_PORT_IDS}})
        options.delete_many({ExtendableOptionKey.PUBLIC_ID: {'$in': ALL_OPTION_IDS}})

    _purge()

    types.insert_one(_type_doc())
    objects.insert_many([
        _object_doc(PANEL_OBJECT_ID, with_interface_row=True),
        _object_doc(SERVER_OBJECT_ID),
    ])
    ports.insert_many([
        _port_doc(FRONT_PORT_ID, PANEL_OBJECT_ID, '1', PortSide.FRONT.value),
        _port_doc(REAR_PORT_ID, PANEL_OBJECT_ID, '1', PortSide.REAR.value),
        _port_doc(SPARE_PORT_ID, PANEL_OBJECT_ID, '2', PortSide.FRONT.value),
        _port_doc(SERVER_PORT_ID, SERVER_OBJECT_ID, 'eth0'),
    ])
    connections.insert_many([
        _connection_doc(INTERNAL_CONNECTION_ID, [FRONT_PORT_ID, REAR_PORT_ID],
                        ConnectionType.INTERNAL.value),
        _connection_doc(CABLE_CONNECTION_ID, [FRONT_PORT_ID, SERVER_PORT_ID],
                        ConnectionType.CABLE.value),
    ])
    links.insert_one({
        PortInterfaceLinkKey.PUBLIC_ID.value: LINK_ID,
        PortInterfaceLinkKey.PORT_ID.value: FRONT_PORT_ID,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: PANEL_OBJECT_ID,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: IpamSection.INTERFACE.value,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: ROW_ID,
        PortInterfaceLinkKey.RELATION_TYPE.value: InterfaceRelationType.PHYSICAL.value,
        PortInterfaceLinkKey.AUTHOR_ID.value: 1,
    })
    options.insert_many([
        _option_doc(SPEED_OPTION_ID, OptionType.PORT_SPEED.value, '10G'),
        _option_doc(STATUS_OPTION_ID, OptionType.PORT_STATUS.value, 'Up'),
        _option_doc(FOREIGN_OPTION_ID, OptionType.CABLE_TYPE.value, 'CAT6A'),
    ])

    yield {'ports': ports, 'connections': connections, 'links': links}

    _purge()


def _bulk_url(object_id: int = PANEL_OBJECT_ID) -> str:
    """The bulk action URL of one object's ports."""
    return f'{PORTS_URL}/object/{object_id}/bulk'


def _stored_port(seeded, public_id: int) -> dict[str, Any] | None:
    """Reads one port back out of the collection."""
    return seeded['ports'].find_one({PortKey.PUBLIC_ID.value: public_id})


def _stored_connection_ids(seeded) -> set[int]:
    """The connections still stored, of the seeded pair."""
    return {
        connection[PortConnectionKey.PUBLIC_ID.value]
        for connection in seeded['connections'].find(
            {PortConnectionKey.PUBLIC_ID.value: {'$in': ALL_CONNECTION_IDS}},
        )
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     BULK EDIT                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkEdit:
    """PATCH /ports/object/<id>/bulk"""

    def test_the_shared_values_reach_every_selected_port(self, rest_api, seeded) -> None:
        """One call, one `$set`, the whole selection"""
        response = rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID, REAR_PORT_ID],
            'values': {'speed': SPEED_OPTION_ID, 'description': 'after'},
        })

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[BulkActionKey.UPDATED.value] == 2

        for port_id in (FRONT_PORT_ID, REAR_PORT_ID):
            stored = _stored_port(seeded, port_id)
            assert stored[PortKey.SPEED.value] == SPEED_OPTION_ID
            assert stored[PortKey.DESCRIPTION.value] == 'after'

    def test_an_unselected_port_is_untouched(self, rest_api, seeded) -> None:
        """The selection is the selection"""
        rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID], 'values': {'description': 'after'},
        })

        assert _stored_port(seeded, SPARE_PORT_ID)[PortKey.DESCRIPTION.value] == 'before'

    def test_a_field_left_out_keeps_its_value(self, rest_api, seeded) -> None:
        """"Set the speed of these two" must not clear their descriptions"""
        rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID], 'values': {'speed': SPEED_OPTION_ID},
        })

        assert _stored_port(seeded, FRONT_PORT_ID)[PortKey.DESCRIPTION.value] == 'before'

    def test_the_edit_time_is_stamped(self, rest_api, seeded) -> None:
        """A bulk edit is an edit - the ports carry when it happened"""
        rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID], 'values': {'description': 'after'},
        })

        assert _stored_port(seeded, FRONT_PORT_ID)[PortKey.LAST_EDIT_TIME.value] is not None

    @pytest.mark.parametrize('field, value', [
        ('name', 'renamed'), ('port_number', 4), ('object_id', SERVER_OBJECT_ID), ('side', 'rear'),
    ])
    def test_an_identifying_field_is_refused(self, rest_api, seeded, field: str, value: Any) -> None:
        """
        Reported, not ignored

        A name identifies a port within its face, so one value across a selection collides by
        construction - and nothing is written, which the untouched port proves.
        """
        response = rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID], 'values': {field: value},
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert field in response.get_json()['message']
        assert _stored_port(seeded, FRONT_PORT_ID)[PortKey.NAME.value] == '1'

    def test_another_objects_port_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """
        The all-or-nothing contract: the panel's own port is NOT edited either

        This is the assertion the contract lives or dies by - a partially applied bulk action is a
        state the user then has to reverse-engineer.
        """
        response = rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID, SERVER_PORT_ID], 'values': {'description': 'after'},
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert str(SERVER_PORT_ID) in response.get_json()['message']
        assert _stored_port(seeded, FRONT_PORT_ID)[PortKey.DESCRIPTION.value] == 'before'

    def test_a_missing_port_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """A stale table is refused, not partially obeyed"""
        response = rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID, MISSING_PORT_ID], 'values': {'description': 'after'},
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_port(seeded, FRONT_PORT_ID)[PortKey.DESCRIPTION.value] == 'before'

    def test_a_select_value_from_another_list_is_refused(self, rest_api, seeded) -> None:
        """The same cross-collection rule the single update runs: a speed must be a PORT_SPEED option"""
        response = rest_api.patch(_bulk_url(), json={
            'port_ids': [FRONT_PORT_ID], 'values': {'speed': FOREIGN_OPTION_ID},
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_port(seeded, FRONT_PORT_ID).get(PortKey.SPEED.value) is None

    @pytest.mark.parametrize('body', [
        {'values': {'description': 'x'}},
        {'port_ids': [], 'values': {'description': 'x'}},
        {'port_ids': 'all', 'values': {'description': 'x'}},
        {'port_ids': [FRONT_PORT_ID]},
        {'port_ids': [FRONT_PORT_ID], 'values': {}},
    ], ids=['no ids', 'empty ids', 'not a list', 'no values', 'empty values'])
    def test_an_unusable_body_is_refused(self, rest_api, body: dict[str, Any]) -> None:
        """A bulk edit that selects nothing, or sets nothing, is a client bug"""
        assert rest_api.patch(_bulk_url(), json=body).status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_object_is_a_404(self, rest_api) -> None:
        """The scope is resolved before the selection"""
        response = rest_api.patch(_bulk_url(MISSING_OBJECT_ID), json={
            'port_ids': [FRONT_PORT_ID], 'values': {'description': 'after'},
        })

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                               THE DELETE PRE-CHECK                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkDeletePreview:
    """POST /ports/object/<id>/bulk/delete_preview - §41's 'inform the user of the consequences'."""

    def test_it_lists_what_each_port_would_lose(self, rest_api) -> None:
        """Both of the front port's connections and its interface link"""
        response = rest_api.post(f'{_bulk_url()}/delete_preview', json={'port_ids': [FRONT_PORT_ID]})

        assert response.status_code == HTTPStatus.OK

        entry = response.get_json()[BulkActionKey.PORTS.value][0]

        assert entry[BulkDeletePreviewKey.PORT_ID.value] == FRONT_PORT_ID
        assert entry[BulkDeletePreviewKey.NAME.value] == '1'
        assert entry[BulkDeletePreviewKey.SIDE.value] == PortSide.FRONT.value
        assert set(entry[BulkDeletePreviewKey.CONNECTION_IDS.value]) == {
            INTERNAL_CONNECTION_ID, CABLE_CONNECTION_ID,
        }
        assert entry[BulkDeletePreviewKey.INTERFACE_LINK_IDS.value] == [LINK_ID]

    def test_the_totals_count_a_shared_connection_once(self, rest_api) -> None:
        """The internal pairing joins both selected ports; the delete removes ONE row"""
        response = rest_api.post(
            f'{_bulk_url()}/delete_preview', json={'port_ids': [FRONT_PORT_ID, REAR_PORT_ID]},
        )

        payload = response.get_json()

        assert sorted(payload[BulkActionKey.CONNECTION_IDS.value]) == sorted(ALL_CONNECTION_IDS)

    def test_a_port_with_no_dependents_is_still_listed(self, rest_api) -> None:
        """The dialog shows the whole selection"""
        entry = rest_api.post(
            f'{_bulk_url()}/delete_preview', json={'port_ids': [SPARE_PORT_ID]},
        ).get_json()[BulkActionKey.PORTS.value][0]

        assert entry[BulkDeletePreviewKey.CONNECTION_IDS.value] == []
        assert entry[BulkDeletePreviewKey.INTERFACE_LINK_IDS.value] == []

    def test_it_writes_nothing(self, rest_api, seeded) -> None:
        """A pre-check that deleted anything would be a trap"""
        rest_api.post(f'{_bulk_url()}/delete_preview', json={'port_ids': [FRONT_PORT_ID]})

        assert _stored_port(seeded, FRONT_PORT_ID) is not None
        assert _stored_connection_ids(seeded) == set(ALL_CONNECTION_IDS)

    def test_it_refuses_the_same_selections_the_delete_does(self, rest_api) -> None:
        """A preview that answers is a delete that will not be refused"""
        response = rest_api.post(
            f'{_bulk_url()}/delete_preview', json={'port_ids': [FRONT_PORT_ID, SERVER_PORT_ID]},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    BULK DELETE                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkDelete:
    """DELETE /ports/object/<id>/bulk"""

    def test_the_selected_ports_are_deleted(self, rest_api, seeded) -> None:
        """The ordinary case"""
        response = rest_api.delete(_bulk_url(), json={'port_ids': [SPARE_PORT_ID]})

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[BulkActionKey.DELETED.value] == 1
        assert _stored_port(seeded, SPARE_PORT_ID) is None

    def test_the_cascade_takes_the_connections_and_links(self, rest_api, seeded) -> None:
        """Neither may be left pointing at a port that no longer exists"""
        rest_api.delete(_bulk_url(), json={'port_ids': [FRONT_PORT_ID]})

        assert _stored_connection_ids(seeded) == set()
        assert seeded['links'].find_one({PortInterfaceLinkKey.PUBLIC_ID.value: LINK_ID}) is None

    def test_the_answer_names_what_the_cascade_took(self, rest_api) -> None:
        """Those rows were never named by the caller, so the report has to name them"""
        payload = rest_api.delete(_bulk_url(), json={'port_ids': [FRONT_PORT_ID]}).get_json()

        assert sorted(payload[BulkActionKey.CONNECTION_IDS.value]) == sorted(ALL_CONNECTION_IDS)
        assert payload[BulkActionKey.INTERFACE_LINK_IDS.value] == [LINK_ID]

    def test_the_peer_port_survives(self, rest_api, seeded) -> None:
        """Deleting a port frees its peer, it does not delete it"""
        rest_api.delete(_bulk_url(), json={'port_ids': [FRONT_PORT_ID]})

        assert _stored_port(seeded, SERVER_PORT_ID) is not None

    def test_another_objects_port_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """Nothing is deleted - not even the panel's own port"""
        response = rest_api.delete(_bulk_url(), json={'port_ids': [SPARE_PORT_ID, SERVER_PORT_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_port(seeded, SPARE_PORT_ID) is not None
        assert _stored_port(seeded, SERVER_PORT_ID) is not None

    def test_a_missing_port_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """Same contract, the other reason"""
        response = rest_api.delete(_bulk_url(), json={'port_ids': [SPARE_PORT_ID, MISSING_PORT_ID]})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_port(seeded, SPARE_PORT_ID) is not None

    def test_an_unusable_selection_is_refused(self, rest_api) -> None:
        """A delete with no ids would otherwise be a device-wide delete by accident"""
        assert rest_api.delete(_bulk_url(), json={}).status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                            RESOLVE CONNECTIONS (§34-35)                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBulkResolve:
    """DELETE /port_connections/object/<id>/bulk"""

    @staticmethod
    def _resolve(rest_api, connection_ids: list[int], object_id: int = PANEL_OBJECT_ID):
        """Resolves the given connections in the context of one object."""
        return rest_api.delete(f'{CONNECTIONS_URL}/object/{object_id}/bulk',
                               json={'connection_ids': connection_ids})

    def test_the_selected_connection_is_resolved(self, rest_api, seeded) -> None:
        """The ordinary case: the cable goes, both ports stay"""
        response = self._resolve(rest_api, [CABLE_CONNECTION_ID])

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[BulkActionKey.RESOLVED.value] == 1
        assert _stored_connection_ids(seeded) == {INTERNAL_CONNECTION_ID}

    def test_resolving_one_never_deletes_another(self, rest_api, seeded) -> None:
        """
        §35's rule, on the case it was written for

        The front port carries an external cable AND the panel's internal pairing. Resolving the cable
        must leave the pairing standing - the pair is still physically wired inside the panel.
        """
        self._resolve(rest_api, [CABLE_CONNECTION_ID])

        assert INTERNAL_CONNECTION_ID in _stored_connection_ids(seeded)

    def test_the_internal_pairing_is_resolvable_on_its_own(self, rest_api, seeded) -> None:
        """§34: the internal connection is treatable by itself, and the cable survives it"""
        self._resolve(rest_api, [INTERNAL_CONNECTION_ID])

        assert _stored_connection_ids(seeded) == {CABLE_CONNECTION_ID}

    def test_several_are_resolvable_in_one_call(self, rest_api, seeded) -> None:
        """Several selectable in one dialog, which is what makes it a bulk action"""
        response = self._resolve(rest_api, ALL_CONNECTION_IDS)

        assert response.get_json()[BulkActionKey.RESOLVED.value] == 2
        assert _stored_connection_ids(seeded) == set()

    def test_the_ports_are_untouched(self, rest_api, seeded) -> None:
        """Resolving frees the ports; `connected` is computed, so nothing about them is rewritten"""
        self._resolve(rest_api, ALL_CONNECTION_IDS)

        for port_id in (FRONT_PORT_ID, REAR_PORT_ID, SERVER_PORT_ID):
            assert _stored_port(seeded, port_id) is not None

    def test_the_far_end_may_resolve_it_too(self, rest_api, seeded) -> None:
        """A cable reaches another device, and resolving it from either end is the same act"""
        response = self._resolve(rest_api, [CABLE_CONNECTION_ID], object_id=SERVER_OBJECT_ID)

        assert response.status_code == HTTPStatus.OK
        assert CABLE_CONNECTION_ID not in _stored_connection_ids(seeded)

    def test_a_connection_that_does_not_touch_the_object_is_refused(self, rest_api, seeded) -> None:
        """
        The scope rule: a selection is made in one object's table

        The panel is not an endpoint of a server-only connection, so resolving it from the panel's
        view would be acting out of sight.
        """
        seeded['connections'].update_one(
            {PortConnectionKey.PUBLIC_ID.value: CABLE_CONNECTION_ID},
            {'$set': {PortConnectionKey.ENDPOINTS.value: [SERVER_PORT_ID, MISSING_PORT_ID]}},
        )

        response = self._resolve(rest_api, [CABLE_CONNECTION_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert CABLE_CONNECTION_ID in _stored_connection_ids(seeded)

    def test_a_missing_connection_refuses_the_whole_selection(self, rest_api, seeded) -> None:
        """Nothing is resolved - not even the one that exists"""
        response = self._resolve(rest_api, [CABLE_CONNECTION_ID, MISSING_CONNECTION_ID])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored_connection_ids(seeded) == set(ALL_CONNECTION_IDS)

    def test_an_unusable_selection_is_refused(self, rest_api) -> None:
        """A resolve with no ids is a client bug, not "resolve everything\""""
        response = rest_api.delete(f'{CONNECTIONS_URL}/object/{PANEL_OBJECT_ID}/bulk', json={})

        assert response.status_code == HTTPStatus.BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  THE ERROR TAILS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _raiser(exc: Exception):
    """Returns a function that ignores its args and raises the given exception."""
    def _fail(*_args, **_kwargs):
        raise exc

    return _fail


class TestBulkActionErrorMapping:
    """A denied ACL is a 403, a manager failure a 400, anything else a 500 - on all four routes."""

    EDIT_BODY: dict[str, Any] = {'port_ids': [FRONT_PORT_ID], 'values': {'description': 'after'}}
    DELETE_BODY: dict[str, Any] = {'port_ids': [FRONT_PORT_ID]}
    RESOLVE_BODY: dict[str, Any] = {'connection_ids': [CABLE_CONNECTION_ID]}

    def _denied(self, monkeypatch) -> None:
        """Makes the object read refuse, the way an ACL denial reaches these routes."""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('denied')))

    @pytest.mark.parametrize('method, url_suffix, body', [
        ('patch', '', EDIT_BODY),
        ('post', '/delete_preview', DELETE_BODY),
        ('delete', '', DELETE_BODY),
    ], ids=['edit', 'preview', 'delete'])
    def test_a_denied_object_is_a_403(
        self, rest_api, monkeypatch, method: str, url_suffix: str, body: dict[str, Any],
    ) -> None:
        """The port bulk actions are scoped to an object whose ACL has to allow the caller"""
        self._denied(monkeypatch)

        response = getattr(rest_api, method)(f'{_bulk_url()}{url_suffix}', json=body)

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_an_edit_manager_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """A write that could not be applied is reported as a refusal, not as a server fault"""
        monkeypatch.setattr(PortsManager, 'update_many', _raiser(PortsManagerUpdateError('boom')))

        assert rest_api.patch(_bulk_url(), json=self.EDIT_BODY).status_code == HTTPStatus.BAD_REQUEST

    def test_an_edit_unexpected_error_is_a_500(self, rest_api, monkeypatch) -> None:
        """Anything the route did not anticipate"""
        monkeypatch.setattr(PortsManager, 'update_many', _raiser(RuntimeError('boom')))

        assert rest_api.patch(_bulk_url(), json=self.EDIT_BODY).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_preview_manager_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """The pre-check reads the same rows the delete does, and fails the same way"""
        monkeypatch.setattr(PortsManager, 'find', _raiser(PortsManagerGetError('boom')))

        response = rest_api.post(f'{_bulk_url()}/delete_preview', json=self.DELETE_BODY)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_preview_unexpected_error_is_a_500(self, rest_api, monkeypatch) -> None:
        """Anything else"""
        monkeypatch.setattr(PortsManager, 'find', _raiser(RuntimeError('boom')))

        response = rest_api.post(f'{_bulk_url()}/delete_preview', json=self.DELETE_BODY)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_delete_manager_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """The cascade ran, the port delete did not - reported rather than swallowed"""
        monkeypatch.setattr(PortsManager, 'delete_many', _raiser(PortsManagerDeleteError('boom')))

        assert rest_api.delete(_bulk_url(), json=self.DELETE_BODY).status_code == HTTPStatus.BAD_REQUEST

    def test_a_delete_unexpected_error_is_a_500(self, rest_api, monkeypatch) -> None:
        """Anything else"""
        monkeypatch.setattr(PortsManager, 'delete_many', _raiser(RuntimeError('boom')))

        assert rest_api.delete(_bulk_url(), json=self.DELETE_BODY).status_code \
            == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_resolve_manager_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """The resolve consults no object ACL (Q13), so its tails are the connection manager's"""
        monkeypatch.setattr(
            PortConnectionsManager, 'delete_many', _raiser(PortConnectionsManagerDeleteError('boom')),
        )

        response = rest_api.delete(
            f'{CONNECTIONS_URL}/object/{PANEL_OBJECT_ID}/bulk', json=self.RESOLVE_BODY,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_resolve_read_failure_is_a_400(self, rest_api, monkeypatch) -> None:
        """Reading the selection can fail the same way"""
        monkeypatch.setattr(
            PortConnectionsManager, 'find', _raiser(PortConnectionsManagerGetError('boom')),
        )

        response = rest_api.delete(
            f'{CONNECTIONS_URL}/object/{PANEL_OBJECT_ID}/bulk', json=self.RESOLVE_BODY,
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_resolve_unexpected_error_is_a_500(self, rest_api, monkeypatch) -> None:
        """Anything else"""
        monkeypatch.setattr(PortConnectionsManager, 'delete_many', _raiser(RuntimeError('boom')))

        response = rest_api.delete(
            f'{CONNECTIONS_URL}/object/{PANEL_OBJECT_ID}/bulk', json=self.RESOLVE_BODY,
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
