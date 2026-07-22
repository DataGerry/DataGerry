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
Unit tests for cmdb.framework.ipam.subnet_options

Covers the two pure filter helpers (family equality, name / CIDR substring search with the
shared activation rule) and the orchestrator build_subnet_options_page. For the orchestrator
the loader is patched at the module path; node shaping, family resolution and display-order
sorting are exercised for real through subnet_tree_node / sort_tree_nodes, which have their
own dedicated tests in test_tree_overview
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import (
    SubnetField,
    IpAddressFamily,
    IpamPagination,
    IpamSearch,
    IpamOverviewKey,
    IpamTreeKey,
)
from cmdb.framework.ipam.subnet_options import (
    build_subnet_options_page,
    filter_nodes_by_family,
    filter_nodes_by_search,
)
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID_A: int = 201
SUBNET_OBJECT_ID_B: int = 202
SUBNET_OBJECT_ID_C: int = 203

SUBNET_RANGE_V4_LOW: str = '10.1.0.0/16'
SUBNET_RANGE_V4_HIGH: str = '10.2.0.0/16'
SUBNET_RANGE_V6: str = '2001:db8::/48'
UNPARSABLE_RANGE: str = 'not-a-cidr'

SUBNET_NAME_A: str = 'Core'
SUBNET_NAME_B: str = 'Mgmt'

PATH: str = 'cmdb.framework.ipam.subnet_options'

SUBNET_ICON: str = 'fas fa-network-wired'


@pytest.fixture(autouse=True)
def _stub_special_type_icon():
    """Stubs resolve_special_type_icon so the picker builder does not hit the DB for the icon."""
    with patch(f'{PATH}.resolve_special_type_icon', return_value=SUBNET_ICON):
        yield


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   FIXTURES                                                           #
# -------------------------------------------------------------------------------------------------------------------- #
def _make_node(
    public_id: int,
    cidr: Any = None,
    family: str = IpAddressFamily.IPV4,
    name: Any = None,
) -> dict[str, Any]:
    """Builds an already-shaped subnet option node for the filter helpers."""
    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        IpamTreeKey.NAME: name,
        IpamTreeKey.CIDR: cidr,
        IpamTreeKey.TYPE: family,
    }


def _make_subnet_doc(
    public_id: int,
    network_range: Any = None,
    name: Any = None,
    subnet_type: Any = None,
) -> dict[str, Any]:
    """Builds a SUBNET CmdbObject doc with optional range / name / type-selector fields."""
    fields: list[dict[str, Any]] = []

    if network_range is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.NETWORK_RANGE, CmdbObjectFieldKey.VALUE: network_range})

    if name is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.NAME, CmdbObjectFieldKey.VALUE: name})

    if subnet_type is not None:
        fields.append({CmdbObjectFieldKey.NAME: SubnetField.TYPE, CmdbObjectFieldKey.VALUE: subnet_type})

    return {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
        CmdbObjectKey.FIELDS: fields,
    }


# -------------------------------------------------------------------------------------------------------------------- #
#                                              filter_nodes_by_family                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_filter_nodes_by_family_keeps_only_the_requested_family() -> None:
    """Only nodes whose 'type' equals the requested family survive the filter"""
    v4 = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_V4_LOW)
    v6 = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6)

    assert filter_nodes_by_family([v4, v6], IpAddressFamily.IPV6) == [v6]
    assert filter_nodes_by_family([v4, v6], IpAddressFamily.IPV4) == [v4]


def test_filter_nodes_by_family_deactivates_on_empty_token() -> None:
    """An empty family token returns every node in a new list"""
    nodes = [
        _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_V4_LOW),
        _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6),
    ]

    result = filter_nodes_by_family(nodes, '')

    assert result == nodes
    assert result is not nodes


# -------------------------------------------------------------------------------------------------------------------- #
#                                              filter_nodes_by_search                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_filter_nodes_by_search_matches_name_and_cidr_case_insensitively() -> None:
    """The needle matches against the name OR the CIDR, ignoring case"""
    by_name = _make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_V4_LOW, name=SUBNET_NAME_A)
    by_cidr = _make_node(SUBNET_OBJECT_ID_B, SUBNET_RANGE_V6, family=IpAddressFamily.IPV6)
    no_hit = _make_node(SUBNET_OBJECT_ID_C, SUBNET_RANGE_V4_HIGH, name=SUBNET_NAME_B)

    assert filter_nodes_by_search([by_name, by_cidr, no_hit], 'cOrE') == [by_name]
    assert filter_nodes_by_search([by_name, by_cidr, no_hit], 'db8') == [by_cidr]


def test_filter_nodes_by_search_deactivates_below_min_query_length() -> None:
    """Queries shorter than IpamSearch.MIN_QUERY_LENGTH (after stripping) return every node"""
    nodes = [_make_node(SUBNET_OBJECT_ID_A, SUBNET_RANGE_V4_LOW, name=SUBNET_NAME_A)]
    short_query: str = 'x' * (IpamSearch.MIN_QUERY_LENGTH - 1)

    assert filter_nodes_by_search(nodes, short_query) == nodes
    assert filter_nodes_by_search(nodes, '   ') == nodes


