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
Integration tests for the CmdbPort collection and its manager against a real MongoDB

Two things only a real database can show. First, that the declared unique index really refuses a
second port of the same name on the same face - and, just as importantly, that it does NOT refuse a
patch panel's front 1 alongside its rear 1, which a unique (object_id, name) index would have. Second,
that a real PortsManager round-trips a port through the model.

Note the fixture builds the model's declared indexes itself. The test database is never taken through
CollectionValidator (conftest drops the database and seeds users, nothing more), so its collections are
created implicitly by the first write and carry no index but '_id_'. Building them here is what the
application does at startup, and without it the uniqueness assertions below would silently pass on a
collection that has no constraint at all
"""
from datetime import datetime, timezone
from typing import Any

from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import DuplicateKeyError

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.object_model import CmdbObject
from cmdb.errors.database import DocumentInsertError
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.framework.port.cascade import delete_ports_of_object
from cmdb.models.type_model import CmdbType, TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_helper
from cmdb.models.port_model import CmdbPort, PortKey, PortSide
from tests.utils.ipam_doc_builders import make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #
# Several tests take the 'ports' fixture purely for its side effect - it builds the declared indexes
# and clears the collection - and never touch the handle it yields
# pylint: disable=unused-argument
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 47101
OTHER_OBJECT_ID: int = 47102
PANEL_OBJECT_ID: int = 47103

PORT_IDS: list[int] = [47201, 47202, 47203, 47204, 47205]
OBJECT_IDS: list[int] = [OBJECT_ID, OTHER_OBJECT_ID, PANEL_OBJECT_ID]

PORT_NAME: str = '1'


def _port_doc(
        public_id: int,
        object_id: int,
        name: str = PORT_NAME,
        side: str = PortSide.SINGLE.value,
        **overrides: Any) -> dict[str, Any]:
    """Builds a stored CmdbPort document"""
    doc: dict[str, Any] = {
        PortKey.PUBLIC_ID.value: public_id,
        PortKey.OBJECT_ID.value: object_id,
        PortKey.NAME.value: name,
        PortKey.SIDE.value: side,
        PortKey.PORT_NUMBER.value: None,
        PortKey.STATUS.value: None,
        PortKey.PORT_TYPE.value: None,
        PortKey.SPEED.value: None,
        PortKey.DESCRIPTION.value: None,
        PortKey.AUTHOR_ID.value: 1,
        PortKey.CREATION_TIME.value: datetime.now(timezone.utc),
        PortKey.LAST_EDIT_TIME.value: None,
    }
    doc.update(overrides)

    return doc


@pytest.fixture(name='ports')
def fixture_ports(database_manager: MongoDatabaseManager, database_name: str):
    """
    Gives the raw collection with the model's declared indexes built, cleared around each test

    The index build is what CollectionValidator does at application startup; the test database never
    goes through it (see the module docstring), so it happens here instead.
    """
    collection = database_manager.get_collection(CmdbPort.COLLECTION, database_name)
    collection.delete_many({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})
    database_manager.create_indexes(CmdbPort.COLLECTION, database_name, CmdbPort.get_index_keys())

    yield collection

    collection.delete_many({PortKey.OBJECT_ID.value: {'$in': OBJECT_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> PortsManager:
    """A real PortsManager backed by the test database"""
    return PortsManager(database_manager)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the unique index                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_declared_index_is_really_unique(ports) -> None:
    """
    The model's declaration really produces a unique index

    Guards against the declaration drifting to non-unique: nothing else in the codebase would notice,
    because index reconciliation is name-based and never compares options.
    """
    assert ports.index_information()['object_side_name'].get('unique') is True


def test_the_ordering_index_is_built(ports) -> None:
    """The (object_id, port_number) index is what the ports list is read through"""
    assert 'object_port_number' in ports.index_information()


def test_a_duplicate_name_on_the_same_face_is_refused(ports) -> None:
    """
    A port name identifies a port within one face, enforced where it cannot be raced

    The create route will pre-check this for a readable error, but two concurrent requests would both
    pass that pre-check - only the index stops the second write.
    """
    ports.insert_one(_port_doc(PORT_IDS[0], OBJECT_ID))

    with pytest.raises(DuplicateKeyError):
        ports.insert_one(_port_doc(PORT_IDS[1], OBJECT_ID))


def test_a_patch_panel_may_carry_the_same_name_front_and_rear(ports) -> None:
    """
    The reason 'side' is part of the unique key

    A panel's front 1 and rear 1 are two different ports. A unique (object_id, name) index would have
    made every patch panel unbuildable, which is the mistake this test exists to catch.
    """
    ports.insert_one(_port_doc(PORT_IDS[0], PANEL_OBJECT_ID, side=PortSide.FRONT.value))
    ports.insert_one(_port_doc(PORT_IDS[1], PANEL_OBJECT_ID, side=PortSide.REAR.value))

    assert ports.count_documents({PortKey.OBJECT_ID.value: PANEL_OBJECT_ID}) == 2


def test_the_same_name_on_another_object_is_allowed(ports) -> None:
    """Port names are unique per object, not globally - every switch has a port '1'"""
    ports.insert_one(_port_doc(PORT_IDS[0], OBJECT_ID))
    ports.insert_one(_port_doc(PORT_IDS[1], OTHER_OBJECT_ID))

    assert ports.count_documents({PortKey.NAME.value: PORT_NAME}) == 2


def test_a_duplicate_reports_itself_as_a_duplicate_through_the_manager(
        ports, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    A refused port must fail as a duplicate, not as ten exhausted public_id retries

    dbm.insert retries a duplicate public_id, and until updater_20260902's fix it retried ANY
    duplicate-key error - so a duplicate port name would have burned ten public_ids and blamed the
    wrong index.
    """
    ports.insert_one(_port_doc(PORT_IDS[0], OBJECT_ID))

    before: int = database_manager.get_next_public_id(CmdbPort.COLLECTION, database_name)

    with pytest.raises(DocumentInsertError) as raised:
        database_manager.insert(CmdbPort.COLLECTION, database_name, {
            PortKey.OBJECT_ID.value: OBJECT_ID,
            PortKey.NAME.value: PORT_NAME,
            PortKey.SIDE.value: PortSide.SINGLE.value,
        })

    after: int = database_manager.get_next_public_id(CmdbPort.COLLECTION, database_name)

    assert 'Duplicate key error' in str(raised.value)
    assert after - before == 1

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    the manager                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_manager_round_trips_a_port(ports, manager: PortsManager) -> None:
    """A port inserted through the manager comes back as a CmdbPort with its values intact"""
    new_id: int = manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='Gi0/1', port_number=1))

    stored = manager.get_item(new_id)

    assert isinstance(stored, CmdbPort)
    assert stored.object_id == OBJECT_ID
    assert stored.name == 'Gi0/1'
    assert stored.port_number == 1
    assert stored.side == PortSide.SINGLE.value


