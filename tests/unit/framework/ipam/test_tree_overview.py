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
Unit tests for cmdb.framework.ipam.tree_overview

Covers the pure helpers (reference coercion, node shaping, display-order sorting, CIDR
containment nesting), the type-scoped object loader (Mongo criteria pinned via
assert_called_once_with) and the three orchestrators (build_ipam_tree,
build_supernet_subnet_tree, build_unassigned_subnets). For the orchestrators the loaders are
patched at the module path so each test verifies orchestration in isolation; the loaders have
their own dedicated tests in this file. sort_tree_nodes exercises _tree_sort_key, so the key
function is not tested directly
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    SupernetField,
    IpAddressFamily,
    IpamTreeKey,
)
from cmdb.framework.ipam.tree_overview import (
    _coerce_ref_id,
    _collect_referenced_supernet_ids,
    load_all_special_type_objects,
    _parent_supernet_id,
    subnet_tree_node,
    _supernet_tree_node,
    build_ipam_tree,
    build_supernet_subnet_tree,
    build_unassigned_subnets,
    nest_subnet_nodes,
    sort_tree_nodes,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUPERNET_TYPE_ID: int = 10
SUBNET_TYPE_ID: int = 11
SUPERNET_OBJECT_ID: int = 100
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
SUBNET_OBJECT_ID_C: int = 203
SUBNET_OBJECT_ID_D: int = 204

SUPERNET_RANGE: str = '10.0.0.0/8'
SUBNET_RANGE_BROAD: str = '10.1.0.0/16'
SUBNET_RANGE_NESTED: str = '10.1.4.0/24'
SUBNET_RANGE_SIBLING: str = '10.2.0.0/16'
SUBNET_RANGE_V6: str = '2001:db8::/32'
SUBNET_RANGE_V6_NONCANONICAL: str = '2001:DB8::/32'
TIE_RANGE_NARROW: str = '10.0.0.0/16'
UNPARSABLE_RANGE: str = 'not-a-cidr'

SUPERNET_NAME: str = 'DC'
SUBNET_NAME_A: str = 'Core'
SUBNET_NAME_B: str = 'Mgmt'
UNPARSABLE_NAME_FIRST: str = 'Alpha'
UNPARSABLE_NAME_SECOND: str = 'beta'

PATH: str = 'cmdb.framework.ipam.tree_overview'

SUPERNET_ICON: str = 'fas fa-sitemap'
SUBNET_ICON: str = 'fas fa-network-wired'


@pytest.fixture(autouse=True)
def _stub_special_type_icon():
    """Stubs resolve_special_type_icon so orchestrators don't hit the DB; per-family icon values."""
    icons: dict[SpecialType, str] = {SpecialType.SUPERNET: SUPERNET_ICON, SpecialType.SUBNET: SUBNET_ICON}

    with patch(f'{PATH}.resolve_special_type_icon', side_effect=lambda _types_manager, special_type: icons[special_type]):
        yield


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_subnet_doc(
    public_id: int,
    network_range: Any = None,
    name: Any = None,
    subnet_type: Any = None,
    supernet_ref: Any = None,
    include_ref_field: bool = False,
) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc; the ref field is only present when given or forced."""
    fields: list[dict[str, Any]] = []

    if network_range is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE, CmdbObjectFieldKey.VALUE: network_range})

    if name is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.NAME, CmdbObjectFieldKey.VALUE: name})

    if subnet_type is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.TYPE, CmdbObjectFieldKey.VALUE: subnet_type})

    if supernet_ref is not None or include_ref_field:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.PARENT_SUPERNET, CmdbObjectFieldKey.VALUE: supernet_ref})

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS: fields,
    }


def _make_supernet_doc(public_id: int, network_range: Any = None, name: Any = None) -> dict[str, Any]:
    """Builds a SUPERNET CmdbObject doc with optional range and name fields."""
    fields: list[dict[str, Any]] = []

    if network_range is not None:
        fields.append({CmdbObjectFieldKey.NAME: SupernetField.NETWORK_RANGE, CmdbObjectFieldKey.VALUE: network_range})

    if name is not None:
        fields.append({CmdbObjectFieldKey.NAME: SupernetField.NAME, CmdbObjectFieldKey.VALUE: name})

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUPERNET_TYPE_ID,
        CmdbObjectKey.FIELDS: fields,
    }


def _make_node(public_id: int, cidr: Any, family: str = IpAddressFamily.IPV4, name: Any = None) -> dict[str, Any]:
    """Builds an already-shaped tree node for the sort / nest helpers."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        IpamTreeKey.NAME: name,
        IpamTreeKey.CIDR: cidr,
        IpamTreeKey.TYPE: family,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _coerce_ref_id                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_coerce_ref_id_passes_ints_and_digit_strings_through() -> None:
    """An int ref and a digit-string ref both coerce to the int public_id"""
    assert _coerce_ref_id(SUPERNET_OBJECT_ID) == SUPERNET_OBJECT_ID
    assert _coerce_ref_id(str(SUPERNET_OBJECT_ID)) == SUPERNET_OBJECT_ID


def test_coerce_ref_id_treats_empty_markers_as_no_reference() -> None:
    """None, the empty string and 0 all coerce to None (no usable reference)"""
    assert _coerce_ref_id(None) is None
    assert _coerce_ref_id('') is None
    assert _coerce_ref_id(0) is None


def test_coerce_ref_id_returns_none_for_garbage() -> None:
    """A non-numeric string coerces to None instead of raising"""
    assert _coerce_ref_id(UNPARSABLE_RANGE) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                _parent_supernet_id                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_parent_supernet_id_reads_the_ref_field() -> None:
    """A subnet with a numeric dg-supernet-ref resolves to that public_id"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID_A, supernet_ref=SUPERNET_OBJECT_ID)

    assert _parent_supernet_id(doc) == SUPERNET_OBJECT_ID


def test_parent_supernet_id_returns_none_when_field_missing_or_cleared() -> None:
    """A missing ref field and a cleared (None) ref both count as unassigned"""
    missing = _make_subnet_doc(SUBNET_OBJECT_ID_A)
    cleared = _make_subnet_doc(SUBNET_OBJECT_ID_B, include_ref_field=True)

    assert _parent_supernet_id(missing) is None
    assert _parent_supernet_id(cleared) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                         _collect_referenced_supernet_ids                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_collect_referenced_supernet_ids_collects_coerced_refs_and_skips_unassigned() -> None:
    """Numeric and digit-string refs land in the set; unassigned subnets contribute nothing"""
    docs = [
        _make_subnet_doc(SUBNET_OBJECT_ID_A, supernet_ref=SUPERNET_OBJECT_ID),
        _make_subnet_doc(SUBNET_OBJECT_ID_B, supernet_ref=str(SUPERNET_OBJECT_ID + 1)),
        _make_subnet_doc(SUBNET_OBJECT_ID_C),
    ]

    assert _collect_referenced_supernet_ids(docs) == {SUPERNET_OBJECT_ID, SUPERNET_OBJECT_ID + 1}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                subnet_tree_node                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_subnet_tree_node_shapes_the_full_node_including_icon() -> None:
    """A well-formed subnet yields public_id, name, canonical cidr, the family and the type icon"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_BROAD, name=SUBNET_NAME_A)

    assert subnet_tree_node(doc, SUBNET_ICON) == {
        CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID_A,
        IpamTreeKey.NAME: SUBNET_NAME_A,
        IpamTreeKey.CIDR: SUBNET_RANGE_BROAD,
        IpamTreeKey.TYPE: IpAddressFamily.IPV4,
        IpamTreeKey.ICON: SUBNET_ICON,
    }


def test_subnet_tree_node_icon_defaults_to_none() -> None:
    """Without an icon argument the node carries icon=None (pass-through for the FE default)"""
    node = subnet_tree_node(_make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_BROAD))

    assert node[IpamTreeKey.ICON] is None


