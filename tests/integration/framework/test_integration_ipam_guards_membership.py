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
Integration tests for the IPAM write-guard paths against a real MongoDB

Pins the DB-touching behaviour the unit tests only mock: the interface-row batch validation
(the IP-uniqueness collision query with its $elemMatch/$all filter, the self-exclusion pair,
the required-type and type-family rules against real subnet documents), the save-time
enforcement dispatch for an interface carrier, the deletion guards (supernet blocked by
referencing subnets, subnet blocked by VLANs / interface rows, unreferenced objects pass),
and the batch supernet-membership detach (real update_many write, validate-all-or-nothing
rejection leaves the data untouched)
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

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
    VlanField,
    InterfaceField,
    IpamSection,
    IpAddressFamily,
    IpamUnassignKey,
)
from cmdb.framework.ipam.interface_validator import InterfaceErrorCode, validate_interface_rows
from cmdb.framework.ipam.enforcement import (
    DeleteGuardErrorCode,
    enforce_delete_guards,
    enforce_object_invariants,
)
from cmdb.framework.ipam.supernet_membership import unassign_subnets_from_supernet
from cmdb.utils import ValidationErrorKey
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE_ID: int = 9610
SUBNET_TYPE_ID: int = 9611
VLAN_TYPE_ID: int = 9612
CARRIER_TYPE_ID: int = 9613

SUPERNET_A_ID: int = 9620      # referenced by subnets -> delete blocked
SUPERNET_B_ID: int = 9621      # unreferenced -> delete allowed
SUBNET_1_ID: int = 9622        # referenced by vlan + interface row -> delete blocked
SUBNET_2_ID: int = 9623        # unreferenced subnet -> delete allowed
SUBNET_3_ID: int = 9624        # detached by the membership happy-path test
VLAN_ID: int = 9625
CARRIER_1_ID: int = 9626       # owns the colliding interface row
FOREIGN_SUBNET_ID: int = 9999  # never seeded

SUPERNET_A_RANGE: str = '10.0.0.0/8'
SUPERNET_B_RANGE: str = '172.16.0.0/12'
SUBNET_1_RANGE: str = '10.1.0.0/16'
SUBNET_2_RANGE: str = '10.2.0.0/16'
SUBNET_3_RANGE: str = '10.3.0.0/16'

ASSIGNED_IP: str = '10.1.0.5'
FREE_IP: str = '10.1.0.9'

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, VLAN_TYPE_ID, CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [
    SUPERNET_A_ID, SUPERNET_B_ID, SUBNET_1_ID, SUBNET_2_ID, SUBNET_3_ID, VLAN_ID, CARRIER_1_ID,
]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _subnet_doc(public_id: int, name: str, cidr: str, supernet_ref: int | None) -> dict[str, Any]:
    """Builds a SUBNET object doc with an optional parent supernet reference."""
    fields = [
        make_field(SubnetField.NAME, name),
        make_field(SubnetField.TYPE, IpAddressFamily.IPV4),
        make_field(SubnetField.NETWORK_RANGE, cidr),
    ]

    if supernet_ref is not None:
        fields.append(make_field(SubnetField.PARENT_SUPERNET, supernet_ref))

    return make_object_doc(public_id, SUBNET_TYPE_ID, fields)


