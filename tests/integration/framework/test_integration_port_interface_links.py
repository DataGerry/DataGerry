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
Integration tests for the CmdbPortInterfaceLink collection against a real MongoDB

Three things only a real database can show:

  1. the unique index really enforces ONE link per port/interface pair - and, just as importantly, that
     it does NOT key on relation_type, so re-linking the same pair under a different type is still
     refused. A unit test asserting the declaration would pass either way
  2. a link **survives an unrelated object write**. The object is updated the way the application
     updates one, and the link still resolves - which is the whole premise of addressing an MDS row
  3. a link goes dangling **without erroring** when its row is removed, and the report finds it

Note the fixture builds the model's declared indexes itself. The test database is never taken through
CollectionValidator (conftest drops the database and seeds users, nothing more), so its collections are
created implicitly by the first write and carry no index but '_id_'
"""
from datetime import datetime, timezone
from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.models.object_model import CmdbObject
from cmdb.models.port_interface_link_model import (
    AssignableInterfaceKey,
    AssignableInterfaceSubnetKey,
    CmdbPortInterfaceLink,
    InterfaceRelationType,
    PortInterfaceLinkKey,
    LINK_IDENTITY_INDEX_NAME,
)
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.framework.port.assignable_interfaces import (
    build_assignable_interface_rows,
    build_subnet_lookup,
    referenced_subnet_ids,
)
from cmdb.framework.port.cascade import delete_interface_links_of_ports
from cmdb.framework.port.interface_links import collect_dangling_links, resolve_link_row
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests take the 'links' fixture purely for its side effect - it builds the declared indexes
# and clears the collection - and never touch the handle it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

PORT_ID: int = 49101
OTHER_PORT_ID: int = 49102
PORT_IDS: list[int] = [PORT_ID, OTHER_PORT_ID]

HOST_OBJECT_ID: int = 49201
LINK_IDS: list[int] = [49301, 49302, 49303]

ROW_ID: int = 1
OTHER_ROW_ID: int = 2

ROW_IP: str = '10.0.0.1'
OTHER_ROW_IP: str = '10.0.0.2'
ROW_MAC: str = '00:1A:2B:3C:4D:5E'
OTHER_ROW_MAC: str = '00:1A:2B:3C:4D:5F'


def _interface_row(multi_data_id: int, ip: str, mac: str = ROW_MAC) -> dict[str, Any]:
    """
    One dg-ipam-interface MDS row, carrying both addresses the section declares

    IP and MAC are the two values the interface is the single source of truth for - neither is copied
    onto the port - so a row holding only the IP would not prove that a resolved read hands back
    everything the interface stores.
    """
    return {
        'multi_data_id': multi_data_id,
        'data': [
            {'name': InterfaceField.IP.value, 'value': ip, 'type': 'text'},
            {'name': InterfaceField.MAC.value, 'value': mac, 'type': 'text'},
        ],
    }


def _row_value(interface_row: dict[str, Any], field_name: str) -> Any:
    """Reads one field value out of an interface row, by name rather than by position."""
    return next(
        (entry.get('value') for entry in interface_row.get('data', []) if entry.get('name') == field_name),
        None,
    )


def _host_doc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A CmdbObject carrying the given interface rows."""
    return {
        'public_id': HOST_OBJECT_ID,
        'type_id': 49001,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'fields': [{'name': 'dg-name', 'value': 'host', 'type': 'text'}],
        'multi_data_sections': [{
            'section_id': IpamSection.INTERFACE.value,
            'highest_id': max(row['multi_data_id'] for row in rows) if rows else 0,
            'values': rows,
        }],
    }


def _link_doc(
        public_id: int,
        port_id: int = PORT_ID,
        multi_data_id: int = ROW_ID,
        relation_type: str = InterfaceRelationType.PHYSICAL.value) -> dict[str, Any]:
    """A stored CmdbPortInterfaceLink document."""
    return {
        PortInterfaceLinkKey.PUBLIC_ID.value: public_id,
        PortInterfaceLinkKey.PORT_ID.value: port_id,
        PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value: HOST_OBJECT_ID,
        PortInterfaceLinkKey.INTERFACE_SECTION_ID.value: IpamSection.INTERFACE.value,
        PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: multi_data_id,
        PortInterfaceLinkKey.RELATION_TYPE.value: relation_type,
        PortInterfaceLinkKey.AUTHOR_ID.value: 1,
        PortInterfaceLinkKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortInterfaceLinkKey.LAST_EDIT_TIME.value: None,
    }