def test_subnet_tree_node_normalises_the_cidr_to_canonical_form() -> None:
    """A parsable but non-canonical IPv6 spelling is normalised via the parsed network"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V6_NONCANONICAL)

    assert subnet_tree_node(doc)[IpamTreeKey.CIDR] == SUBNET_RANGE_V6


def test_subnet_tree_node_passes_unparsable_cidr_through_and_falls_back_to_selector() -> None:
    """An unparsable range stays verbatim and the family comes from the selector field"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=UNPARSABLE_RANGE, subnet_type=IpAddressFamily.IPV6)
    node = subnet_tree_node(doc)

    assert node[IpamTreeKey.CIDR] == UNPARSABLE_RANGE
    assert node[IpamTreeKey.TYPE] == IpAddressFamily.IPV6


def test_subnet_tree_node_resolves_family_cidr_first() -> None:
    """An IPv6 CIDR wins over a contradicting IPv4 selector value"""
    doc = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V6, subnet_type=IpAddressFamily.IPV4)

    assert subnet_tree_node(doc)[IpamTreeKey.TYPE] == IpAddressFamily.IPV6


def test_subnet_tree_node_nulls_missing_name_and_range() -> None:
    """A subnet without name / range fields yields None for both and defaults to IPv4"""
    node = subnet_tree_node(_make_subnet_doc(SUBNET_OBJECT_ID_A))

    assert node[IpamTreeKey.NAME] is None
    assert node[IpamTreeKey.CIDR] is None
    assert node[IpamTreeKey.TYPE] == IpAddressFamily.IPV4


