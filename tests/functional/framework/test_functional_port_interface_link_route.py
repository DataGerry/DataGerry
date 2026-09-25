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
Functional tests for the port <-> interface link REST routes

Covers the whole surface over HTTP: create / read single / read per port / update / delete / the
dangling report, plus the invariants the routes exist to hold - the interface triple is immutable, the
relation type is the only editable field and comes from a fixed list, and a row with no multi_data_id
can not be linked.

The pair of behaviours that defines the feature is asserted end to end here: **creating an
already-dangling link is refused, while an existing link going dangling is not**. The second is
simulated the way it really happens - the interface row is removed from the object by something that
has nothing to do with ports - and the link must still read, must report itself in the repair list, and
must still be deletable
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import abort

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_interface_link_model import (
    AssignableInterfaceKey,
    AssignableInterfaceObjectKey,
    AssignableInterfaceSubnetKey,
    CmdbPortInterfaceLink,
    InterfaceRelationType,
    PortInterfaceLinkKey,
)
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager
from cmdb.interface.rest_api.routes.port_routes import port_interface_link_routes
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.errors.security import AccessDeniedError
from cmdb.errors.manager.port_interface_links_manager import (
    PortInterfaceLinksManagerDeleteError,
    PortInterfaceLinksManagerGetError,
    PortInterfaceLinksManagerInsertError,
    PortInterfaceLinksManagerUpdateError,
)
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import (
    INTERFACE_ROW_KEY,
    PORT_INTERFACE_LINKS_KEY,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_constants import PORT_CONNECTED_KEY
# -------------------------------------------------------------------------------------------------------------------- #

PORTS_URL: str = '/ports'
LINKS_URL: str = f'{PORTS_URL}/interface_links'

PORT_TYPE_ID: int = 9960
HOST_TYPE_ID: int = 9961

SWITCH_OBJECT_ID: int = 9970
HOST_OBJECT_ID: int = 9971

PORT_ID: int = 9980
OTHER_PORT_ID: int = 9981

MISSING_PORT_ID: int = 9998
MISSING_LINK_ID: int = 9997
MISSING_OBJECT_ID: int = 9996

ROW_ID: int = 1
OTHER_ROW_ID: int = 2
MISSING_ROW_ID: int = 99

ROW_IP: str = '10.0.0.1'
OTHER_ROW_IP: str = '10.0.0.2'
ROW_MAC: str = '00:1A:2B:3C:4D:5E'
OTHER_ROW_MAC: str = '00:1A:2B:3C:4D:5F'

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, HOST_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [SWITCH_OBJECT_ID, HOST_OBJECT_ID]
ALL_PORT_IDS: list[int] = [PORT_ID, OTHER_PORT_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """
    Licenses IPAM so the gated link surface is reachable

    Port Connectivity is gated behind LicenseFeature.IPAM. That the gate really blocks the surface is
    asserted by the license tests.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)


def _type_doc(public_id: int, uses_ports: bool = False) -> dict[str, Any]:
    """A CmdbType document, port-bearing or not."""
    return {
        'public_id': public_id,
        'name': f'link-type-{public_id}',
        'label': f'Link Type {public_id}',
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


def _interface_row(multi_data_id: int, ip: str, mac: str = ROW_MAC) -> dict[str, Any]:
    """
    One dg-ipam-interface MDS row, carrying both addresses the section declares

    IP and MAC are the two values the interface is the single source of truth for - the concept keeps
    neither on the port - so a fixture holding only the IP would let the read path drop the MAC
    unnoticed.
    """
    return {
        'multi_data_id': multi_data_id,
        'data': [
            {'name': InterfaceField.IP.value, 'value': ip, 'type': FieldType.TEXT.value},
            {'name': InterfaceField.MAC.value, 'value': mac, 'type': FieldType.TEXT.value},
        ],
    }


def _row_value(interface_row: dict[str, Any], field_name: str) -> Any:
    """Reads one field value out of an interface row, by name rather than by position."""
    return next(
        (entry.get('value') for entry in interface_row.get('data', []) if entry.get('name') == field_name),
        None,
    )


def _object_doc(public_id: int, type_id: int, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A CmdbObject, optionally carrying dg-ipam-interface rows."""
    doc: dict[str, Any] = {
        'public_id': public_id,
        'type_id': type_id,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}', 'type': FieldType.TEXT.value}],
        'multi_data_sections': [],
    }

    if rows:
        doc['multi_data_sections'] = [{
            'section_id': IpamSection.INTERFACE.value,
            'highest_id': max(row['multi_data_id'] for row in rows),
            'values': rows,
        }]

    return doc


def _port_doc(public_id: int, object_id: int, name: str) -> dict[str, Any]:
    """A stored CmdbPort document."""
    return {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.SIDE.value: PortSide.SINGLE.value,
        PortKey.NAME.value: name,
        PortKey.AUTHOR_ID.value: 1,
    }


def _payload(
        object_id: int = SWITCH_OBJECT_ID,
        multi_data_id: int = ROW_ID,
        relation_type: str = InterfaceRelationType.PHYSICAL.value,
        **overrides: Any) -> dict[str, Any]:
    """A create/update body for a link."""
    payload: dict[str, Any] = {
        'interface_object_id': object_id,
        'interface_multi_data_id': multi_data_id,
        'relation_type': relation_type,
    }
    payload.update(overrides)

    return payload


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds the types, the switch with its ports AND its interface rows, and a foreign host

    A port may only be linked to its own object's interfaces, so the switch has to carry the rows the
    links point at. The host keeps interface rows of its own precisely because it is the FOREIGN
    object: it is what the same-object guard is tested against.
    """
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    ports = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    links = database_manager.get_collection(CmdbPortInterfaceLink.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})
        ports.delete_many({PortKey.PUBLIC_ID.value: {'$in': ALL_PORT_IDS}})
        links.delete_many({PortInterfaceLinkKey.PORT_ID.value: {'$in': ALL_PORT_IDS}})

    _purge()

    types.insert_many([_type_doc(PORT_TYPE_ID, uses_ports=True), _type_doc(HOST_TYPE_ID)])
    objects.insert_many([
        _object_doc(SWITCH_OBJECT_ID, PORT_TYPE_ID, [
            _interface_row(ROW_ID, ROW_IP),
            _interface_row(OTHER_ROW_ID, OTHER_ROW_IP, OTHER_ROW_MAC),
        ]),
        _object_doc(HOST_OBJECT_ID, HOST_TYPE_ID, [
            _interface_row(ROW_ID, ROW_IP),
            _interface_row(OTHER_ROW_ID, OTHER_ROW_IP, OTHER_ROW_MAC),
        ]),
    ])
    ports.insert_many([
        _port_doc(PORT_ID, SWITCH_OBJECT_ID, 'Gi0/1'),
        _port_doc(OTHER_PORT_ID, SWITCH_OBJECT_ID, 'Gi0/2'),
    ])

    yield objects

    _purge()


def _create(rest_api, port_id: int = PORT_ID, **kwargs: Any):
    """POSTs a link on a port."""
    return rest_api.post(f'{PORTS_URL}/{port_id}/interface_links/', json=_payload(**kwargs))


def _created_id(response) -> int:
    """Reads the public_id out of an InsertSingleResponse."""
    return response.get_json()['result_id']


def _break_the_row(objects, multi_data_id: int = ROW_ID) -> None:
    """
    Removes one interface row from the host, the way an ordinary object write would

    This is how a link really goes dangling: the MDS row id is not durable, so a full PUT or a CSV
    import overwrite renumbers or drops it without ever touching a port.
    """
    objects.update_one(
        {'public_id': SWITCH_OBJECT_ID},
        {'$pull': {'multi_data_sections.$[section].values': {'multi_data_id': multi_data_id}}},
        array_filters=[{'section.section_id': IpamSection.INTERFACE.value}],
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateLink:
    """POST /ports/<port_id>/interface_links/"""

    def test_creates_a_link_and_stamps_the_server_owned_fields(self, rest_api) -> None:
        """The author and the creation time come from the request, never from the body."""
        response = _create(rest_api)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        created = response.get_json()['raw']

        assert created[PortInterfaceLinkKey.PORT_ID.value] == PORT_ID
        assert created[PortInterfaceLinkKey.AUTHOR_ID.value] is not None
        assert created[PortInterfaceLinkKey.CREATION_TIME.value] is not None

    def test_the_section_id_defaults_to_the_ipam_interface_template(self, rest_api) -> None:
        """
        Stored rather than assumed, so the triple stays self-describing

        A second interface-bearing section later would not invalidate every existing row.
        """
        created = _create(rest_api).get_json()['raw']

        assert created[PortInterfaceLinkKey.INTERFACE_SECTION_ID.value] == IpamSection.INTERFACE.value

    def test_the_port_comes_from_the_url_not_the_body(self, rest_api) -> None:
        """
        A body naming a different port is ignored rather than reconciled

        The URL already identifies the port whose owner ACL was checked, so a payload key could only
        ever disagree with it - which is why 'port_id' is not a request key at all.
        """
        response = rest_api.post(f'{PORTS_URL}/{OTHER_PORT_ID}/interface_links/', json={
            **_payload(), 'port_id': PORT_ID,
        })

        assert response.get_json()['raw'][PortInterfaceLinkKey.PORT_ID.value] == OTHER_PORT_ID

    def test_one_port_may_carry_several_interfaces(self, rest_api) -> None:
        """A bond member and a VLAN sub-interface on the same port - the N side of N:M"""
        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        response = _create(
            rest_api, multi_data_id=OTHER_ROW_ID, relation_type=InterfaceRelationType.VLAN.value,
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_one_interface_may_be_reached_over_several_ports(self, rest_api) -> None:
        """The M side - a bonded interface reached over two physical ports"""
        _create(rest_api, relation_type=InterfaceRelationType.BOND.value)

        response = _create(
            rest_api, port_id=OTHER_PORT_ID, relation_type=InterfaceRelationType.BOND.value,
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_the_same_pair_twice_is_refused(self, rest_api) -> None:
        """One link per port/interface pair - the relation type describes it, it does not multiply it"""
        _create(rest_api)

        response = _create(rest_api, relation_type=InterfaceRelationType.VLAN.value)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already linked' in response.get_json()['message']

    def test_a_row_without_a_multi_data_id_is_refused(self, rest_api) -> None:
        """
        The id IS the reference

        A link without one would point at nothing from the moment it was created, which the concept
        refuses outright.
        """
        response = rest_api.post(f'{PORTS_URL}/{PORT_ID}/interface_links/', json={
            'interface_object_id': HOST_OBJECT_ID,
            'relation_type': InterfaceRelationType.PHYSICAL.value,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'multi_data_id' in response.get_json()['message']

    def test_an_already_dangling_link_is_refused(self, rest_api) -> None:
        """
        Creating one is a mistake the write path can see, unlike one going dangling later

        This is the half of the soft reference that IS enforced.
        """
        response = _create(rest_api, multi_data_id=MISSING_ROW_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_unknown_relation_type_is_refused(self, rest_api) -> None:
        """The list is fixed and non-customizable, so an unknown value is a typo"""
        response = _create(rest_api, relation_type='SOMETHING_ELSE')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert InterfaceRelationType.PHYSICAL.value in response.get_json()['message']

    def test_a_missing_relation_type_is_refused(self, rest_api) -> None:
        """It is required - a link with no relation type describes nothing"""
        response = rest_api.post(f'{PORTS_URL}/{PORT_ID}/interface_links/', json={
            'interface_object_id': SWITCH_OBJECT_ID, 'interface_multi_data_id': ROW_ID,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_port_is_a_404(self, rest_api) -> None:
        """The port is the link's hard reference"""
        assert _create(rest_api, port_id=MISSING_PORT_ID).status_code == HTTPStatus.NOT_FOUND

    def test_an_interface_on_another_object_is_refused(self, rest_api) -> None:
        """
        A port may only be linked to its OWN object's interfaces

        The host carries a perfectly valid interface row with the same multi_data_id - the refusal is
        about which device it belongs to, not about whether it exists.
        """
        response = _create(rest_api, object_id=HOST_OBJECT_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'different one' in response.get_json()['message']

    def test_the_refusal_names_both_objects(self, rest_api) -> None:
        """A client has to be able to see which object it should have asked for."""
        message = _create(rest_api, object_id=HOST_OBJECT_ID).get_json()['message']

        assert str(SWITCH_OBJECT_ID) in message
        assert str(HOST_OBJECT_ID) in message

    def test_an_unknown_object_is_refused_as_foreign(self, rest_api) -> None:
        """
        An id naming nothing is not the port's object either

        The same-object guard runs before the row is read, so an object that does not exist is refused
        for being a different object (400) rather than for being missing (404) - the 404 arm survives
        only for the owner vanishing mid-request, which `get_interface_row_or_abort` still covers.
        """
        assert _create(rest_api, object_id=MISSING_OBJECT_ID).status_code == HTTPStatus.BAD_REQUEST

    def test_several_ports_may_share_one_interface(self, rest_api) -> None:
        """
        The M side of N:M, and the case Change 1 must not take away

        A bonded interface reached over two physical ports of the same device - both links name the
        same row, and only the same PORT twice is refused.
        """
        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        response = _create(rest_api, port_id=OTHER_PORT_ID, relation_type=InterfaceRelationType.BOND.value)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadLink:
    """GET the single link and the per-port list, both resolving the interface row."""

    def test_a_read_resolves_the_live_interface_row(self, rest_api) -> None:
        """
        The point of the link: the interface's values come from the row, never from a copy

        The IP and the MAC the caller sees are the ones stored on the object, so editing the interface
        is visible immediately and no second truth exists. The row is handed back whole: the read
        projects nothing, which is what keeps a field added to the section template later visible here
        without a change to this route.
        """
        new_id: int = _created_id(_create(rest_api))

        link = rest_api.get(f'{LINKS_URL}/{new_id}').get_json()['result']

        assert _row_value(link[INTERFACE_ROW_KEY], InterfaceField.IP.value) == ROW_IP
        assert _row_value(link[INTERFACE_ROW_KEY], InterfaceField.MAC.value) == ROW_MAC

    def test_a_missing_link_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        assert rest_api.get(f'{LINKS_URL}/{MISSING_LINK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_the_port_list_returns_every_link(self, rest_api) -> None:
        """A port's interface list, which is what the ports panel shows"""
        _create(rest_api)
        _create(rest_api, multi_data_id=OTHER_ROW_ID, relation_type=InterfaceRelationType.VLAN.value)

        links = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/').get_json()

        assert len(links) == 2
        assert {_row_value(link[INTERFACE_ROW_KEY], InterfaceField.IP.value) for link in links} == {
            ROW_IP, OTHER_ROW_IP,
        }
        assert {_row_value(link[INTERFACE_ROW_KEY], InterfaceField.MAC.value) for link in links} == {
            ROW_MAC, OTHER_ROW_MAC,
        }

    def test_a_port_without_links_answers_with_an_empty_list(self, rest_api) -> None:
        """Not linked is a normal state, not a 404"""
        response = rest_api.get(f'{PORTS_URL}/{OTHER_PORT_ID}/interface_links/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == []

    def test_a_missing_port_is_a_404(self, rest_api) -> None:
        """A different answer from 'this port has no links', so a typo is distinguishable"""
        response = rest_api.get(f'{PORTS_URL}/{MISSING_PORT_ID}/interface_links/')

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the links on the PORT reads                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestThePortReadsCarryTheLinks:
    """
    Both port reads answer with each port's interface links attached

    The ports panel shows a port's addresses next to the port. Without this it would have to call
    ``GET /ports/<id>/interface_links/`` once per row - 48 follow-up requests for a switch - so the
    links ride along with the ports, exactly as the derived `connected` flag does.
    """

    def test_the_object_read_carries_the_links_per_port(self, rest_api) -> None:
        """Grouped by port: a link of one port must not appear on another"""
        _create(rest_api)
        _create(rest_api, port_id=OTHER_PORT_ID, multi_data_id=OTHER_ROW_ID)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()
        by_id = {port[PortKey.PUBLIC_ID.value]: port for port in ports}

        assert [link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value]
                for link in by_id[PORT_ID][PORT_INTERFACE_LINKS_KEY]] == [ROW_ID]
        assert [link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value]
                for link in by_id[OTHER_PORT_ID][PORT_INTERFACE_LINKS_KEY]] == [OTHER_ROW_ID]

    def test_the_live_row_travels_with_the_link(self, rest_api) -> None:
        """
        The addresses come from the row, whole - the same contract the dedicated link route has

        Asserted by field NAME, never by position: a template field added later has to keep working.
        """
        _create(rest_api)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()
        row = next(port for port in ports
                   if port[PortKey.PUBLIC_ID.value] == PORT_ID)[PORT_INTERFACE_LINKS_KEY][0][INTERFACE_ROW_KEY]

        assert _row_value(row, InterfaceField.IP.value) == ROW_IP
        assert _row_value(row, InterfaceField.MAC.value) == ROW_MAC

    def test_a_port_with_several_links_keeps_them_all(self, rest_api) -> None:
        """The N:M case: a bond member, or a stack of VLAN sub-interfaces on one port"""
        _create(rest_api)
        _create(rest_api, multi_data_id=OTHER_ROW_ID, relation_type=InterfaceRelationType.VLAN.value)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()
        links = next(port for port in ports
                     if port[PortKey.PUBLIC_ID.value] == PORT_ID)[PORT_INTERFACE_LINKS_KEY]

        assert {_row_value(link[INTERFACE_ROW_KEY], InterfaceField.IP.value) for link in links} == {
            ROW_IP, OTHER_ROW_IP,
        }

    def test_an_unlinked_port_carries_an_empty_list(self, rest_api) -> None:
        """Never a missing key - "linked to nothing" must not look like "not answered\""""
        _create(rest_api)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()
        other = next(port for port in ports if port[PortKey.PUBLIC_ID.value] == OTHER_PORT_ID)

        assert other[PORT_INTERFACE_LINKS_KEY] == []

    def test_a_dangling_link_is_listed_without_its_row(self, rest_api, seeded) -> None:
        """Shown, never hidden - the same contract as the dedicated link list"""
        _create(rest_api)
        _break_the_row(seeded)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()
        links = next(port for port in ports
                     if port[PortKey.PUBLIC_ID.value] == PORT_ID)[PORT_INTERFACE_LINKS_KEY]

        assert len(links) == 1
        assert INTERFACE_ROW_KEY not in links[0]

    def test_the_connected_flag_is_still_there(self, rest_api) -> None:
        """The new key is additive: what the panel already read must keep arriving"""
        _create(rest_api)

        ports = rest_api.get(f'{PORTS_URL}/object/{SWITCH_OBJECT_ID}').get_json()

        assert all(PORT_CONNECTED_KEY in port for port in ports)

    def test_the_single_port_read_carries_the_links_too(self, rest_api) -> None:
        """A port looks the same whichever read produced it"""
        _create(rest_api)

        port = rest_api.get(f'{PORTS_URL}/{PORT_ID}').get_json()['result']

        assert _row_value(port[PORT_INTERFACE_LINKS_KEY][0][INTERFACE_ROW_KEY],
                          InterfaceField.IP.value) == ROW_IP

    def test_the_single_read_of_an_unlinked_port_carries_an_empty_list(self, rest_api) -> None:
        """Same contract as the object read"""
        port = rest_api.get(f'{PORTS_URL}/{OTHER_PORT_ID}').get_json()['result']

        assert port[PORT_INTERFACE_LINKS_KEY] == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the soft reference, going dangling                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDanglingLinks:
    """
    An existing link going dangling is tolerated, reported, and never cascaded

    The row is removed the way it really happens - by an object write that has nothing to do with
    ports - because an MDS row id is not durable.
    """

    def test_a_dangling_link_still_reads(self, rest_api, seeded) -> None:
        """
        Tolerated, not an error

        The customer has to be able to see that the link exists and that what it named is gone.
        """
        new_id: int = _created_id(_create(rest_api))
        _break_the_row(seeded)

        response = rest_api.get(f'{LINKS_URL}/{new_id}')

        assert response.status_code == HTTPStatus.OK
        assert INTERFACE_ROW_KEY not in response.get_json()['result']

    def test_a_dangling_link_is_not_removed_from_the_port_list(self, rest_api, seeded) -> None:
        """Hiding it would leave the customer with damage they can neither see nor repair"""
        _create(rest_api)
        _break_the_row(seeded)

        links = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/').get_json()

        assert len(links) == 1
        assert INTERFACE_ROW_KEY not in links[0]

    def test_the_report_lists_the_dangling_link(self, rest_api, seeded) -> None:
        """The repair list - the whole reason tolerating a dangling link is acceptable"""
        new_id: int = _created_id(_create(rest_api))
        _break_the_row(seeded)

        dangling = rest_api.get(f'{LINKS_URL}/dangling').get_json()

        assert [link[PortInterfaceLinkKey.PUBLIC_ID.value] for link in dangling] == [new_id]

    def test_the_report_ignores_the_healthy_links(self, rest_api, seeded) -> None:
        """It is a repair list, not an inventory"""
        _create(rest_api)
        broken_id: int = _created_id(_create(
            rest_api, multi_data_id=OTHER_ROW_ID, relation_type=InterfaceRelationType.VLAN.value,
        ))
        _break_the_row(seeded, OTHER_ROW_ID)

        dangling = rest_api.get(f'{LINKS_URL}/dangling').get_json()

        assert [link[PortInterfaceLinkKey.PUBLIC_ID.value] for link in dangling] == [broken_id]

    def test_a_healthy_installation_reports_nothing(self, rest_api) -> None:
        """Nothing to repair is the normal state"""
        _create(rest_api)

        assert rest_api.get(f'{LINKS_URL}/dangling').get_json() == []

    def test_a_dangling_link_is_still_deletable(self, rest_api, seeded) -> None:
        """The repair the report exists to enable"""
        new_id: int = _created_id(_create(rest_api))
        _break_the_row(seeded)

        assert rest_api.delete(f'{LINKS_URL}/{new_id}').status_code in (
            HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT,
        )
        assert rest_api.get(f'{LINKS_URL}/dangling').get_json() == []

    def test_deleting_the_interface_object_does_not_cascade(self, rest_api, seeded) -> None:
        """
        The soft reference in its strongest form

        Even the whole object going away leaves the link in place to be reported - the link is the only
        record of what the customer meant, and removing it silently would destroy that.

        Asserted through the dangling REPORT rather than through the link's own read: since a port may
        only link its own object's interfaces, that object is also the port's owner, and every link
        route resolves the owner to check its ACL. So the link survives the object; reading it one by
        one does not. The report is what the survival is for.
        """
        _create(rest_api)
        # A raw collection delete, so no route cascade runs - the link survives its object entirely
        seeded.delete_one({'public_id': SWITCH_OBJECT_ID})

        assert len(rest_api.get(f'{LINKS_URL}/dangling').get_json()) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateLink:
    """PUT /ports/interface_links/<id> - the relation type only"""

    def test_updates_the_relation_type(self, rest_api) -> None:
        """The one thing an update writes"""
        new_id: int = _created_id(_create(rest_api))

        response = rest_api.put(
            f'{LINKS_URL}/{new_id}', json={'relation_type': InterfaceRelationType.BOND.value},
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

        updated = rest_api.get(f'{LINKS_URL}/{new_id}').get_json()['result']

        assert updated[PortInterfaceLinkKey.RELATION_TYPE.value] == InterfaceRelationType.BOND.value

    def test_changing_the_interface_row_is_refused(self, rest_api) -> None:
        """
        The triple is the link's identity, so changing one key is creating a different link

        Refused rather than ignored, so a client can not discover that its edit did nothing.
        """
        new_id: int = _created_id(_create(rest_api))

        response = rest_api.put(f'{LINKS_URL}/{new_id}', json={
            'interface_multi_data_id': OTHER_ROW_ID,
            'relation_type': InterfaceRelationType.PHYSICAL.value,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_changing_the_interface_object_is_refused(self, rest_api) -> None:
        """Same rule, the other coordinate"""
        new_id: int = _created_id(_create(rest_api))

        response = rest_api.put(f'{LINKS_URL}/{new_id}', json={
            'interface_object_id': HOST_OBJECT_ID,
            'relation_type': InterfaceRelationType.PHYSICAL.value,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_repeating_the_stored_triple_is_allowed(self, rest_api) -> None:
        """A client that round-trips a GET sends the whole document back"""
        new_id: int = _created_id(_create(rest_api))

        response = rest_api.put(f'{LINKS_URL}/{new_id}', json=_payload(
            relation_type=InterfaceRelationType.VLAN.value,
        ))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_an_unknown_relation_type_is_refused(self, rest_api) -> None:
        """The fixed list applies on update too"""
        new_id: int = _created_id(_create(rest_api))

        response = rest_api.put(f'{LINKS_URL}/{new_id}', json={'relation_type': 'SOMETHING_ELSE'})

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_link_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        response = rest_api.put(
            f'{LINKS_URL}/{MISSING_LINK_ID}', json={'relation_type': InterfaceRelationType.OTHER.value},
        )

        assert response.status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       DELETE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDeleteLink:
    """DELETE /ports/interface_links/<id>"""

    def test_deletes_the_link(self, rest_api) -> None:
        """The ordinary case"""
        new_id: int = _created_id(_create(rest_api))

        assert rest_api.delete(f'{LINKS_URL}/{new_id}').status_code in (
            HTTPStatus.OK, HTTPStatus.ACCEPTED, HTTPStatus.NO_CONTENT,
        )
        assert rest_api.get(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.NOT_FOUND

    def test_neither_side_of_the_link_is_touched(self, rest_api, seeded) -> None:
        """Removing the association removes nothing else"""
        new_id: int = _created_id(_create(rest_api))

        rest_api.delete(f'{LINKS_URL}/{new_id}')

        assert rest_api.get(f'{PORTS_URL}/{PORT_ID}').status_code == HTTPStatus.OK
        assert seeded.find_one({'public_id': HOST_OBJECT_ID}) is not None

    def test_the_pair_may_be_linked_again(self, rest_api) -> None:
        """Guards against a delete that only marks rows - the unique index would refuse the next link"""
        new_id: int = _created_id(_create(rest_api))
        rest_api.delete(f'{LINKS_URL}/{new_id}')

        assert _create(rest_api).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_missing_link_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        assert rest_api.delete(f'{LINKS_URL}/{MISSING_LINK_ID}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the cascade, driven over the /ports route                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPortDeleteCascade:
    """DELETE /ports/<id> takes the port's links with it - the HARD half of the reference"""

    def test_deleting_a_port_removes_its_links(self, rest_api) -> None:
        """A link without its port is a row nothing can reach and nothing can repair"""
        new_id: int = _created_id(_create(rest_api))

        rest_api.delete(f'{PORTS_URL}/{PORT_ID}')

        assert rest_api.get(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.NOT_FOUND

    def test_deleting_a_port_leaves_another_ports_links_alone(self, rest_api) -> None:
        """The scope is the deleted port"""
        kept_id: int = _created_id(_create(rest_api, port_id=OTHER_PORT_ID))
        _create(rest_api)

        rest_api.delete(f'{PORTS_URL}/{PORT_ID}')

        assert rest_api.get(f'{LINKS_URL}/{kept_id}').status_code == HTTPStatus.OK

    def test_deleting_a_port_does_not_touch_the_interface_object(self, rest_api, seeded) -> None:
        """The interface half is soft in both directions: nothing about the object changes"""
        _create(rest_api)

        rest_api.delete(f'{PORTS_URL}/{PORT_ID}')

        host = seeded.find_one({'public_id': HOST_OBJECT_ID})

        assert len(host['multi_data_sections'][0]['values']) == 2


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

    A manager error surfacing as a 500 hides a recoverable problem; an unexpected error surfacing as a
    400 tells the caller their request was wrong when it was not. The create route has a third arm: an
    insert failure is the unique index refusing a racing duplicate, and it keeps the readable message
    the pre-check would have given.
    """

    def test_create_retrieval_of_the_created_link_failing_is_404(self, rest_api, monkeypatch) -> None:
        """The insert worked but the read-back did not, so the response would be empty."""
        monkeypatch.setattr(PortInterfaceLinksManager, 'get_item', lambda *_a, **_k: None)

        assert _create(rest_api).status_code == HTTPStatus.NOT_FOUND

    def test_create_duplicate_from_the_index_is_400(self, rest_api, monkeypatch) -> None:
        """
        The arm that holds under concurrency, and the only way to reach it

        The pre-check is a read followed by a write, so in a real race both creates pass it and the
        unique index stops the loser at insert time. Injected at the insert itself, which is where a
        concurrent write lands.
        """
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'insert_item',
            _raiser(PortInterfaceLinksManagerInsertError('duplicate key')),
        )

        response = _create(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'already linked' in response.get_json()['message']

    def test_create_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Not a 400: nothing is wrong with the request."""
        monkeypatch.setattr(PortInterfaceLinksManager, 'insert_item', _raiser(RuntimeError('boom')))

        assert _create(rest_api).status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_single_read_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed read is reported as a bad request, not as a crash."""
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'get_item',
            _raiser(PortInterfaceLinksManagerGetError('boom')),
        )

        assert rest_api.get(f'{LINKS_URL}/1').status_code == HTTPStatus.BAD_REQUEST

    def test_single_read_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(PortInterfaceLinksManager, 'get_item', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{LINKS_URL}/1').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_port_list_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """The per-port list route maps its own manager error."""
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'get_links_of_port',
            _raiser(PortInterfaceLinksManagerGetError('boom')),
        )

        response = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_port_list_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'get_links_of_port', _raiser(RuntimeError('boom')),
        )

        response = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/')

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_dangling_report_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """The repair report maps its own manager error."""
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'get_all_links',
            _raiser(PortInterfaceLinksManagerGetError('boom')),
        )

        assert rest_api.get(f'{LINKS_URL}/dangling').status_code == HTTPStatus.BAD_REQUEST

    def test_dangling_report_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        monkeypatch.setattr(PortInterfaceLinksManager, 'get_all_links', _raiser(RuntimeError('boom')))

        assert rest_api.get(f'{LINKS_URL}/dangling').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_update_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed write is reported as a bad request."""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'update_item',
            _raiser(PortInterfaceLinksManagerUpdateError('boom')),
        )

        response = rest_api.put(
            f'{LINKS_URL}/{new_id}', json={'relation_type': InterfaceRelationType.BOND.value},
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_update_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(PortInterfaceLinksManager, 'update_item', _raiser(RuntimeError('boom')))

        response = rest_api.put(
            f'{LINKS_URL}/{new_id}', json={'relation_type': InterfaceRelationType.BOND.value},
        )

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_delete_manager_error_is_400(self, rest_api, monkeypatch) -> None:
        """A failed delete is reported as a bad request."""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(
            PortInterfaceLinksManager, 'delete_item',
            _raiser(PortInterfaceLinksManagerDeleteError('boom')),
        )

        assert rest_api.delete(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.BAD_REQUEST

    def test_delete_unexpected_error_is_500(self, rest_api, monkeypatch) -> None:
        """Anything else is a server error."""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(PortInterfaceLinksManager, 'delete_item', _raiser(RuntimeError('boom')))

        assert rest_api.delete(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    def test_a_denied_owner_is_403_on_create(self, rest_api, monkeypatch) -> None:
        """
        The PORT owner's ACL is what governs a link, so a denied owner is a 403

        Patched at ObjectsManager.get_object, the same seam the /ports routes' ACL cases use.
        """
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert _create(rest_api).status_code == HTTPStatus.FORBIDDEN

    def test_a_denied_owner_is_403_on_read(self, rest_api, monkeypatch) -> None:
        """
        The same on a read, and the link has to EXIST for the ACL to be what refuses it

        Addressing a missing link would answer 404 before the owner is ever resolved, which would make
        this pass for the wrong reason.
        """
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.FORBIDDEN

    def test_a_denied_owner_is_403_on_delete(self, rest_api, monkeypatch) -> None:
        """A link may not be removed by somebody who cannot see the port it belongs to"""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.delete(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.FORBIDDEN

    def test_a_denied_owner_is_403_on_update(self, rest_api, monkeypatch) -> None:
        """And the write path in between"""
        new_id: int = _created_id(_create(rest_api))
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.put(
            f'{LINKS_URL}/{new_id}', json={'relation_type': InterfaceRelationType.BOND.value},
        )

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_a_denied_owner_is_403_on_the_port_list(self, rest_api, monkeypatch) -> None:
        """Reading a port's links means reading part of the port's owner"""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        response = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/')

        assert response.status_code == HTTPStatus.FORBIDDEN



# -------------------------------------------------------------------------------------------------------------------- #
#                                              THE ASSIGNABLE-INTERFACE PICKER                                         #
# -------------------------------------------------------------------------------------------------------------------- #
ASSIGNABLE_URL: str = f'{PORTS_URL}/{PORT_ID}/assignable_interfaces/'

SUBNET_TYPE_ID: int = 9962
SUBNET_OBJECT_ID: int = 9972
SUBNET_NAME: str = 'Office LAN'


class TestAssignableInterfaces:
    """
    The picker a client uses to choose what to link, which is the only way to discover an MDS row

    One scope, always: the port's own object. A port may only be linked to its own object's
    interfaces, so there is nothing to widen and the picker takes no scope argument - the host's rows
    exist in the fixture precisely so their ABSENCE from every answer can be asserted.
    """

    @pytest.fixture(autouse=True)
    def _picker_state(self, database_manager: MongoDatabaseManager, database_name: str, seeded):
        """
        Makes both types IPAM-capable and gives the switch two known interface rows

        The rows are replaced rather than added to, so the picker assertions can count exactly. The
        host stays interface-bearing on purpose: it is the foreign object whose rows must never be
        offered.
        """
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

        interface_section = {'type': SectionType.MDS_SECTION.value,
                             'name': IpamSection.INTERFACE.value, 'label': 'Interfaces', 'fields': []}

        for type_id in (HOST_TYPE_ID, PORT_TYPE_ID):
            types.update_one({'public_id': type_id},
                             {'$push': {'render_meta.sections': interface_section}})

        objects.update_one(
            {'public_id': SWITCH_OBJECT_ID},
            {'$set': {'multi_data_sections': [{
                'section_id': IpamSection.INTERFACE.value,
                'highest_id': OTHER_ROW_ID,
                'values': [
                    _interface_row(ROW_ID, '10.9.9.9', '00:11:22:33:44:55'),
                    _interface_row(OTHER_ROW_ID, '10.9.9.10', '00:11:22:33:44:56'),
                ],
            }]}},
        )

        yield objects

        objects.delete_many({'public_id': {'$in': [SUBNET_OBJECT_ID]}})
        types.delete_many({'public_id': {'$in': [SUBNET_TYPE_ID]}})

    @staticmethod
    def _rows(rest_api, query: str = '') -> list[dict[str, Any]]:
        """GETs the picker and returns its rows"""
        return rest_api.get(f'{ASSIGNABLE_URL}{query}').get_json()['rows']

    def test_only_the_ports_own_object_is_offered(self, rest_api) -> None:
        """A port and the interface it carries are two descriptions of the same device"""
        object_ids = {row[AssignableInterfaceKey.INTERFACE_OBJECT_ID.value]
                      for row in self._rows(rest_api)}

        assert object_ids == {SWITCH_OBJECT_ID}

    def test_a_foreign_objects_rows_are_never_offered(self, rest_api) -> None:
        """
        The host carries two perfectly good interface rows and none of them may appear

        Offering one would promise the 400 the create route answers with.
        """
        object_ids = {row[AssignableInterfaceKey.INTERFACE_OBJECT_ID.value]
                      for row in self._rows(rest_api)}

        assert HOST_OBJECT_ID not in object_ids

    def test_a_scope_argument_cannot_widen_it(self, rest_api) -> None:
        """
        The `?all_objects=true` argument is gone, not ignored-but-honoured

        A client that still sends it gets the port's own object, the same as one that does not.
        """
        assert self._rows(rest_api, '?all_objects=true') == self._rows(rest_api)

    def test_a_row_carries_the_create_payload(self, rest_api) -> None:
        """The point of the picker: posting a selected row back is a copy, not a translation"""
        row = self._rows(rest_api)[0]

        response = rest_api.post(
            f'{PORTS_URL}/{PORT_ID}/interface_links/',
            json={
                'interface_object_id': row[AssignableInterfaceKey.INTERFACE_OBJECT_ID.value],
                'interface_section_id': row[AssignableInterfaceKey.INTERFACE_SECTION_ID.value],
                'interface_multi_data_id': row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value],
                'relation_type': InterfaceRelationType.PHYSICAL.value,
            },
        )

        assert response.status_code == HTTPStatus.CREATED

    def test_a_row_carries_the_resolved_values(self, rest_api) -> None:
        """IP and MAC come from the interface, which is the single source for both"""
        row = self._rows(rest_api)[0]

        assert row[AssignableInterfaceKey.IP.value] == '10.9.9.9'
        assert row[AssignableInterfaceKey.MAC.value] == '00:11:22:33:44:55'
        assert row[AssignableInterfaceKey.OBJECT_INFO.value][
            AssignableInterfaceObjectKey.PUBLIC_ID.value] == SWITCH_OBJECT_ID

    def test_a_linked_row_drops_out(self, rest_api) -> None:
        """Offering it would promise the 400 the unique index answers with"""
        row = self._rows(rest_api)[0]
        linked_id = row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value]
        _create(rest_api, object_id=SWITCH_OBJECT_ID, multi_data_id=linked_id)

        remaining = self._rows(rest_api)

        assert linked_id not in [
            row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value] for row in remaining
        ]

    def test_another_ports_link_does_not_exclude_a_row(self, rest_api) -> None:
        """
        Several ports of one object may share an interface, so another port's link excludes nothing

        This is the half of the N:M relation that survives the same-object rule, and the one a bonded
        interface reached over two physical ports depends on.
        """
        _create(rest_api, port_id=OTHER_PORT_ID, object_id=SWITCH_OBJECT_ID, multi_data_id=ROW_ID)

        offered = [row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value]
                   for row in self._rows(rest_api)]

        assert ROW_ID in offered

    def test_the_subnet_is_resolved(self, rest_api, _picker_state,
                                    database_manager: MongoDatabaseManager, database_name: str) -> None:
        """A reference is a number on the row; the picker shows the network's name"""
        types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
        types.insert_one(_type_doc(SUBNET_TYPE_ID))
        subnet = _object_doc(SUBNET_OBJECT_ID, SUBNET_TYPE_ID)
        subnet['fields'] = [{'name': 'dg-name', 'value': SUBNET_NAME, 'type': FieldType.TEXT.value}]
        _picker_state.insert_one(subnet)
        _picker_state.update_one(
            {'public_id': SWITCH_OBJECT_ID},
            {'$push': {'multi_data_sections.0.values.0.data': {
                'name': InterfaceField.SUBNET.value, 'value': SUBNET_OBJECT_ID, 'type': 'ref'}}},
        )

        row = self._rows(rest_api)[0]

        assert row[AssignableInterfaceKey.SUBNET.value][
            AssignableInterfaceSubnetKey.NAME.value] == SUBNET_NAME

    def test_the_search_narrows(self, rest_api) -> None:
        """?search= matches the addresses, the subnet name and the owning device"""
        page = rest_api.get(f'{ASSIGNABLE_URL}?search=10.9.9.9').get_json()

        assert page['total'] == 1
        assert page['rows'][0][AssignableInterfaceKey.IP.value] == '10.9.9.9'

    def test_the_envelope_is_paginated(self, rest_api) -> None:
        """The shape the IPAM pickers answer with, since these are rows rather than documents"""
        page = rest_api.get(f'{ASSIGNABLE_URL}?page=1&page_size=1').get_json()

        assert (page['page'], page['page_size'], page['total']) == (1, 1, 2)
        assert len(page['rows']) == 1

    def test_a_missing_port_is_a_404(self, rest_api) -> None:
        """The picker answers for a port, so an unknown one is not an empty list"""
        response = rest_api.get(f'{PORTS_URL}/{MISSING_PORT_ID}/assignable_interfaces/')

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_the_owner_acl_is_enforced(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reading a port's picker is reading part of its owner object"""
        monkeypatch.setattr(ObjectsManager, 'get_object', _raiser(AccessDeniedError('nope')))

        assert rest_api.get(ASSIGNABLE_URL).status_code == HTTPStatus.FORBIDDEN

    def test_a_link_read_failure_is_400(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """The exclusion needs the port's links, and a database failure there is recoverable"""
        monkeypatch.setattr(
            PortInterfaceLinksManager,
            'get_links_of_port',
            _raiser(PortInterfaceLinksManagerGetError('boom')),
        )

        assert rest_api.get(ASSIGNABLE_URL).status_code == HTTPStatus.BAD_REQUEST

    def test_an_unexpected_failure_is_500(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Anything the picker did not anticipate is a server fault, never a 400"""
        monkeypatch.setattr(PortInterfaceLinksManager, 'get_links_of_port', _raiser(RuntimeError('boom')))

        assert rest_api.get(ASSIGNABLE_URL).status_code == HTTPStatus.INTERNAL_SERVER_ERROR


class TestTheDanglingReportErrorArms:
    """The repair report has nothing to refuse, so its HTTPException arm needs a forced abort."""

    def test_an_http_exception_keeps_its_own_status(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        The HTTPException arm hands an abort through untouched

        The arm is unreachable in a normal request - nothing inside the try aborts. It exists so an
        abort added later keeps its own status instead of being swallowed by the generic handler below
        and reported as a 500, which is what this pins.
        """
        def _abort(*_args: Any, **_kwargs: Any):
            abort(HTTPStatus.NOT_FOUND, 'forced')

        monkeypatch.setattr(port_interface_link_routes, 'collect_dangling_links', _abort)

        assert rest_api.get(f'{LINKS_URL}/dangling').status_code == HTTPStatus.NOT_FOUND

