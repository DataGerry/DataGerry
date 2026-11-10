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
Integration tests for the IPAM reference lookups and the delete guards built on them, against a real MongoDB

Pins what the unit tests can only assert as call arguments: the projection really answers the two keys and
nothing else of the document, the ``$in`` criteria match several referenced ids at once, the selection
exclusion (``$nin``) leaves the deleted-together objects out, the read is capped and sorted, the count
behind "... and N more", the one-read special-type lookup, and the guards' answers on a seeded topology -
a selection that removes a supernet with all of its subnets is not blocked, one that leaves a subnet behind is
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpamSection,
    SubnetField,
    SupernetField,
    VlanField,
)
from cmdb.framework.ipam.enforcement import enforce_delete_guards, selection_ipam_type_ids
from cmdb.framework.ipam.references import (
    count_references,
    excluding_ids,
    find_interfaces_referencing_subnet,
    find_references,
    find_subnets_referencing_supernet,
    find_vlans_referencing_subnet,
    interfaces_referencing_subnets_criteria,
    resolve_special_type_id,
    resolve_special_type_ids,
    subnets_referencing_supernets_criteria,
)
from cmdb.utils import ValidationErrorKey
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE_ID: int = 942301
SUBNET_TYPE_ID: int = 942302
VLAN_TYPE_ID: int = 942303
CARRIER_TYPE_ID: int = 942304
OTHER_CARRIER_TYPE_ID: int = 942305

BIG_SUPERNET_ID: int = 942310       # 25 subnets: the capped message
SMALL_SUPERNET_ID: int = 942311     # 2 subnets
LONELY_SUPERNET_ID: int = 942312    # no subnet
FIRST_BIG_SUBNET_ID: int = 942400   # 942400 ... 942424
BIG_SUBNET_COUNT: int = 25
SMALL_SUBNET_IDS: list[int] = [942330, 942331]
VLAN_IDS: list[int] = [942340, 942341]          # both point at SMALL_SUBNET_IDS[0]
CARRIER_ID: int = 942350                        # interface row -> SMALL_SUBNET_IDS[0]
OTHER_CARRIER_ID: int = 942351                  # interface row -> SMALL_SUBNET_IDS[0], another type
DECOY_CARRIER_ID: int = 942352                  # same field name, another section: no reference

BIG_SUBNET_IDS: list[int] = [FIRST_BIG_SUBNET_ID + offset for offset in range(BIG_SUBNET_COUNT)]
TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, VLAN_TYPE_ID, CARRIER_TYPE_ID, OTHER_CARRIER_TYPE_ID]
OBJECT_IDS: list[int] = [BIG_SUPERNET_ID, SMALL_SUPERNET_ID, LONELY_SUPERNET_ID, *BIG_SUBNET_IDS, *SMALL_SUBNET_IDS,
                         *VLAN_IDS, CARRIER_ID, OTHER_CARRIER_ID, DECOY_CARRIER_ID]
LISTED: int = 20
REFERENCE_KEYS: set[str] = {CmdbObjectKey.PUBLIC_ID.value, CmdbObjectKey.TYPE_ID.value}


def _interface_rows(subnet_id: int, section_id: str = IpamSection.INTERFACE.value) -> list[dict[str, Any]]:
    """One interface-shaped MDS section whose single row names the subnet."""
    return [{
        CmdbObjectMdsKey.SECTION_ID.value: section_id,
        CmdbObjectMdsKey.VALUES.value: [
            {CmdbObjectMdsRowKey.DATA.value: [make_field(InterfaceField.SUBNET, subnet_id)]},
        ],
    }]


def _subnet(public_id: int, supernet_id: int) -> dict[str, Any]:
    """A SUBNET object pointing at a supernet."""
    return make_object_doc(public_id, SUBNET_TYPE_ID, [
        make_field(SubnetField.NAME, f'it-ref-sub-{public_id}'), make_field(SubnetField.PARENT_SUPERNET, supernet_id),
    ])


