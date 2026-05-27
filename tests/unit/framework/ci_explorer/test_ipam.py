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
Unit tests for cmdb.framework.ci_explorer.ipam

The references-side helpers (find_subnets_referencing_supernet, etc.) and the
SpecialType resolver are exercised in their own suites; here we monkey-patch them at the
module level so collect_ipam_neighbours is tested in isolation against controlled inputs
"""
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.framework.ci_explorer.ipam import (
    IpamRelationName,
    collect_ipam_neighbours,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE: str = 'cmdb.framework.ci_explorer.ipam'

TYPE_SUPERNET: int = 30
TYPE_SUBNET: int = 31
TYPE_VLAN: int = 32
TYPE_SERVER: int = 33

TARGET_SUPERNET: int = 300
TARGET_SUBNET: int = 301
TARGET_VLAN: int = 302
TARGET_SERVER: int = 303

SUBNET_CHILD: int = 400
VLAN_CHILD: int = 401
INTERFACE_CARRIER: int = 402
PARENT_SUPERNET: int = 500
PARENT_SUBNET: int = 501


def _build_object(public_id: int, type_id: int) -> dict[str, Any]:
    """Constructs a minimal object document used as fake return from objects_manager.find."""
    return {'public_id': public_id, 'type_id': type_id}


def _make_supernet_target() -> dict[str, Any]:
    """Target object document for a SUPERNET CmdbObject."""
    return {'public_id': TARGET_SUPERNET, 'type_id': TYPE_SUPERNET, 'fields': []}


def _make_subnet_target(supernet_ref: int | None = PARENT_SUPERNET) -> dict[str, Any]:
    """Target object document for a SUBNET CmdbObject, optionally with a dg-supernet-ref."""
    fields: list[dict[str, Any]] = []
    if supernet_ref is not None:
        fields.append({'name': 'dg-supernet-ref', 'value': supernet_ref})
    return {'public_id': TARGET_SUBNET, 'type_id': TYPE_SUBNET, 'fields': fields}


def _make_vlan_target(subnet_ref: int | None = PARENT_SUBNET) -> dict[str, Any]:
    """Target object document for a VLAN CmdbObject, optionally with a dg-subnet-ref."""
    fields: list[dict[str, Any]] = []
    if subnet_ref is not None:
        fields.append({'name': 'dg-subnet-ref', 'value': subnet_ref})
    return {'public_id': TARGET_VLAN, 'type_id': TYPE_VLAN, 'fields': fields}


def _make_interface_carrier(subnet_refs: list[int]) -> dict[str, Any]:
    """Target object document for any CmdbObject that carries dg-ipam-interface MDS rows."""
    return {
        'public_id': TARGET_SERVER,
        'type_id': TYPE_SERVER,
        'fields': [],
        'multi_data_sections': [
            {
                'section_id': 'dg-ipam-interface',
                'values': [
                    {'data': [{'name': 'dg-interface-subnet', 'value': subnet_ref}]}
                    for subnet_ref in subnet_refs
                ],
            },
        ],
    }


def _patch_special_type_resolver():
    """Returns a patch that stubs resolve_special_type_id so each SpecialType maps to a known id."""
    mapping = {
        'SUPERNET': TYPE_SUPERNET,
        'SUBNET': TYPE_SUBNET,
        'VLAN': TYPE_VLAN,
    }
    return patch(f'{MODULE}.resolve_special_type_id', side_effect=lambda _tm, st: mapping.get(st.value))


# -------------------------------------------------------------------------------------------------------------------- #
#                                            collect_ipam_neighbours                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_returns_empty_when_both_directions_disabled() -> None:
    """include_parents and include_children both False short-circuits with no DB calls"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    result = collect_ipam_neighbours(
        target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
        include_parents=False, include_children=False,
        types_filter=frozenset(), remaining=0, item_limit_active=False,
        objects_manager=objects_manager, types_manager=types_manager,
    )

    assert result == []
    objects_manager.find.assert_not_called()


def test_returns_empty_when_remaining_is_zero_under_item_limit() -> None:
    """remaining<=0 with item_limit_active short-circuits"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    result = collect_ipam_neighbours(
        target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
        include_parents=True, include_children=True,
        types_filter=frozenset(), remaining=0, item_limit_active=True,
        objects_manager=objects_manager, types_manager=types_manager,
    )

    assert result == []
    objects_manager.find.assert_not_called()


def test_supernet_target_grafts_subnet_children() -> None:
    """target=SUPERNET → plan includes its SUBNETs as children"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [_build_object(SUBNET_CHILD, TYPE_SUBNET)]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet',
               return_value=[{'public_id': SUBNET_CHILD, 'type_id': TYPE_SUBNET}]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert len(result) == 1
    assert result[0].neighbour_object['public_id'] == SUBNET_CHILD
    assert result[0].is_child_of_target is True
    assert result[0].relation_name == IpamRelationName.SUBNET


