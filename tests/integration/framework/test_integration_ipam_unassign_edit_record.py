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
Integration tests for what the two IPAM unassign writes record about the objects they edit

Against a real MongoDB, both writes are checked for the edit record every object edit carries: the
version bump and the edit stamp stored with the change, and the written object handed to ``on_write``
for its change log and webhook. Two properties only a real database can show are pinned here:

* **the supernet detach skips a SUBNET moved in between** - the bulk write's statements re-assert the
  supernet reference, the count comes back short, and the SUBNET that was skipped is neither bumped
  nor handed over, while the others are
* **the SUBNET-side write is a targeted update** - an edit of another part of the owner, stored after
  the owner was read, survives the unassign

Each test seeds its own objects and removes them, so the tests do not depend on each other's order
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import (
    CmdbObject,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    extract_field_value,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    InterfaceField,
    IpamSection,
    IpAddressFamily,
    IpamUnassignMode,
)
from cmdb.framework.object_edit import ObjectWrite, hand_over_object_writes
from cmdb.framework.ipam.supernet_membership import (
    clear_supernet_ref,
    is_detached_by_this_write,
    plan_subnet_detaches,
    unassign_subnets_from_supernet,
)
from cmdb.framework.ipam.subnet_unassign import apply_unassign_to_owners, unassign_ips_from_subnet
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE_ID: int = 9710
SUBNET_TYPE_ID: int = 9711
CARRIER_TYPE_ID: int = 9712

SUPERNET_A_ID: int = 9720
SUPERNET_B_ID: int = 9721
SUBNET_1_ID: int = 9722
SUBNET_2_ID: int = 9723
CARRIER_ID: int = 9724

SUBNET_1_RANGE: str = '10.71.0.0/16'
SUBNET_2_RANGE: str = '10.72.0.0/16'
CARRIER_IP: str = '10.71.0.5'

START_VERSION: str = '1.0.0'
PATCHED_VERSION: str = '1.0.1'
EDITOR_ID: int = 88
HOSTNAME_FIELD: str = 'dg-name'

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [SUPERNET_A_ID, SUPERNET_B_ID, SUBNET_1_ID, SUBNET_2_ID, CARRIER_ID]


class _User:
    """A stand-in CmdbUser: the ACL reads `group_id`, the edit stamp reads `public_id`."""

    def __init__(self) -> None:
        self.group_id: int = 1
        self.public_id: int = EDITOR_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _supernet_doc(public_id: int, cidr: str) -> dict[str, Any]:
    """A SUPERNET object."""
    return make_object_doc(public_id, SUPERNET_TYPE_ID, [
        make_field(SupernetField.NAME, f'edit-sn-{public_id}'),
        make_field(SupernetField.TYPE, IpAddressFamily.IPV4),
        make_field(SupernetField.NETWORK_RANGE, cidr),
    ])


def _subnet_doc(public_id: int, cidr: str) -> dict[str, Any]:
    """A SUBNET assigned to SUPERNET_A."""
    return make_object_doc(public_id, SUBNET_TYPE_ID, [
        make_field(SubnetField.NAME, f'edit-sub-{public_id}'),
        make_field(SubnetField.TYPE, IpAddressFamily.IPV4),
        make_field(SubnetField.NETWORK_RANGE, cidr),
        make_field(SubnetField.PARENT_SUPERNET, SUPERNET_A_ID),
    ])