# -------------------------------------------------------------------------------------------------------------------- #
#                                               _supernet_tree_node                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_supernet_tree_node_sets_has_children_from_the_referenced_set() -> None:
    """has_children is True iff the supernet's public_id appears in the referenced-id set"""
    doc = _make_supernet_doc(SUPERNET_OBJECT_ID, network_range=SUPERNET_RANGE, name=SUPERNET_NAME)

    with_children = _supernet_tree_node(doc, {SUPERNET_OBJECT_ID}, SUPERNET_ICON)
    without_children = _supernet_tree_node(doc, set(), SUPERNET_ICON)

    assert with_children[IpamTreeKey.HAS_CHILDREN] is True
    assert without_children[IpamTreeKey.HAS_CHILDREN] is False
    assert with_children[IpamTreeKey.CIDR] == SUPERNET_RANGE
    assert with_children[IpamTreeKey.TYPE] == IpAddressFamily.IPV4
    assert with_children[IpamTreeKey.ICON] == SUPERNET_ICON


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 sort_tree_nodes                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_sort_tree_nodes_groups_ipv4_before_ipv6() -> None:
    """Every IPv4 node precedes every IPv6 node regardless of input order"""
    v6 = _make_node(1, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6)
    v4 = _make_node(2, SUBNET_RANGE_BROAD)

    assert sort_tree_nodes([v6, v4]) == [v4, v6]


def test_sort_tree_nodes_orders_by_network_address_then_prefix_length() -> None:
    """Within a family: ascending address, with the broader prefix first on an address tie"""
    narrow_same_addr = _make_node(1, TIE_RANGE_NARROW)
    broad_same_addr = _make_node(2, SUPERNET_RANGE)
    higher_addr = _make_node(3, SUBNET_RANGE_BROAD)

    result = sort_tree_nodes([higher_addr, narrow_same_addr, broad_same_addr])

    assert [n[CmdbObjectKey.PUBLIC_ID] for n in result] == [2, 1, 3]


def test_sort_tree_nodes_places_unparsable_nodes_last_within_their_family_by_name() -> None:
    """Unparsable-CIDR nodes trail their family group, ordered case-insensitively by name"""
    v4_parsable = _make_node(1, SUBNET_RANGE_BROAD)
    v4_unparsable_b = _make_node(2, UNPARSABLE_RANGE, name=UNPARSABLE_NAME_SECOND)
    v4_unparsable_a = _make_node(3, None, name=UNPARSABLE_NAME_FIRST)
    v6_parsable = _make_node(4, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6)

    result = sort_tree_nodes([v6_parsable, v4_unparsable_b, v4_unparsable_a, v4_parsable])

    assert [n[CmdbObjectKey.PUBLIC_ID] for n in result] == [1, 3, 2, 4]


def test_sort_tree_nodes_does_not_mutate_the_input_list() -> None:
    """The input list keeps its order; a new sorted list is returned"""
    first = _make_node(1, SUBNET_RANGE_SIBLING)
    second = _make_node(2, SUBNET_RANGE_BROAD)
    nodes = [first, second]

    result = sort_tree_nodes(nodes)

    assert nodes == [first, second]
    assert result == [second, first]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                nest_subnet_nodes                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_nest_subnet_nodes_nests_by_strict_cidr_containment() -> None:
    """A /24 inside a /16 nests under it; an unrelated /16 stays a root sibling"""
    broad = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_BROAD)
    nested = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_NESTED)
    sibling = _make_node(SUBNET_OBJECT_ID_C, SUBNET_RANGE_SIBLING)

    roots = nest_subnet_nodes([sibling, nested, broad])

    assert [n[CmdbObjectKey.PUBLIC_ID] for n in roots] == [SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_C]
    assert broad[IpamTreeKey.CHILDREN] == [nested]
    assert nested[IpamTreeKey.CHILDREN] == []
    assert sibling[IpamTreeKey.CHILDREN] == []