def test_the_manager_reads_the_ports_of_one_object(ports, manager: PortsManager) -> None:
    """The ports of an object are what every read of this collection asks for"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))
    manager.insert_item(_port_doc(PORT_IDS[1], OBJECT_ID, name='2'))
    manager.insert_item(_port_doc(PORT_IDS[2], OTHER_OBJECT_ID, name='1'))

    found = manager.find(criteria={PortKey.OBJECT_ID.value: OBJECT_ID})

    assert sorted(port[PortKey.NAME.value] for port in found) == ['1', '2']


def test_a_port_stored_without_a_side_reads_as_single(ports, manager: PortsManager) -> None:
    """A document written before/without the key must not land in its own namespace"""
    doc = _port_doc(PORT_IDS[0], OBJECT_ID)
    del doc[PortKey.SIDE.value]
    ports.insert_one(doc)

    assert manager.get_item(PORT_IDS[0]).side == PortSide.SINGLE.value


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the delete cascade                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_cascade_removes_every_port_of_the_object(ports, manager: PortsManager) -> None:
    """
    Nothing else removes a port when its owner goes: it lives outside the object's document

    Asserted against stored rows rather than a mocked call, because the filter is what matters - a
    cascade with a slightly wrong one either leaves rows behind or takes another object's.
    """
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))
    manager.insert_item(_port_doc(PORT_IDS[1], OBJECT_ID, name='2'))

    removed: int = delete_ports_of_object(manager, {'public_id': OBJECT_ID})

    assert removed == 2
    assert ports.count_documents({PortKey.OBJECT_ID.value: OBJECT_ID}) == 0


def test_the_cascade_leaves_other_objects_alone(ports, manager: PortsManager) -> None:
    """The scope is the deleted object, and the (object_id, ...) index is what makes it cheap"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))
    manager.insert_item(_port_doc(PORT_IDS[1], OTHER_OBJECT_ID, name='1'))

    delete_ports_of_object(manager, {'public_id': OBJECT_ID})

    assert ports.count_documents({PortKey.OBJECT_ID.value: OTHER_OBJECT_ID}) == 1


