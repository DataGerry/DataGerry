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

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from cmdb.models.port_interface_link_model import (
    CmdbPortInterfaceLink,
    InterfaceRelationType,
    PortInterfaceLinkKey,
)
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.models.type_model import CmdbType, FieldType, SectionType
from cmdb.manager import ObjectsManager
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
from cmdb.interface.rest_api.routes.port_routes.port_interface_link_constants import INTERFACE_ROW_KEY
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

NAME_FIELD: str = 'dg-name'

ALL_TYPE_IDS: list[int] = [PORT_TYPE_ID, HOST_TYPE_ID]
ALL_OBJECT_IDS: list[int] = [SWITCH_OBJECT_ID, HOST_OBJECT_ID]
ALL_PORT_IDS: list[int] = [PORT_ID, OTHER_PORT_ID]


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """
    Licenses IPAM so the gated link surface is reachable

    Port Connectivity is gated behind LicenseFeature.IPAM by decision D6. That the gate really blocks
    the surface is asserted in tests/functional/license/.
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


def _interface_row(multi_data_id: int, ip: str) -> dict[str, Any]:
    """One dg-ipam-interface MDS row."""
    return {
        'multi_data_id': multi_data_id,
        'data': [{'name': InterfaceField.IP.value, 'value': ip, 'type': FieldType.TEXT.value}],
    }


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
        object_id: int = HOST_OBJECT_ID,
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
    """Seeds the types, the switch with its ports and the host with two interface rows."""
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
        _object_doc(SWITCH_OBJECT_ID, PORT_TYPE_ID),
        _object_doc(HOST_OBJECT_ID, HOST_TYPE_ID, [
            _interface_row(ROW_ID, '10.0.0.1'), _interface_row(OTHER_ROW_ID, '10.0.0.2'),
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
        {'public_id': HOST_OBJECT_ID},
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
            'interface_object_id': HOST_OBJECT_ID, 'interface_multi_data_id': ROW_ID,
        })

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_missing_port_is_a_404(self, rest_api) -> None:
        """The port is the link's hard reference"""
        assert _create(rest_api, port_id=MISSING_PORT_ID).status_code == HTTPStatus.NOT_FOUND

    def test_a_missing_interface_object_is_a_404(self, rest_api) -> None:
        """Nothing to link to"""
        assert _create(rest_api, object_id=MISSING_OBJECT_ID).status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                        READ                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadLink:
    """GET the single link and the per-port list, both resolving the interface row."""

    def test_a_read_resolves_the_live_interface_row(self, rest_api) -> None:
        """
        The point of the link: the interface's values come from the row, never from a copy

        The IP the caller sees is the one stored on the object, so editing the interface is visible
        immediately and no second truth exists.
        """
        new_id: int = _created_id(_create(rest_api))

        link = rest_api.get(f'{LINKS_URL}/{new_id}').get_json()['result']

        assert link[INTERFACE_ROW_KEY]['data'][0]['value'] == '10.0.0.1'

    def test_a_missing_link_is_a_404(self, rest_api) -> None:
        """Addressing a row that does not exist"""
        assert rest_api.get(f'{LINKS_URL}/{MISSING_LINK_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_the_port_list_returns_every_link(self, rest_api) -> None:
        """A port's interface list, which is what the ports panel shows"""
        _create(rest_api)
        _create(rest_api, multi_data_id=OTHER_ROW_ID, relation_type=InterfaceRelationType.VLAN.value)

        links = rest_api.get(f'{PORTS_URL}/{PORT_ID}/interface_links/').get_json()

        assert len(links) == 2
        assert {link[INTERFACE_ROW_KEY]['data'][0]['value'] for link in links} == {
            '10.0.0.1', '10.0.0.2',
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
        """
        new_id: int = _created_id(_create(rest_api))
        seeded.delete_one({'public_id': HOST_OBJECT_ID})

        assert rest_api.get(f'{LINKS_URL}/{new_id}').status_code == HTTPStatus.OK
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
            'interface_object_id': SWITCH_OBJECT_ID,
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