def test_nest_subnet_nodes_links_to_the_most_specific_enclosing_node() -> None:
    """With /8 -> /16 -> /24 all present, the /24 nests under the /16, not the /8"""
    top = _make_node(SUBNET_OBJECT_ID_A, SUPERNET_RANGE)
    middle = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_BROAD)
    leaf = _make_node(SUBNET_OBJECT_ID_C, SUBNET_RANGE_NESTED)

    roots = nest_subnet_nodes([leaf, top, middle])

    assert roots == [top]
    assert top[IpamTreeKey.CHILDREN] == [middle]
    assert middle[IpamTreeKey.CHILDREN] == [leaf]


def test_nest_subnet_nodes_treats_equal_cidrs_as_siblings() -> None:
    """Two nodes with the identical CIDR do not nest into each other"""
    first = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_BROAD)
    duplicate = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_BROAD)

    roots = nest_subnet_nodes([first, duplicate])

    assert len(roots) == 2
    assert first[IpamTreeKey.CHILDREN] == []
    assert duplicate[IpamTreeKey.CHILDREN] == []


def test_nest_subnet_nodes_never_links_across_families() -> None:
    """An IPv6 node stays a root next to IPv4 nodes and the roots keep IPv4 first"""
    v4 = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_BROAD)
    v6 = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6)

    roots = nest_subnet_nodes([v6, v4])

    assert roots == [v4, v6]
    assert v4[IpamTreeKey.CHILDREN] == []
    assert v6[IpamTreeKey.CHILDREN] == []


def test_nest_subnet_nodes_returns_unparsable_nodes_as_trailing_roots() -> None:
    """A node without a parsable CIDR becomes a root with empty children, after parsable roots"""
    parsable = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_BROAD)
    unparsable = _make_node(SUBNET_OBJECT_ID_B, UNPARSABLE_RANGE, name=SUBNET_NAME_B)

    roots = nest_subnet_nodes([unparsable, parsable])

    assert roots == [parsable, unparsable]
    assert unparsable[IpamTreeKey.CHILDREN] == []


def test_nest_subnet_nodes_keeps_children_in_ascending_cidr_order() -> None:
    """Children of one parent come back ascending by network address"""
    parent = _make_node(SUBNET_OBJECT_ID_A, SUPERNET_RANGE)
    child_high = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_SIBLING)
    child_low = _make_node(SUBNET_OBJECT_ID_C, SUBNET_RANGE_BROAD)

    nest_subnet_nodes([parent, child_high, child_low])

    assert parent[IpamTreeKey.CHILDREN] == [child_low, child_high]


# -------------------------------------------------------------------------------------------------------------------- #
#                                          load_all_special_type_objects                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_all_special_type_objects_pins_the_type_id_criteria() -> None:
    """The loader queries exactly {type_id: <resolved id>} with as_dict=True"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=SUBNET_TYPE_ID) as mock_resolve:
        result = load_all_special_type_objects(objects_manager, types_manager, SpecialType.SUBNET)

    mock_resolve.assert_called_once_with(types_manager, SpecialType.SUBNET)
    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID}, as_dict=True,
    )
    assert result == []


def test_load_all_special_type_objects_returns_empty_when_type_undefined() -> None:
    """An installation without the SpecialType yields [] without querying objects"""
    objects_manager = MagicMock()

    with patch(f'{PATH}.resolve_special_type_id', return_value=None):
        result = load_all_special_type_objects(objects_manager, MagicMock(), SpecialType.SUPERNET)

    assert result == []
    objects_manager.find_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 build_ipam_tree                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_ipam_tree_assembles_sorted_supernets_and_unassigned_blocks() -> None:
    """Supernets carry has_children from the subnet refs; only unassigned subnets are listed"""
    supernet_with = _make_supernet_doc(SUPERNET_OBJECT_ID, network_range=SUBNET_RANGE_SIBLING)
    supernet_without = _make_supernet_doc(SUPERNET_OBJECT_ID + 1, network_range=SUBNET_RANGE_BROAD)
    assigned = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_NESTED, supernet_ref=SUPERNET_OBJECT_ID)
    orphan = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_BROAD)

    with patch(
        f'{PATH}.load_all_special_type_objects',
        side_effect=[[supernet_with, supernet_without], [assigned, orphan]],
    ) as mock_load:
        tree = build_ipam_tree(MagicMock(), MagicMock())

    assert mock_load.call_count == 2
    assert [s[CmdbObjectKey.PUBLIC_ID] for s in tree[IpamTreeKey.SUPERNETS]] == [
        SUPERNET_OBJECT_ID + 1, SUPERNET_OBJECT_ID,
    ]
    assert tree[IpamTreeKey.SUPERNETS][0][IpamTreeKey.HAS_CHILDREN] is False
    assert tree[IpamTreeKey.SUPERNETS][1][IpamTreeKey.HAS_CHILDREN] is True
    assert [s[CmdbObjectKey.PUBLIC_ID] for s in tree[IpamTreeKey.UNASSIGNED]] == [SUBNET_OBJECT_ID_B]
    # Each family carries its own resolved type icon
    assert tree[IpamTreeKey.SUPERNETS][0][IpamTreeKey.ICON] == SUPERNET_ICON
    assert tree[IpamTreeKey.UNASSIGNED][0][IpamTreeKey.ICON] == SUBNET_ICON


def test_build_ipam_tree_loads_supernets_then_subnets() -> None:
    """The two type-scoped loads request SUPERNET and SUBNET objects respectively"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}.load_all_special_type_objects', side_effect=[[], []]) as mock_load:
        tree = build_ipam_tree(objects_manager, types_manager)

    assert mock_load.call_args_list[0].args == (objects_manager, types_manager, SpecialType.SUPERNET)
    assert mock_load.call_args_list[1].args == (objects_manager, types_manager, SpecialType.SUBNET)
    assert tree == {IpamTreeKey.SUPERNETS: [], IpamTreeKey.UNASSIGNED: []}