@pytest.fixture(name='links')
def fixture_links(database_manager: MongoDatabaseManager, database_name: str):
    """
    Gives the raw collection with the model's declared indexes built, cleared around each test

    The index build is what CollectionValidator does at application startup; the test database never
    goes through it, so without it the uniqueness assertions would pass on a collection with no
    constraint at all.
    """
    collection = database_manager.get_collection(CmdbPortInterfaceLink.COLLECTION, database_name)
    collection.delete_many({PortInterfaceLinkKey.PORT_ID.value: {'$in': PORT_IDS}})
    database_manager.create_indexes(
        CmdbPortInterfaceLink.COLLECTION, database_name, CmdbPortInterfaceLink.get_index_keys(),
    )

    yield collection

    collection.delete_many({PortInterfaceLinkKey.PORT_ID.value: {'$in': PORT_IDS}})


@pytest.fixture(name='host')
def fixture_host(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the CmdbObject holding two interface rows, cleared around each test."""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': HOST_OBJECT_ID})
    objects.insert_one(_host_doc([_interface_row(ROW_ID, ROW_IP),
                                  _interface_row(OTHER_ROW_ID, OTHER_ROW_IP, OTHER_ROW_MAC)]))

    yield objects

    objects.delete_many({'public_id': HOST_OBJECT_ID})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> PortInterfaceLinksManager:
    """A real PortInterfaceLinksManager backed by the test database"""
    return PortInterfaceLinksManager(database_manager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          one link per port/interface pair                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_identity_index_is_really_unique(links) -> None:
    """
    The declaration really produces a unique index

    Index reconciliation is name-based and never compares options, so a declaration that silently
    stopped being unique would change nothing anywhere else in the codebase.
    """
    assert links.index_information()[LINK_IDENTITY_INDEX_NAME].get('unique') is True


def test_the_same_pair_twice_is_refused(links) -> None:
    """One link per port/interface pair"""
    links.insert_one(_link_doc(LINK_IDS[0]))

    with pytest.raises(DuplicateKeyError):
        links.insert_one(_link_doc(LINK_IDS[1]))


def test_a_different_relation_type_does_not_make_a_second_link(links) -> None:
    """
    The reason relation_type is NOT part of the index key

    It DESCRIBES the pair rather than identifying it. Keyed on, the same port and the same interface
    row could be linked five times over - once per relation type - which is exactly what 'one link per
    pair' forbids, and no unit test of the declaration would have caught it.
    """
    links.insert_one(_link_doc(LINK_IDS[0], relation_type=InterfaceRelationType.PHYSICAL.value))

    with pytest.raises(DuplicateKeyError):
        links.insert_one(_link_doc(LINK_IDS[1], relation_type=InterfaceRelationType.VLAN.value))


def test_a_second_row_of_the_same_object_is_a_different_link(links) -> None:
    """One port carrying two interfaces of the same peer - the N side of N:M"""
    links.insert_one(_link_doc(LINK_IDS[0], multi_data_id=ROW_ID))
    links.insert_one(_link_doc(LINK_IDS[1], multi_data_id=OTHER_ROW_ID))

    assert links.count_documents({PortInterfaceLinkKey.PORT_ID.value: PORT_ID}) == 2


def test_another_port_may_reach_the_same_interface(links) -> None:
    """A bonded interface reached over two physical ports - the M side"""
    links.insert_one(_link_doc(LINK_IDS[0], port_id=PORT_ID))
    links.insert_one(_link_doc(LINK_IDS[1], port_id=OTHER_PORT_ID))

    assert links.count_documents(
        {PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value: ROW_ID}) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                    the soft reference, against real documents                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_link_survives_an_unrelated_object_write(links, host, manager) -> None:
    """
    The premise of the whole design: addressing a row by id has to survive editing the object

    The object is updated the way the application updates one - a field write that has nothing to do
    with interfaces - and the link still resolves.
    """
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0])))

    host.update_one({'public_id': HOST_OBJECT_ID}, {'$set': {'fields.0.value': 'renamed-host'}})

    stored_link = manager.get_item(LINK_IDS[0], as_dict=True)
    stored_host = host.find_one({'public_id': HOST_OBJECT_ID})

    resolved = resolve_link_row(stored_link, stored_host)

    assert resolved is not None
    assert _row_value(resolved, InterfaceField.IP.value) == ROW_IP
    assert _row_value(resolved, InterfaceField.MAC.value) == ROW_MAC


def test_a_link_survives_another_row_being_removed(links, host, manager) -> None:
    """Removing a DIFFERENT interface row must not disturb this link"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0], multi_data_id=ROW_ID)))

    host.update_one(
        {'public_id': HOST_OBJECT_ID},
        {'$pull': {'multi_data_sections.$[section].values': {'multi_data_id': OTHER_ROW_ID}}},
        array_filters=[{'section.section_id': IpamSection.INTERFACE.value}],
    )

    stored_host = host.find_one({'public_id': HOST_OBJECT_ID})

    assert resolve_link_row(manager.get_item(LINK_IDS[0], as_dict=True), stored_host) is not None


def test_a_link_goes_dangling_without_erroring_when_its_row_is_removed(links, host, manager) -> None:
    """
    The tolerated failure, which is what makes the reference soft

    An MDS row id is not durable - the full PUT does not preserve row ids and the CSV import overwrite
    renumbers them - so this happens without anything touching the port. The link has to stay readable.
    """
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0])))

    host.update_one(
        {'public_id': HOST_OBJECT_ID},
        {'$pull': {'multi_data_sections.$[section].values': {'multi_data_id': ROW_ID}}},
        array_filters=[{'section.section_id': IpamSection.INTERFACE.value}],
    )

    stored_link = manager.get_item(LINK_IDS[0], as_dict=True)
    stored_host = host.find_one({'public_id': HOST_OBJECT_ID})

    assert stored_link is not None
    assert resolve_link_row(stored_link, stored_host) is None


