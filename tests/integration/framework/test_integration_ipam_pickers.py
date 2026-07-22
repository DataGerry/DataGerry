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
Integration tests for the IPAM picker / sidebar builders against a real MongoDB

Pins the DB-touching behaviour the unit tests only mock: the sidebar tree's type-scoped
loads and dg-supernet-ref based has_children / unassigned classification
(build_ipam_tree, build_supernet_subnet_tree, build_unassigned_subnets), the family-filtered
subnet-options page backing the interface picker (build_subnet_options_page), and the
assignable-objects page incl. the real render_meta.sections $elemMatch capable-type discovery
(find_ipam_capable_type_ids / build_assignable_objects_page)
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SupernetField,
    SubnetField,
    IpamSection,
    IpAddressFamily,
    IpamOverviewKey,
    IpamTreeKey,
)
from cmdb.framework.ipam.tree_overview import (
    build_ipam_tree,
    build_supernet_subnet_tree,
    build_unassigned_subnets,
)
from cmdb.framework.ipam.subnet_options import build_subnet_options_page
from cmdb.framework.ipam.assignable_objects import (
    build_assignable_objects_page,
    find_ipam_capable_type_ids,
)
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUPERNET_TYPE_ID: int = 9710
SUBNET_TYPE_ID: int = 9711
CAPABLE_TYPE_ID: int = 9712
PLAIN_TYPE_ID: int = 9713

SUPERNET_V4_ID: int = 9720
SUPERNET_V6_ID: int = 9721
SUBNET_BROAD_ID: int = 9722    # 10.1.0.0/16 under the v4 supernet
SUBNET_NESTED_ID: int = 9723   # 10.1.4.0/24, CIDR-child of the broad subnet
SUBNET_V6_ID: int = 9724       # assigned to the v6 supernet
SUBNET_ORPHAN_ID: int = 9725   # no dg-supernet-ref
CAPABLE_OBJECT_ID: int = 9726
PLAIN_OBJECT_ID: int = 9727

SUPERNET_V4_RANGE: str = '10.0.0.0/8'
SUPERNET_V6_RANGE: str = '2001:db8::/32'
SUBNET_BROAD_RANGE: str = '10.1.0.0/16'
SUBNET_NESTED_RANGE: str = '10.1.4.0/24'
SUBNET_V6_RANGE: str = '2001:db8:1::/48'
SUBNET_ORPHAN_RANGE: str = '192.168.0.0/16'

ORPHAN_NAME: str = 'picker-orphan'
NESTED_NAME: str = 'picker-nested'

TYPE_IDS: list[int] = [SUPERNET_TYPE_ID, SUBNET_TYPE_ID, CAPABLE_TYPE_ID, PLAIN_TYPE_ID]
OBJECT_IDS: list[int] = [
    SUPERNET_V4_ID, SUPERNET_V6_ID, SUBNET_BROAD_ID, SUBNET_NESTED_ID,
    SUBNET_V6_ID, SUBNET_ORPHAN_ID, CAPABLE_OBJECT_ID, PLAIN_OBJECT_ID,
]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
INTERFACE_SECTION_LAYOUT: dict[str, Any] = {
    'name': IpamSection.INTERFACE,
    'type': 'multi-data-section',
    'label': 'IPAM Interface',
}


def _subnet_doc(public_id: int, name: str, cidr: str, supernet_ref: int | None) -> dict[str, Any]:
    """Builds a SUBNET object doc with an optional parent supernet reference."""
    fields = [
        make_field(SubnetField.NAME, name),
        make_field(SubnetField.NETWORK_RANGE, cidr),
    ]

    if supernet_ref is not None:
        fields.append(make_field(SubnetField.PARENT_SUPERNET, supernet_ref))

    return make_object_doc(public_id, SUBNET_TYPE_ID, fields)


@pytest.fixture(scope='module', autouse=True)
def _seed_picker_topology(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds two supernets, four subnets (nested / v6 / orphan) and two picker objects."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    types.insert_many([
        make_type_doc(SUPERNET_TYPE_ID, 'it-picker-supernet', SpecialType.SUPERNET),
        make_type_doc(SUBNET_TYPE_ID, 'it-picker-subnet', SpecialType.SUBNET),
        make_type_doc(CAPABLE_TYPE_ID, 'it-picker-capable', None, sections=[INTERFACE_SECTION_LAYOUT]),
        make_type_doc(PLAIN_TYPE_ID, 'it-picker-plain', None),
    ])

    objects.insert_many([
        make_object_doc(SUPERNET_V4_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'picker-sn4'),
            make_field(SupernetField.NETWORK_RANGE, SUPERNET_V4_RANGE),
        ]),
        make_object_doc(SUPERNET_V6_ID, SUPERNET_TYPE_ID, [
            make_field(SupernetField.NAME, 'picker-sn6'),
            make_field(SupernetField.NETWORK_RANGE, SUPERNET_V6_RANGE),
        ]),
        _subnet_doc(SUBNET_BROAD_ID, 'picker-broad', SUBNET_BROAD_RANGE, SUPERNET_V4_ID),
        _subnet_doc(SUBNET_NESTED_ID, NESTED_NAME, SUBNET_NESTED_RANGE, SUPERNET_V4_ID),
        _subnet_doc(SUBNET_V6_ID, 'picker-sub6', SUBNET_V6_RANGE, SUPERNET_V6_ID),
        _subnet_doc(SUBNET_ORPHAN_ID, ORPHAN_NAME, SUBNET_ORPHAN_RANGE, None),
        make_object_doc(CAPABLE_OBJECT_ID, CAPABLE_TYPE_ID, [make_field('dg-name', 'picker-host')]),
        make_object_doc(PLAIN_OBJECT_ID, PLAIN_TYPE_ID, [make_field('dg-name', 'picker-site')]),
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