def test_filter_nodes_by_search_skips_nodes_without_name_and_cidr() -> None:
    """A node whose name and cidr are both None never matches an active search"""
    bare = _make_node(SUBNET_OBJECT_ID_A)

    assert not filter_nodes_by_search([bare], SUBNET_NAME_A)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            build_subnet_options_page                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_subnet_options_page_loads_subnets_and_shapes_sorted_rows() -> None:
    """All SUBNET objects are loaded once and come back as sorted lightweight option rows"""
    objects_manager = MagicMock()
    types_manager = MagicMock()
    docs = [
        _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_V4_HIGH),
        _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V4_LOW, name=SUBNET_NAME_A),
    ]

    with patch(f'{PATH}.load_all_special_type_objects', return_value=docs) as mock_load:
        result = build_subnet_options_page(
            objects_manager, types_manager, page=1, page_size=10, search='',
        )

    mock_load.assert_called_once_with(objects_manager, types_manager, SpecialType.SUBNET)
    assert result[IpamOverviewKey.TOTAL] == 2
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result[IpamOverviewKey.ROWS]] == [
        SUBNET_OBJECT_ID_A, SUBNET_OBJECT_ID_B,
    ]
    assert result[IpamOverviewKey.ROWS][0] == {
        CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID_A,
        IpamTreeKey.NAME: SUBNET_NAME_A,
        IpamTreeKey.CIDR: SUBNET_RANGE_V4_LOW,
        IpamTreeKey.TYPE: IpAddressFamily.IPV4,
        IpamTreeKey.ICON: SUBNET_ICON,
    }


def test_build_subnet_options_page_filters_by_family_cidr_first() -> None:
    """The family filter uses the CIDR-first resolution: a v6 CIDR with a v4 selector is ipv6"""
    contradicting = _make_subnet_doc(
        SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V6, subnet_type=IpAddressFamily.IPV4,
    )
    legacy_default = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=UNPARSABLE_RANGE)
    plain_v4 = _make_subnet_doc(SUBNET_OBJECT_ID_C, network_range=SUBNET_RANGE_V4_LOW)

    with patch(f'{PATH}.load_all_special_type_objects', return_value=[contradicting, legacy_default, plain_v4]):
        v6_page = build_subnet_options_page(
            MagicMock(), MagicMock(), page=1, page_size=10, search='', family=IpAddressFamily.IPV6,
        )
        v4_page = build_subnet_options_page(
            MagicMock(), MagicMock(), page=1, page_size=10, search='', family=IpAddressFamily.IPV4,
        )

    assert [r[CmdbObjectKey.PUBLIC_ID] for r in v6_page[IpamOverviewKey.ROWS]] == [SUBNET_OBJECT_ID_A]
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in v4_page[IpamOverviewKey.ROWS]] == [
        SUBNET_OBJECT_ID_C, SUBNET_OBJECT_ID_B,
    ]
    assert v6_page[IpamOverviewKey.TYPE] == IpAddressFamily.IPV6


def test_build_subnet_options_page_applies_search_after_the_family_filter() -> None:
    """total reflects the post-filter count; search narrows within the family selection"""
    match = _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V4_LOW, name=SUBNET_NAME_A)
    no_match = _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_V4_HIGH, name=SUBNET_NAME_B)
    wrong_family = _make_subnet_doc(SUBNET_OBJECT_ID_C, network_range=SUBNET_RANGE_V6, name=SUBNET_NAME_A)

    with patch(f'{PATH}.load_all_special_type_objects', return_value=[match, no_match, wrong_family]):
        result = build_subnet_options_page(
            MagicMock(), MagicMock(), page=1, page_size=10,
            search=SUBNET_NAME_A, family=IpAddressFamily.IPV4,
        )

    assert result[IpamOverviewKey.TOTAL] == 1
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result[IpamOverviewKey.ROWS]] == [SUBNET_OBJECT_ID_A]
    assert result[IpamOverviewKey.SEARCH] == SUBNET_NAME_A


def test_build_subnet_options_page_clamps_pagination_and_slices() -> None:
    """An out-of-range page resolves to the last valid page; the slice honours page_size"""
    docs = [
        _make_subnet_doc(SUBNET_OBJECT_ID_A, network_range=SUBNET_RANGE_V4_LOW),
        _make_subnet_doc(SUBNET_OBJECT_ID_B, network_range=SUBNET_RANGE_V4_HIGH),
        _make_subnet_doc(SUBNET_OBJECT_ID_C, network_range=SUBNET_RANGE_V6),
    ]

    with patch(f'{PATH}.load_all_special_type_objects', return_value=docs):
        result = build_subnet_options_page(
            MagicMock(), MagicMock(), page=99, page_size=2, search='',
        )

    assert result[IpamOverviewKey.PAGE] == 2
    assert result[IpamOverviewKey.PAGE_SIZE] == 2
    assert result[IpamOverviewKey.TOTAL] == 3
    assert [r[CmdbObjectKey.PUBLIC_ID] for r in result[IpamOverviewKey.ROWS]] == [SUBNET_OBJECT_ID_C]


def test_build_subnet_options_page_collapses_to_empty_envelope_without_subnets() -> None:
    """No SUBNET objects (or no SUBNET CmdbType) yields an empty page envelope, no error"""
    with patch(f'{PATH}.load_all_special_type_objects', return_value=[]):
        result = build_subnet_options_page(
            MagicMock(), MagicMock(),
            page=1, page_size=IpamPagination.DEFAULT_PAGE_SIZE, search='',
        )

    assert result == {
        IpamOverviewKey.PAGE: 1,
        IpamOverviewKey.PAGE_SIZE: IpamPagination.DEFAULT_PAGE_SIZE,
        IpamOverviewKey.TOTAL: 0,
        IpamOverviewKey.SEARCH: '',
        IpamOverviewKey.TYPE: '',
        IpamOverviewKey.ROWS: [],
    }