def test_the_report_finds_the_dangling_link_and_nothing_else(links, host, manager) -> None:
    """The repair list, measured against stored documents rather than a stub"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0], multi_data_id=ROW_ID)))
    manager.insert_item(CmdbPortInterfaceLink.from_data(
        _link_doc(LINK_IDS[1], multi_data_id=OTHER_ROW_ID),
    ))

    host.update_one(
        {'public_id': HOST_OBJECT_ID},
        {'$pull': {'multi_data_sections.$[section].values': {'multi_data_id': OTHER_ROW_ID}}},
        array_filters=[{'section.section_id': IpamSection.INTERFACE.value}],
    )

    stored_host = host.find_one({'public_id': HOST_OBJECT_ID})
    dangling = collect_dangling_links(manager.get_all_links(), {HOST_OBJECT_ID: stored_host})

    assert [link[PortInterfaceLinkKey.PUBLIC_ID.value] for link in dangling] == [LINK_IDS[1]]


def test_deleting_the_interface_object_never_cascades(links, host, manager) -> None:
    """
    The strongest form of the soft reference

    Even the object going away leaves the link in place: it is the only record of what the customer
    meant, and removing it silently would destroy that.
    """
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0])))

    host.delete_one({'public_id': HOST_OBJECT_ID})

    assert manager.get_item(LINK_IDS[0], as_dict=True) is not None
    assert collect_dangling_links(manager.get_all_links(), {}) != []


# -------------------------------------------------------------------------------------------------------------------- #
#                                          the port half, which IS hard                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_links_of_deleted_ports_are_removed(links, manager) -> None:
    """A link without its port is a row nothing can reach and nothing can repair"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0], port_id=PORT_ID)))
    manager.insert_item(CmdbPortInterfaceLink.from_data(
        _link_doc(LINK_IDS[1], port_id=OTHER_PORT_ID),
    ))

    assert delete_interface_links_of_ports(manager, [PORT_ID]) == 1
    assert manager.get_links_of_port(PORT_ID) == []
    assert len(manager.get_links_of_port(OTHER_PORT_ID)) == 1


def test_the_pair_may_be_linked_again_after_the_delete(links, manager) -> None:
    """
    Guards against a delete that only marks rows

    The unique index would then refuse the next link between the same port and the same interface.
    """
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0])))
    delete_interface_links_of_ports(manager, [PORT_ID])

    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[1])))

    assert len(manager.get_links_of_port(PORT_ID)) == 1