def _carrier_doc() -> dict[str, Any]:
    """An interface carrier with one row in SUBNET_1."""
    return make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [make_field(HOSTNAME_FIELD, 'edit-host')], mds=[{
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
            make_field(InterfaceField.SUBNET, SUBNET_1_ID),
            make_field(InterfaceField.IP, CARRIER_IP),
            make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
        ]}],
    }])


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Seeds two supernets, two subnets of SUPERNET_A and one carrier; removes them afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'it-edit-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'it-edit-subnet', SpecialType.SUBNET),
        make_type_doc(CARRIER_TYPE_ID, 'it-edit-carrier', None),
    ])
    objects.insert_many([
        _supernet_doc(SUPERNET_A_ID, '10.64.0.0/10'),
        _supernet_doc(SUPERNET_B_ID, '172.20.0.0/14'),
        _subnet_doc(SUBNET_1_ID, SUBNET_1_RANGE),
        _subnet_doc(SUBNET_2_ID, SUBNET_2_RANGE),
        _carrier_doc(),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': OBJECT_IDS}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """Provides an ObjectsManager wired to the test database."""
    return ObjectsManager(database_manager)


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """Provides a TypesManager wired to the test database."""
    return TypesManager(database_manager)


def _stored(objects_manager: ObjectsManager, public_id: int) -> dict[str, Any]:
    """The object as stored now."""
    return objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID: public_id}, as_dict=True)[0]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 supernet detach                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_detach_stores_the_version_bump_and_edit_stamp_with_the_change(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Every detached SUBNET is bumped and stamped in the same write that clears its reference."""
    unassign_subnets_from_supernet(
        objects_manager, types_manager, SUPERNET_A_ID, [SUBNET_1_ID, SUBNET_2_ID], request_user=_User(),
    )

    for subnet_id in (SUBNET_1_ID, SUBNET_2_ID):
        stored = _stored(objects_manager, subnet_id)
        assert extract_field_value(stored, SubnetField.PARENT_SUPERNET) is None
        assert stored[CmdbObjectKey.VERSION] == PATCHED_VERSION
        assert stored[CmdbObjectKey.EDITOR_ID] == EDITOR_ID
        assert stored[CmdbObjectKey.LAST_EDIT_TIME] is not None


def test_the_detach_hands_every_detached_subnet_to_on_write(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """on_write gets each SUBNET's before (1.0.0, assigned) and after (1.0.1, detached) state."""
    received: list[ObjectWrite] = []

    unassign_subnets_from_supernet(
        objects_manager, types_manager, SUPERNET_A_ID, [SUBNET_1_ID, SUBNET_2_ID],
        request_user=_User(), on_write=received.append,
    )

    assert sorted(write.after.get_public_id() for write in received) == [SUBNET_1_ID, SUBNET_2_ID]
    for write in received:
        assert write.before.version == START_VERSION
        assert write.after.version == PATCHED_VERSION
        assert write.after.get_value(SubnetField.PARENT_SUPERNET) is None


def test_a_subnet_moved_in_between_is_skipped_and_not_handed_over(
    objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The race the re-asserting filter exists for, run for real

    The plan is taken from SUBNET_1 and SUBNET_2 as assigned to SUPERNET_A; SUBNET_2 is then moved to
    SUPERNET_B before the write. The write detaches SUBNET_1 only, SUBNET_2 keeps its new supernet and
    its version, and only SUBNET_1 reaches on_write.
    """
    docs = [_stored(objects_manager, SUBNET_1_ID), _stored(objects_manager, SUBNET_2_ID)]
    plans = plan_subnet_detaches(docs, SUPERNET_A_ID)

    database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_2_ID, 'fields.name': SubnetField.PARENT_SUPERNET.value},
        {'$set': {'fields.$.value': SUPERNET_B_ID}},
    )

    modified = clear_supernet_ref(objects_manager, plans, SUPERNET_A_ID, _User())
    received: list[ObjectWrite] = []
    hand_over_object_writes(objects_manager, plans, received.append, is_written=is_detached_by_this_write)

    assert modified == 1
    moved = _stored(objects_manager, SUBNET_2_ID)
    assert extract_field_value(moved, SubnetField.PARENT_SUPERNET) == SUPERNET_B_ID
    assert moved[CmdbObjectKey.VERSION] == START_VERSION
    assert [write.after.get_public_id() for write in received] == [SUBNET_1_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                SUBNET-side unassign                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_owner_write_stores_the_version_bump_and_edit_stamp(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The owner's interface row is detached, and the owner is bumped and stamped with it."""
    received: list[ObjectWrite] = []

    unassign_ips_from_subnet(
        objects_manager, types_manager, SUBNET_1_ID, [CARRIER_IP], _User(), on_write=received.append,
    )

    stored = _stored(objects_manager, CARRIER_ID)
    row = stored[CmdbObjectKey.MULTI_DATA_SECTIONS][0][CmdbObjectMdsKey.VALUES][0]
    assert extract_field_value({CmdbObjectKey.FIELDS: row[CmdbObjectMdsRowKey.DATA]}, InterfaceField.SUBNET) is None
    assert stored[CmdbObjectKey.VERSION] == PATCHED_VERSION
    assert stored[CmdbObjectKey.EDITOR_ID] == EDITOR_ID
    assert [write.after.version for write in received] == [PATCHED_VERSION]


def test_an_owner_edit_stored_after_the_read_survives_the_unassign(
    objects_manager: ObjectsManager, database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """
    The unassign writes the owner's sections, version and stamp - not a copy of the whole owner

    The owner is read, then its hostname is changed in the database, then the unassign runs from the
    stale read. A full-document write would put the old hostname back; the targeted one leaves it.
    """
    stale_owner = _stored(objects_manager, CARRIER_ID)

    database_manager.get_collection(CmdbObject.COLLECTION, database_name).update_one(
        {CmdbObjectKey.PUBLIC_ID: CARRIER_ID, 'fields.name': HOSTNAME_FIELD},
        {'$set': {'fields.$.value': 'renamed-meanwhile'}},
    )

    apply_unassign_to_owners(
        objects_manager, [stale_owner], SUBNET_1_ID, {CARRIER_IP}, _User(), IpamUnassignMode.REFERENCE,
    )

    stored = _stored(objects_manager, CARRIER_ID)
    assert extract_field_value(stored, HOSTNAME_FIELD) == 'renamed-meanwhile'
    assert stored[CmdbObjectKey.VERSION] == PATCHED_VERSION