@pytest.fixture(scope='module', autouse=True)
def _seed_reference_topology(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds three supernets, their subnets, VLANs and interface carriers; removes them afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'it-ref-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'it-ref-subnet', SpecialType.SUBNET),
        make_type_doc(VLAN_TYPE_ID, 'it-ref-vlan', SpecialType.VLAN),
        make_type_doc(CARRIER_TYPE_ID, 'it-ref-carrier', None),
        make_type_doc(OTHER_CARRIER_TYPE_ID, 'it-ref-carrier-2', None),
    ])
    objects.insert_many([
        *(make_object_doc(supernet_id, SUPERNET_TYPE_ID, [make_field(SupernetField.NAME, f'it-ref-sn-{supernet_id}')])
          for supernet_id in (BIG_SUPERNET_ID, SMALL_SUPERNET_ID, LONELY_SUPERNET_ID)),
        # inserted in descending id order, so an unsorted read would answer them backwards
        *(_subnet(subnet_id, BIG_SUPERNET_ID) for subnet_id in reversed(BIG_SUBNET_IDS)),
        *(_subnet(subnet_id, SMALL_SUPERNET_ID) for subnet_id in SMALL_SUBNET_IDS),
        *(make_object_doc(vlan_id, VLAN_TYPE_ID, [make_field(VlanField.SUBNET_REF, SMALL_SUBNET_IDS[0])])
          for vlan_id in VLAN_IDS),
        make_object_doc(OTHER_CARRIER_ID, OTHER_CARRIER_TYPE_ID, [], mds=_interface_rows(SMALL_SUBNET_IDS[0])),
        make_object_doc(CARRIER_ID, CARRIER_TYPE_ID, [], mds=_interface_rows(SMALL_SUBNET_IDS[0])),
        make_object_doc(DECOY_CARRIER_ID, CARRIER_TYPE_ID, [], mds=_interface_rows(SMALL_SUBNET_IDS[0], 'dg-other')),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': OBJECT_IDS}})


@pytest.fixture(name='objects_manager')
def fixture_objects_manager(database_manager: MongoDatabaseManager) -> ObjectsManager:
    """An ObjectsManager on the test database."""
    return ObjectsManager(database_manager)


@pytest.fixture(name='types_manager')
def fixture_types_manager(database_manager: MongoDatabaseManager) -> TypesManager:
    """A TypesManager on the test database."""
    return TypesManager(database_manager)


def _ids(references: list[dict[str, Any]]) -> list[int]:
    """The public_ids of reference dicts, in the order answered."""
    return [reference[CmdbObjectKey.PUBLIC_ID.value] for reference in references]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the lookups                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_finders_answer_two_keys_and_nothing_else_of_the_document(objects_manager: ObjectsManager) -> None:
    """No fields, no MDS rows, no _id: the projection is applied by the database"""
    answers = [
        *find_subnets_referencing_supernet(objects_manager, SUBNET_TYPE_ID, SMALL_SUPERNET_ID),
        *find_vlans_referencing_subnet(objects_manager, VLAN_TYPE_ID, SMALL_SUBNET_IDS[0]),
        *find_interfaces_referencing_subnet(objects_manager, SMALL_SUBNET_IDS[0]),
    ]

    assert answers
    assert all(set(answer) == REFERENCE_KEYS for answer in answers)


def test_the_finders_answer_the_right_objects_in_ascending_id(objects_manager: ObjectsManager) -> None:
    """Each finder: exactly its referencing objects, sorted; the decoy section does not count"""
    assert _ids(find_subnets_referencing_supernet(objects_manager, SUBNET_TYPE_ID, BIG_SUPERNET_ID)) == BIG_SUBNET_IDS
    assert _ids(find_vlans_referencing_subnet(objects_manager, VLAN_TYPE_ID, SMALL_SUBNET_IDS[0])) == VLAN_IDS
    carriers = find_interfaces_referencing_subnet(objects_manager, SMALL_SUBNET_IDS[0])
    assert carriers == [
        {CmdbObjectKey.PUBLIC_ID.value: CARRIER_ID, CmdbObjectKey.TYPE_ID.value: CARRIER_TYPE_ID},
        {CmdbObjectKey.PUBLIC_ID.value: OTHER_CARRIER_ID, CmdbObjectKey.TYPE_ID.value: OTHER_CARRIER_TYPE_ID},
    ]
    assert not find_subnets_referencing_supernet(objects_manager, SUBNET_TYPE_ID, LONELY_SUPERNET_ID)


def test_one_criteria_matches_several_referenced_ids(objects_manager: ObjectsManager) -> None:
    """The $in form: the subnets of two supernets in one read"""
    criteria = subnets_referencing_supernets_criteria(SUBNET_TYPE_ID, [SMALL_SUPERNET_ID, BIG_SUPERNET_ID])

    assert _ids(find_references(objects_manager, criteria)) == sorted([*SMALL_SUBNET_IDS, *BIG_SUBNET_IDS])


def test_the_selection_is_left_out(objects_manager: ObjectsManager) -> None:
    """$nin: carriers deleted together with the subnet do not reference it"""
    criteria = excluding_ids(interfaces_referencing_subnets_criteria([SMALL_SUBNET_IDS[0]]), {CARRIER_ID})

    assert _ids(find_references(objects_manager, criteria)) == [OTHER_CARRIER_ID]


def test_the_read_is_capped_and_the_rest_counted(objects_manager: ObjectsManager) -> None:
    """A limit reads the lowest ids; the count is the whole match"""
    criteria = subnets_referencing_supernets_criteria(SUBNET_TYPE_ID, [BIG_SUPERNET_ID])

    assert _ids(find_references(objects_manager, criteria, limit=LISTED + 1)) == BIG_SUBNET_IDS[:LISTED + 1]
    assert count_references(objects_manager, criteria) == BIG_SUBNET_COUNT


def test_the_special_type_ids_resolve_in_one_read_and_one_at_a_time(types_manager: TypesManager) -> None:
    """The several-marker read and the single projected read agree with the seeded types"""
    resolved = resolve_special_type_ids(types_manager, [SpecialType.SUBNET, SpecialType.VLAN, SpecialType.SUPERNET])

    assert resolved == {SpecialType.SUBNET: SUBNET_TYPE_ID, SpecialType.VLAN: VLAN_TYPE_ID,
                        SpecialType.SUPERNET: SUPERNET_TYPE_ID}
    assert resolve_special_type_id(types_manager, SpecialType.VLAN) == VLAN_TYPE_ID


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the delete guards                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _target(public_id: int, type_id: int) -> dict[str, Any]:
    """A delete target."""
    return {CmdbObjectKey.PUBLIC_ID.value: public_id, CmdbObjectKey.TYPE_ID.value: type_id}


def _messages(errors: list[dict[str, Any]]) -> list[str]:
    """The guard errors' messages."""
    return [error[ValidationErrorKey.MESSAGE] for error in errors]


def test_a_supernet_with_many_subnets_names_twenty_and_counts_the_rest(
        objects_manager: ObjectsManager, types_manager: TypesManager) -> None:
    """25 subnets: the first 20 in ascending id, then '... and 5 more'"""
    errors = enforce_delete_guards(objects_manager, types_manager, _target(BIG_SUPERNET_ID, SUPERNET_TYPE_ID))

    listed = ', '.join(map(str, BIG_SUBNET_IDS[:LISTED]))
    assert _messages(errors) == [f'Supernet is referenced by subnets: {listed} and 5 more']


def test_a_subnet_names_its_vlans_and_its_interface_carriers(
        objects_manager: ObjectsManager, types_manager: TypesManager) -> None:
    """Both kinds, each list whole"""
    errors = enforce_delete_guards(objects_manager, types_manager, _target(SMALL_SUBNET_IDS[0], SUBNET_TYPE_ID))

    assert _messages(errors) == [
        f'Subnet is referenced by vlans: {VLAN_IDS[0]}, {VLAN_IDS[1]}',
        f'Subnet is referenced by interface rows on objects: {CARRIER_ID}, {OTHER_CARRIER_ID}',
    ]


def test_a_selection_holding_the_supernet_and_all_its_subnets_is_not_blocked(
        objects_manager: ObjectsManager, types_manager: TypesManager) -> None:
    """The subnets go with their supernet: nothing outside the selection references it"""
    selection = [_target(SMALL_SUPERNET_ID, SUPERNET_TYPE_ID),
                 *(_target(subnet_id, SUBNET_TYPE_ID) for subnet_id in SMALL_SUBNET_IDS[1:])]

    # the second subnet carries no VLAN / interface; the first stays outside and blocks the supernet
    assert selection_ipam_type_ids(objects_manager, types_manager, selection) is not None

    selection.append(_target(SMALL_SUBNET_IDS[0], SUBNET_TYPE_ID))
    selection.extend(_target(vlan_id, VLAN_TYPE_ID) for vlan_id in VLAN_IDS)
    selection.extend(_target(carrier_id, CARRIER_TYPE_ID) for carrier_id in (CARRIER_ID, OTHER_CARRIER_ID))

    assert selection_ipam_type_ids(objects_manager, types_manager, selection) is None


def test_the_per_target_guard_leaves_the_selection_out(
        objects_manager: ObjectsManager, types_manager: TypesManager) -> None:
    """A subnet deleted with its VLANs is still held by the interface carriers outside the selection"""
    selection_ids = {SMALL_SUBNET_IDS[0], *VLAN_IDS}

    errors = enforce_delete_guards(objects_manager, types_manager, _target(SMALL_SUBNET_IDS[0], SUBNET_TYPE_ID),
                                   exclude_ids=selection_ids)

    assert _messages(errors) == [f'Subnet is referenced by interface rows on objects: {CARRIER_ID}, {OTHER_CARRIER_ID}']


def test_an_unreferenced_supernet_passes_both_checks(
        objects_manager: ObjectsManager, types_manager: TypesManager) -> None:
    """Nothing points at it"""
    target = _target(LONELY_SUPERNET_ID, SUPERNET_TYPE_ID)

    assert not enforce_delete_guards(objects_manager, types_manager, target)
    assert selection_ipam_type_ids(objects_manager, types_manager, [target]) is None