def test_the_manager_reads_both_directions(links, manager) -> None:
    """A port's interfaces, and the links pointing into one object - the two declared read indexes"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0])))
    manager.insert_item(CmdbPortInterfaceLink.from_data(
        _link_doc(LINK_IDS[1], port_id=OTHER_PORT_ID),
    ))

    assert len(manager.get_links_of_port(PORT_ID)) == 1
    assert len(manager.get_links_of_interface_object(HOST_OBJECT_ID)) == 2
    assert len(manager.get_links_of_ports(PORT_IDS)) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                       THE PICKER, AGAINST THE STORED DOCUMENTS                                       #
# -------------------------------------------------------------------------------------------------------------------- #
# The unit tests hand the builders their documents; what is only observable here is that the rows the
# picker offers are the rows the database actually holds - the exclusion is keyed on links read back
# out of Mongo, and the subnet names come from a real second collection read
SUBNET_OBJECT_ID: int = 49401
SUBNET_NAME: str = 'Office LAN'


def _stored_host(database_manager: MongoDatabaseManager, database_name: str) -> dict[str, Any]:
    """Reads the seeded host document back out of the database"""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)\
        .find_one({'public_id': HOST_OBJECT_ID}, {'_id': 0})


def _offered(host_doc: dict[str, Any], manager: PortInterfaceLinksManager,
             port_id: int = PORT_ID) -> list[dict[str, Any]]:
    """Shapes the rows the picker would offer for one port, with the links read from Mongo"""
    linked_rows = {
        (link[PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value],
         link[PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value])
        for link in manager.get_links_of_port(port_id)
    }

    return build_assignable_interface_rows([host_doc], linked_rows, {}, {}, {})


def test_the_picker_offers_the_stored_rows(links, host, manager,
                                           database_manager: MongoDatabaseManager,
                                           database_name: str) -> None:
    """Every interface row the object really holds is offered, with the values it really stores"""
    rows = _offered(_stored_host(database_manager, database_name), manager)

    assert [row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value] for row in rows] == [ROW_ID, OTHER_ROW_ID]
    assert [row[AssignableInterfaceKey.IP.value] for row in rows] == [ROW_IP, OTHER_ROW_IP]
    assert [row[AssignableInterfaceKey.MAC.value] for row in rows] == [ROW_MAC, OTHER_ROW_MAC]


def test_a_stored_link_removes_its_row_from_the_picker(links, host, manager,
                                                       database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
    """The exclusion is keyed on links read back out of Mongo, not on anything held in memory"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(_link_doc(LINK_IDS[0], multi_data_id=ROW_ID)))

    rows = _offered(_stored_host(database_manager, database_name), manager)

    assert [row[AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value] for row in rows] == [OTHER_ROW_ID]


def test_another_ports_link_leaves_the_row_offered(links, host, manager,
                                                   database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
    """N:M: the same interface row may be reached over several ports, so only THIS port's links exclude"""
    manager.insert_item(CmdbPortInterfaceLink.from_data(
        _link_doc(LINK_IDS[0], port_id=OTHER_PORT_ID, multi_data_id=ROW_ID)))

    rows = _offered(_stored_host(database_manager, database_name), manager)

    assert len(rows) == 2


def test_the_subnet_name_comes_from_the_referenced_object(links, host, manager,
                                                          database_manager: MongoDatabaseManager,
                                                          database_name: str) -> None:
    """The reference resolves through a real second read, and one read covers every row that shares it"""
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.update_many(
        {'public_id': HOST_OBJECT_ID},
        {'$push': {'multi_data_sections.$[section].values.$[].data': {
            'name': InterfaceField.SUBNET.value, 'value': SUBNET_OBJECT_ID, 'type': 'ref'}}},
        array_filters=[{'section.section_id': IpamSection.INTERFACE.value}],
    )
    objects.delete_many({'public_id': SUBNET_OBJECT_ID})
    objects.insert_one({'public_id': SUBNET_OBJECT_ID, 'type_id': 49002, 'active': True,
                        'fields': [{'name': 'dg-name', 'value': SUBNET_NAME, 'type': 'text'}]})

    host_doc = _stored_host(database_manager, database_name)
    subnet_ids = referenced_subnet_ids([host_doc])
    subnet_names = build_subnet_lookup(
        list(objects.find({'public_id': {'$in': subnet_ids}}, {'_id': 0})),
    )
    rows = build_assignable_interface_rows([host_doc], set(), {}, {}, subnet_names)

    objects.delete_many({'public_id': SUBNET_OBJECT_ID})

    assert subnet_ids == [SUBNET_OBJECT_ID]
    assert rows[0][AssignableInterfaceKey.SUBNET.value][
        AssignableInterfaceSubnetKey.NAME.value] == SUBNET_NAME