def test_subnet_target_grafts_supernet_parent_and_vlan_interface_children() -> None:
    """target=SUBNET → parent SUPERNET (via dg-supernet-ref), child VLANs + child interface carriers"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [
        _build_object(PARENT_SUPERNET, TYPE_SUPERNET),
        _build_object(VLAN_CHILD, TYPE_VLAN),
        _build_object(INTERFACE_CARRIER, TYPE_SERVER),
    ]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet',
               return_value=[{'public_id': VLAN_CHILD, 'type_id': TYPE_VLAN}]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet',
               return_value=[{'public_id': INTERFACE_CARRIER, 'type_id': TYPE_SERVER}]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUBNET, target_object=_make_subnet_target(),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    by_id = {n.neighbour_object['public_id']: n for n in result}
    assert by_id[PARENT_SUPERNET].is_child_of_target is False
    assert by_id[PARENT_SUPERNET].relation_name == IpamRelationName.SUPERNET
    assert by_id[VLAN_CHILD].is_child_of_target is True
    assert by_id[VLAN_CHILD].relation_name == IpamRelationName.VLAN
    assert by_id[INTERFACE_CARRIER].is_child_of_target is True
    assert by_id[INTERFACE_CARRIER].relation_name == IpamRelationName.INTERFACE


def test_vlan_target_grafts_only_parent_subnet() -> None:
    """target=VLAN → plan has only the parent SUBNET (via dg-subnet-ref)"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [_build_object(PARENT_SUBNET, TYPE_SUBNET)]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_VLAN, target_object=_make_vlan_target(),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert len(result) == 1
    assert result[0].neighbour_object['public_id'] == PARENT_SUBNET
    assert result[0].is_child_of_target is False
    assert result[0].relation_name == IpamRelationName.SUBNET


def test_interface_carrier_target_grafts_subnet_parents_from_mds_rows() -> None:
    """target=interface carrier → plan has the SUBNETs its dg-ipam-interface rows point at"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [_build_object(PARENT_SUBNET, TYPE_SUBNET)]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SERVER, target_object=_make_interface_carrier([PARENT_SUBNET]),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert len(result) == 1
    assert result[0].neighbour_object['public_id'] == PARENT_SUBNET
    assert result[0].is_child_of_target is False
    assert result[0].relation_name == IpamRelationName.SUBNET


def test_self_reference_in_dg_supernet_ref_is_skipped() -> None:
    """A SUBNET with dg-supernet-ref pointing at itself is silently skipped (no self-edge)"""
    target = _make_subnet_target(supernet_ref=TARGET_SUBNET)
    objects_manager = MagicMock()
    objects_manager.find.return_value = []

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUBNET, target_object=target,
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert result == []


def test_interface_row_pointing_at_self_is_skipped() -> None:
    """A dg-interface-subnet row pointing at the target's own public_id contributes no edge"""
    target = _make_interface_carrier([TARGET_SERVER])
    objects_manager = MagicMock()
    objects_manager.find.return_value = []

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SERVER, target_object=target,
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert result == []


def test_include_children_false_filters_out_child_neighbours() -> None:
    """include_children=False on a SUPERNET target drops the SUBNET children before the bulk fetch"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = []

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet',
               return_value=[{'public_id': SUBNET_CHILD, 'type_id': TYPE_SUBNET}]) as find_subnets, \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
            include_parents=True, include_children=False,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert result == []
    # find_subnets_referencing_supernet was called (planning happens unconditionally) but the
    # resulting child entry is dropped before the bulk fetch
    find_subnets.assert_called_once()
    objects_manager.find.assert_not_called()


def test_types_filter_is_applied_at_mongo_level() -> None:
    """types_filter narrows the bulk fetch via a type_id $in clause (matches relation/location semantics)"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [_build_object(SUBNET_CHILD, TYPE_SUBNET)]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet',
               return_value=[{'public_id': SUBNET_CHILD, 'type_id': TYPE_SUBNET}]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        collect_ipam_neighbours(
            target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
            include_parents=True, include_children=True,
            types_filter=frozenset({TYPE_SUBNET}), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    criteria = objects_manager.find.call_args.kwargs['criteria']
    assert criteria['type_id']['$in'] == [TYPE_SUBNET]


def test_item_limit_caps_post_filter_count() -> None:
    """When item_limit is active the surviving list is sliced to remaining after the bulk fetch"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = [
        _build_object(401, TYPE_VLAN),
        _build_object(402, TYPE_SERVER),
        _build_object(403, TYPE_SERVER),
    ]

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet', return_value=[]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet',
               return_value=[{'public_id': 401, 'type_id': TYPE_VLAN}]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet',
               return_value=[
                   {'public_id': 402, 'type_id': TYPE_SERVER},
                   {'public_id': 403, 'type_id': TYPE_SERVER},
               ]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUBNET, target_object=_make_subnet_target(supernet_ref=None),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=2, item_limit_active=True,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert len(result) == 2


def test_plan_entries_whose_object_failed_to_load_are_dropped() -> None:
    """When a planned neighbour doesn't survive the bulk fetch (deleted between calls), it's skipped"""
    objects_manager = MagicMock()
    objects_manager.find.return_value = []  # the bulk fetch returns nothing

    with _patch_special_type_resolver(), \
         patch(f'{MODULE}.find_subnets_referencing_supernet',
               return_value=[{'public_id': SUBNET_CHILD, 'type_id': TYPE_SUBNET}]), \
         patch(f'{MODULE}.find_vlans_referencing_subnet', return_value=[]), \
         patch(f'{MODULE}.find_interfaces_referencing_subnet', return_value=[]):
        result = collect_ipam_neighbours(
            target_id=TARGET_SUPERNET, target_object=_make_supernet_target(),
            include_parents=True, include_children=True,
            types_filter=frozenset(), remaining=10, item_limit_active=False,
            objects_manager=objects_manager, types_manager=MagicMock(),
        )

    assert result == []