@pytest.fixture(scope='module', autouse=True)
def _seed_guard_topology(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the supernet / subnet / vlan / carrier topology, cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'it-guard-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'it-guard-subnet', SpecialType.SUBNET),
        make_type_doc(VLAN_TYPE_ID, 'it-guard-vlan', SpecialType.VLAN),
        make_type_doc(CARRIER_TYPE_ID, 'it-guard-carrier', None),
    ])

    objects.insert_many([
        make_object_doc(SUPERNET_A_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'guard-sn-a'),
            make_field(SupernetField.TYPE, IpAddressFamily.IPV4),
            make_field(SupernetField.NETWORK_RANGE, SUPERNET_A_RANGE),
        ]),
        make_object_doc(SUPERNET_B_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'guard-sn-b'),
            make_field(SupernetField.TYPE, IpAddressFamily.IPV4),
            make_field(SupernetField.NETWORK_RANGE, SUPERNET_B_RANGE),
        ]),
        _subnet_doc(SUBNET_1_ID, 'guard-sub-1', SUBNET_1_RANGE, SUPERNET_A_ID),
        _subnet_doc(SUBNET_2_ID, 'guard-sub-2', SUBNET_2_RANGE, None),
        _subnet_doc(SUBNET_3_ID, 'guard-sub-3', SUBNET_3_RANGE, SUPERNET_A_ID),
        make_object_doc(VLAN_ID, VLAN_TYPE_ID, [
            make_field(VlanField.NAME, 'guard-vlan'),
            make_field(VlanField.SUBNET_REF, SUBNET_1_ID),
        ]),
        make_object_doc(CARRIER_1_ID, CARRIER_TYPE_ID, [make_field('dg-name', 'guard-host-1')], mds=[{
            CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
            CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
                make_field(InterfaceField.SUBNET, SUBNET_1_ID),
                make_field(InterfaceField.IP, ASSIGNED_IP),
                make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
            ]}],
        }]),
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


def _codes(errors: list[dict[str, Any]]) -> set[str]:
    """Returns the set of error codes in a structured error list."""
    return {e[ValidationErrorKey.CODE] for e in errors}


# -------------------------------------------------------------------------------------------------------------------- #
#                                        INTERFACE ROW VALIDATION (REAL QUERIES)                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_interface_rows_uniqueness_collision_is_found_by_the_real_query(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A row claiming an IP already stored on another carrier trips the $elemMatch/$all collision query"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_1_ID, ASSIGNED_IP, IpAddressFamily.IPV4),
    ]

    errors = validate_interface_rows(objects_manager, types_manager, rows)

    assert InterfaceErrorCode.IP_DUPLICATE in _codes(errors)


def test_interface_rows_exclusion_pair_spares_the_own_pre_edit_row(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Re-validating the carrier's own stored row with the exclusion pair reports no collision"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_1_ID, ASSIGNED_IP, IpAddressFamily.IPV4),
    ]

    errors = validate_interface_rows(
        objects_manager, types_manager, rows, exclude_object_id=CARRIER_1_ID,
    )

    assert not errors