def test_build_ipam_tree_keeps_unassigned_flat_without_children_keys() -> None:
    """Unassigned nodes carry no 'children' / 'has_children' keys - the block is a flat list"""
    orphan_parent_range = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_BROAD)
    orphan_child_range = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_NESTED)

    with patch(
        f'{PATH}.load_all_special_type_objects',
        side_effect=[[], [orphan_parent_range, orphan_child_range]],
    ):
        tree = build_ipam_tree(MagicMock(), MagicMock())

    assert len(tree[IpamTreeKey.UNASSIGNED]) == 2

    for node in tree[IpamTreeKey.UNASSIGNED]:
        assert IpamTreeKey.CHILDREN not in node
        assert IpamTreeKey.HAS_CHILDREN not in node


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_supernet_subnet_tree                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_supernet_subnet_tree_validates_then_nests_the_assigned_subnets() -> None:
    """The supernet is validated first; the assigned subnets come back CIDR-nested"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    broad = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_BROAD, name=SUBNET_NAME_A)
    nested = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_NESTED, name=SUBNET_NAME_B)

    with patch(f'{PATH}.load_supernet_object') as mock_validate, \
         patch(f'{PATH}.load_subnets_for_supernet', return_value=[nested, broad]) as mock_load:
        subtree = build_supernet_subnet_tree(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    mock_validate.assert_called_once_with(objects_manager, types_manager, SUPERNET_OBJECT_ID)
    mock_load.assert_called_once_with(objects_manager, types_manager, SUPERNET_OBJECT_ID)

    roots = subtree[IpamTreeKey.CHILDREN]
    assert [n[CmdbObjectKey.PUBLIC_ID] for n in roots] == [SUBNET_OBJECT_ID_A]
    assert [n[CmdbObjectKey.PUBLIC_ID] for n in roots[0][IpamTreeKey.CHILDREN]] == [SUBNET_OBJECT_ID_B]


def test_build_supernet_subnet_tree_returns_empty_children_for_a_bare_supernet() -> None:
    """A supernet without assigned subnets yields {'children': []} rather than erroring"""
    with patch(f'{PATH}.load_supernet_object'), \
         patch(f'{PATH}.load_subnets_for_supernet', return_value=[]):
        subtree = build_supernet_subnet_tree(MagicMock(), MagicMock(), SUPERNET_OBJECT_ID)

    assert subtree == {IpamTreeKey.CHILDREN: []}


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_unassigned_subnets                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_unassigned_subnets_filters_and_sorts_the_orphans() -> None:
    """Only subnets without a usable ref are listed, in display order, under 'unassigned'"""
    assigned = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_BROAD, supernet_ref=SUPERNET_OBJECT_ID)
    orphan_high = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_SIBLING)
    orphan_low = _make_subnet_doc(SUBNET_OBJECT_ID_C, network_range=SUBNET_RANGE_NESTED)

    with patch(
        f'{PATH}.load_all_special_type_objects',
        return_value=[assigned, orphan_high, orphan_low],
    ) as mock_load:
        result = build_unassigned_subnets(MagicMock(), MagicMock())

    assert mock_load.call_args.args[2] == SpecialType.SUBNET
    assert [n[CmdbObjectKey.PUBLIC_ID] for n in result[IpamTreeKey.UNASSIGNED]] == [
        SUBNET_OBJECT_ID_C, SUBNET_OBJECT_ID_B,
    ]