def _ids(nodes: list[dict[str, Any]]) -> list[int]:
    """Returns the public_ids of a node list in order."""
    return [n[CmdbObjectKey.PUBLIC_ID] for n in nodes]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  SIDEBAR TREE                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_ipam_tree_lists_sorted_supernets_with_has_children_and_orphans(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The initial payload: v4 before v6 supernets, ref-derived has_children, flat orphan block"""
    tree = build_ipam_tree(objects_manager, types_manager)

    assert _ids(tree[IpamTreeKey.SUPERNETS]) == [SUPERNET_V4_ID, SUPERNET_V6_ID]
    assert all(s[IpamTreeKey.HAS_CHILDREN] is True for s in tree[IpamTreeKey.SUPERNETS])

    assert _ids(tree[IpamTreeKey.UNASSIGNED]) == [SUBNET_ORPHAN_ID]
    orphan = tree[IpamTreeKey.UNASSIGNED][0]
    assert orphan[IpamTreeKey.NAME] == ORPHAN_NAME
    assert IpamTreeKey.CHILDREN not in orphan


def test_supernet_subnet_tree_nests_by_cidr_from_the_real_ref_query(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The v4 supernet's subtree nests the /24 under the /16 loaded via dg-supernet-ref"""
    subtree = build_supernet_subnet_tree(objects_manager, types_manager, SUPERNET_V4_ID)

    roots = subtree[IpamTreeKey.CHILDREN]
    assert _ids(roots) == [SUBNET_BROAD_ID]
    assert _ids(roots[0][IpamTreeKey.CHILDREN]) == [SUBNET_NESTED_ID]
    assert roots[0][IpamTreeKey.CHILDREN][0][IpamTreeKey.TYPE] == IpAddressFamily.IPV4


def test_unassigned_subnets_returns_only_the_orphan(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """The targeted-refresh route's builder lists exactly the subnet without a supernet ref"""
    result = build_unassigned_subnets(objects_manager, types_manager)

    assert _ids(result[IpamTreeKey.UNASSIGNED]) == [SUBNET_ORPHAN_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 SUBNET OPTIONS                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_subnet_options_family_filter_against_real_documents(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """ipv4 returns the three v4 subnets in CIDR order; ipv6 returns only the v6 subnet"""
    v4_page = build_subnet_options_page(
        objects_manager, types_manager, page=1, page_size=10, search='', family=IpAddressFamily.IPV4,
    )
    v6_page = build_subnet_options_page(
        objects_manager, types_manager, page=1, page_size=10, search='', family=IpAddressFamily.IPV6,
    )

    assert _ids(v4_page[IpamOverviewKey.ROWS]) == [SUBNET_BROAD_ID, SUBNET_NESTED_ID, SUBNET_ORPHAN_ID]
    assert v4_page[IpamOverviewKey.TOTAL] == 3
    assert _ids(v6_page[IpamOverviewKey.ROWS]) == [SUBNET_V6_ID]


def test_subnet_options_search_matches_the_stored_name(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """A name-fragment search narrows the page to the matching subnet"""
    page = build_subnet_options_page(
        objects_manager, types_manager, page=1, page_size=10, search=NESTED_NAME,
    )

    assert _ids(page[IpamOverviewKey.ROWS]) == [SUBNET_NESTED_ID]
    assert page[IpamOverviewKey.TOTAL] == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                               ASSIGNABLE OBJECTS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_find_ipam_capable_type_ids_uses_the_real_section_query(types_manager: TypesManager) -> None:
    """Only the type whose render_meta.sections carries the interface section is discovered"""
    capable_ids = find_ipam_capable_type_ids(types_manager)

    assert CAPABLE_TYPE_ID in capable_ids
    assert PLAIN_TYPE_ID not in capable_ids


def test_assignable_objects_page_lists_only_capable_type_objects(
    objects_manager: ObjectsManager, types_manager: TypesManager,
) -> None:
    """Objects of the capable type appear with type_info; the plain-type object never does"""
    page = build_assignable_objects_page(objects_manager, types_manager, page=1, page_size=10, search='')

    ids = set(_ids(page[IpamOverviewKey.ROWS]))
    assert CAPABLE_OBJECT_ID in ids
    assert PLAIN_OBJECT_ID not in ids

    row = next(r for r in page[IpamOverviewKey.ROWS] if r[CmdbObjectKey.PUBLIC_ID] == CAPABLE_OBJECT_ID)
    assert row[IpamOverviewKey.TYPE_INFO][CmdbObjectKey.PUBLIC_ID] == CAPABLE_TYPE_ID