def test_the_cascade_is_a_no_op_for_an_object_without_ports(ports, manager: PortsManager) -> None:
    """The common case on every object deletion"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))

    assert delete_ports_of_object(manager, {'public_id': OTHER_OBJECT_ID}) == 0
    assert ports.count_documents({PortKey.OBJECT_ID.value: OBJECT_ID}) == 1


def test_the_cascade_frees_the_port_names_again(ports, manager: PortsManager) -> None:
    """
    After the cascade the same names may be used again on a new object

    Guards against a cascade that only marks rows instead of removing them - the unique index would
    then refuse the next object that reuses a name.
    """
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name=PORT_NAME))

    delete_ports_of_object(manager, {'public_id': OBJECT_ID})

    ports.insert_one(_port_doc(PORT_IDS[1], OBJECT_ID, name=PORT_NAME))

    assert ports.count_documents({PortKey.NAME.value: PORT_NAME}) == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                             the uses_ports guard, measured against real port documents                               #
# -------------------------------------------------------------------------------------------------------------------- #
TYPE_ID: int = 47301
OTHER_TYPE_ID: int = 47302
TYPES_HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'


def _uses_ports_type(public_id: int, uses_ports: bool) -> CmdbType:
    """A CmdbType instance carrying the flag, built from a minimal document"""
    doc = make_type_doc(public_id, f'integration-port-type-{public_id}')
    doc[TypeSchemaKey.USES_PORTS.value] = uses_ports

    return CmdbType.from_data(doc)


@pytest.fixture(name='typed_objects')
def fixture_typed_objects(ports, database_manager: MongoDatabaseManager, database_name: str):
    """
    Seeds two CmdbObjects of one Type and one of another, so the scoping can be measured

    The guard resolves a Type's objects from the objects collection and then counts the ports naming
    them, which is exactly the part a mocked test cannot show.
    """
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
    objects.insert_many([
        make_object_doc(OBJECT_ID, TYPE_ID, []),
        make_object_doc(OTHER_OBJECT_ID, TYPE_ID, []),
        make_object_doc(PANEL_OBJECT_ID, OTHER_TYPE_ID, []),
    ])

    real_provider = types_helper.ManagerProvider.get_manager
    managers = {
        ManagerType.OBJECTS: ObjectsManager(database_manager, database_name),
        ManagerType.PORTS: PortsManager(database_manager, database_name),
    }

    with patch(f'{TYPES_HELPER_PATH}.ManagerProvider.get_manager',
               side_effect=lambda manager_type, _user: managers.get(manager_type,
                                                                    MagicMock(name=str(manager_type)))):
        yield ports

    del real_provider
    objects.delete_many({'public_id': {'$in': OBJECT_IDS}})


def test_the_usage_counts_the_types_own_ports(typed_objects, manager: PortsManager) -> None:
    """Two ports on one object plus one on another object of the same Type"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))
    manager.insert_item(_port_doc(PORT_IDS[1], OBJECT_ID, name='2'))
    manager.insert_item(_port_doc(PORT_IDS[2], OTHER_OBJECT_ID, name='1'))

    usage = types_helper.get_port_usage_of_type(MagicMock(), _uses_ports_type(TYPE_ID, True))

    assert usage['port_count'] == 3
    assert usage['object_count'] == 2


def test_the_usage_ignores_another_types_ports(typed_objects, manager: PortsManager) -> None:
    """
    The scoping the guard depends on

    A filter that forgot to narrow to the Type's own object ids would make the flag impossible to
    clear anywhere in the installation.
    """
    manager.insert_item(_port_doc(PORT_IDS[0], PANEL_OBJECT_ID, name='1'))

    usage = types_helper.get_port_usage_of_type(MagicMock(), _uses_ports_type(TYPE_ID, True))

    assert usage['port_count'] == 0


def test_the_blocker_refuses_the_transition_while_ports_exist(typed_objects,
                                                             manager: PortsManager) -> None:
    """End to end against stored documents"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))

    blocker = types_helper.uses_ports_change_blocker(
        MagicMock(), _uses_ports_type(TYPE_ID, True), _uses_ports_type(TYPE_ID, False),
    )

    assert blocker is not None
    assert '1 Port(s)' in blocker


def test_the_blocker_allows_the_transition_once_the_ports_are_gone(typed_objects,
                                                                  manager: PortsManager) -> None:
    """The documented way out"""
    manager.insert_item(_port_doc(PORT_IDS[0], OBJECT_ID, name='1'))
    delete_ports_of_object(manager, {'public_id': OBJECT_ID})

    assert types_helper.uses_ports_change_blocker(
        MagicMock(), _uses_ports_type(TYPE_ID, True), _uses_ports_type(TYPE_ID, False),
    ) is None