def test_interface_rows_type_family_mismatch_against_real_subnet(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """An ipv6 token on an IPv4 IP referencing an IPv4 subnet yields two mismatches from real data"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_1_ID, FREE_IP, IpAddressFamily.IPV6),
    ]

    errors = validate_interface_rows(objects_manager, types_manager, rows)

    mismatches = [e for e in errors if e[ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_FAMILY_MISMATCH]
    assert len(mismatches) == 2


def test_interface_rows_missing_type_is_required_for_data_rows(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A data-carrying row without the type token is rejected; an empty placeholder row passes"""
    rows: list[tuple[int, int | None, str | None, str | None]] = [
        (0, SUBNET_1_ID, FREE_IP, None),
        (1, None, None, None),
    ]

    errors = validate_interface_rows(objects_manager, types_manager, rows)

    missing = [e for e in errors if e[ValidationErrorKey.CODE] == InterfaceErrorCode.TYPE_MISSING]
    assert len(missing) == 1


def test_enforce_object_invariants_accepts_a_valid_interface_carrier(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The save-time dispatch validates carrier MDS rows end-to-end: a clean candidate passes"""
    candidate = make_object_doc(CARRIER_1_ID + 100, CARRIER_TYPE_ID, [make_field('dg-name', 'new-host')], mds=[{
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
            make_field(InterfaceField.SUBNET, SUBNET_1_ID),
            make_field(InterfaceField.IP, FREE_IP),
            make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
        ]}],
    }])

    assert not enforce_object_invariants(objects_manager, types_manager, candidate)


def test_enforce_object_invariants_rejects_a_colliding_interface_carrier(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The save-time dispatch surfaces the duplicate-IP collision for a new carrier"""
    candidate = make_object_doc(CARRIER_1_ID + 101, CARRIER_TYPE_ID, [make_field('dg-name', 'dupe-host')], mds=[{
        CmdbObjectMdsKey.SECTION_ID: IpamSection.INTERFACE,
        CmdbObjectMdsKey.VALUES: [{CmdbObjectMdsRowKey.DATA: [
            make_field(InterfaceField.SUBNET, SUBNET_1_ID),
            make_field(InterfaceField.IP, ASSIGNED_IP),
            make_field(InterfaceField.TYPE, IpAddressFamily.IPV4),
        ]}],
    }])

    errors = enforce_object_invariants(objects_manager, types_manager, candidate)

    assert InterfaceErrorCode.IP_DUPLICATE in _codes(errors)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 DELETE GUARDS                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_delete_guard_blocks_a_supernet_with_assigned_subnets(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Deleting a supernet that subnets reference is refused by the real reference query"""
    supernet_doc = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: SUPERNET_A_ID}, as_dict=True,
    )[0]

    errors = enforce_delete_guards(objects_manager, types_manager, supernet_doc)

    assert DeleteGuardErrorCode.SUPERNET_HAS_REFERENCING_SUBNETS in _codes(errors)


def test_delete_guard_allows_an_unreferenced_supernet(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A supernet without assigned subnets passes the guard"""
    supernet_doc = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: SUPERNET_B_ID}, as_dict=True,
    )[0]

    assert not enforce_delete_guards(objects_manager, types_manager, supernet_doc)


def test_delete_guard_blocks_a_subnet_referenced_by_vlan_and_interface(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Deleting a subnet referenced by a VLAN and by an interface row reports both blockers"""
    subnet_doc = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_1_ID}, as_dict=True,
    )[0]

    errors = enforce_delete_guards(objects_manager, types_manager, subnet_doc)
    codes = _codes(errors)

    assert DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_VLANS in codes
    assert DeleteGuardErrorCode.SUBNET_HAS_REFERENCING_INTERFACES in codes


def test_delete_guard_allows_an_unreferenced_subnet(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A subnet without VLANs, interface rows or child subnets passes the guard"""
    subnet_doc = objects_manager.find_objects(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_2_ID}, as_dict=True,
    )[0]

    assert not enforce_delete_guards(objects_manager, types_manager, subnet_doc)


def test_delete_guard_allows_a_vlan(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Nothing references a VLAN in the IPAM model, so its deletion is always allowed"""
    vlan_doc = objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID: VLAN_ID}, as_dict=True)[0]

    assert not enforce_delete_guards(objects_manager, types_manager, vlan_doc)


# -------------------------------------------------------------------------------------------------------------------- #
#                                              SUPERNET MEMBERSHIP                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_unassign_subnets_rejects_foreign_ids_without_writing(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A batch containing an unassigned id aborts 400 and the assigned subnet keeps its reference"""
    with pytest.raises(HTTPException) as exc_info:
        unassign_subnets_from_supernet(
            objects_manager, types_manager, SUPERNET_A_ID, [SUBNET_1_ID, FOREIGN_SUBNET_ID],
        )

    assert exc_info.value.code == 400

    subnet_doc = objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID: SUBNET_1_ID}, as_dict=True)[0]
    assert extract_field_value(subnet_doc, SubnetField.PARENT_SUPERNET) == SUPERNET_A_ID


def test_unassign_subnets_clears_the_reference_with_a_real_write(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The happy path clears dg-supernet-ref on the requested subnet and echoes the count"""
    result = unassign_subnets_from_supernet(objects_manager, types_manager, SUPERNET_A_ID, [SUBNET_3_ID])

    assert result[IpamUnassignKey.SUBNET_IDS] == [SUBNET_3_ID]
    assert result[IpamUnassignKey.UNASSIGNED_COUNT] == 1

    detached = objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID: SUBNET_3_ID}, as_dict=True)[0]
    untouched = objects_manager.find_objects({CmdbObjectKey.PUBLIC_ID: SUBNET_1_ID}, as_dict=True)[0]

    assert extract_field_value(detached, SubnetField.PARENT_SUPERNET) is None
    assert extract_field_value(untouched, SubnetField.PARENT_SUPERNET) == SUPERNET_A_ID
