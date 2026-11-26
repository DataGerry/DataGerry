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
Unit tests for the pure half of the materialised scope block (``object_scope_block``)

Pinned: an address encoded fixed-width behind its version (text order = numeric order, both versions), a CIDR's
inclusive bounds; the location entry found by its field type, an unusable value unplaced; every interface row's subnet
and address counted once, other sections and junk left out; the block's lists sorted, a subnet's supernet added; the
related entries the other end of each object relation, either direction (phase 11)
"""
from typing import Any

import pytest

from cmdb.models.object_model import CmdbObjectScopeKey
from cmdb.models.object_model.object_scope_block import (
    build_scope_block,
    encode_ip,
    interface_addresses,
    interface_subnets,
    location_entry,
    network_bounds,
    related_entries,
    scope_path,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOCATION_NODE: int = 7
SUBNET_A: int = 31
SUBNET_B: int = 32
SUPERNET: int = 40


def _rows(*rows: tuple[Any, Any], section: str = 'dg-ipam-interface') -> list[dict[str, Any]]:
    """One interface section with a row per (subnet, address)"""
    return [{'section_id': section, 'values': [
        {'multi_data_id': index, 'data': [{'name': 'dg-interface-subnet', 'value': subnet, 'type': 'ref'},
                                          {'name': 'dg-interface-ip-address', 'value': address, 'type': 'text'}]}
        for index, (subnet, address) in enumerate(rows)]}]


@pytest.mark.parametrize('value, expected', [
    ('10.0.0.1', '4:0a000001'),
    (' 192.168.1.255 ', '4:c0a801ff'),
    ('::1', '6:00000000000000000000000000000001'),
    ('FD00::A', '6:fd00000000000000000000000000000a'),
    ('10.0.0.256', None), ('', None), (None, None), (167772161, None),
], ids=['v4', 'v4-stripped', 'v6', 'v6-lowered', 'bad', 'empty', 'none', 'number'])
def test_encode_ip(value: Any, expected: str | None) -> None:
    """Fixed width behind the version; anything else is no address"""
    assert encode_ip(value) == expected


def test_text_order_is_numeric_order() -> None:
    """9.x sorts before 10.x - it would not as plain text"""
    assert encode_ip('9.255.255.255') < encode_ip('10.0.0.0') < encode_ip('10.0.0.10') < encode_ip('::')


@pytest.mark.parametrize('cidr, expected', [
    ('10.0.0.0/8', ('4:0a000000', '4:0affffff')),
    ('10.1.2.3/32', ('4:0a010203', '4:0a010203')),
    ('10.1.2.3/24', ('4:0a010200', '4:0a0102ff')),
    ('fd00::/120', ('6:fd000000000000000000000000000000', '6:fd0000000000000000000000000000ff')),
], ids=['v4', 'host', 'host-bits', 'v6'])
def test_network_bounds(cidr: str, expected: tuple[str, str]) -> None:
    """Both bounds inclusive, host bits allowed"""
    assert network_bounds(cidr) == expected


def test_network_bounds_refuses_junk() -> None:
    """The compiler only hands in canonical CIDRs"""
    with pytest.raises(ValueError):
        network_bounds('junk')


def test_scope_path() -> None:
    """Dotted under _scope"""
    assert scope_path(CmdbObjectScopeKey.IPS) == '_scope.ips'


@pytest.mark.parametrize('fields, expected', [
    ([{'name': 'loc', 'type': 'location', 'value': LOCATION_NODE}], (True, LOCATION_NODE)),
    ([{'name': 'loc', 'type': 'location', 'value': None}], (True, None)),
    ([{'name': 'loc', 'type': 'location', 'value': True}], (True, None)),
    ([{'name': 'loc', 'type': 'location', 'value': '7'}], (True, None)),
    ([{'name': 'loc', 'type': 'location', 'value': 0}], (True, None)),
    ([{'name': 'loc', 'type': 'text', 'value': LOCATION_NODE}], (False, None)),
    ([], (False, None)),
], ids=['placed', 'unplaced', 'bool', 'text', 'zero', 'not-a-location-field', 'none'])
def test_location_entry(fields: list[dict[str, Any]], expected: tuple[bool, int | None]) -> None:
    """Found by the field type; only a positive whole number places"""
    assert location_entry({'fields': fields}) == expected


def test_interface_rows_count_once_each() -> None:
    """Duplicates once, junk dropped, sorted; another section's rows do not count"""
    document = {'multi_data_sections': [
        *_rows((SUBNET_B, '10.0.0.2'), (SUBNET_A, '10.0.0.1'), (SUBNET_B, '10.0.0.2'), ('', 'junk'), (None, None)),
        *_rows((99, '1.1.1.1'), section='other')]}

    assert interface_subnets(document) == [SUBNET_A, SUBNET_B]
    assert interface_addresses(document) == ['4:0a000001', '4:0a000002']


def test_a_document_without_rows() -> None:
    """Nothing, also for a malformed section list"""
    for document in ({}, {'multi_data_sections': None}, {'multi_data_sections': ['x', {'values': 'x'}]}):
        assert (interface_subnets(document), interface_addresses(document)) == ([], [])


def test_build_scope_block() -> None:
    """The chain as given, the subnets plus the supernets known for them, the addresses"""
    document = {'multi_data_sections': _rows((SUBNET_A, '10.0.0.1'), (SUBNET_B, '10.0.0.9'))}

    block = build_scope_block(document, [5, 3, 5], {SUBNET_A: SUPERNET, 77: 78})

    assert block == {'locations': [3, 5], 'networks': [SUBNET_A, SUBNET_B, SUPERNET],
                     'ips': ['4:0a000001', '4:0a000009'], 'related': []}


def test_build_scope_block_of_an_empty_document() -> None:
    """Three empty lists - stored like that, never missing"""
    assert build_scope_block({}, [], {}) == {'locations': [], 'networks': [], 'ips': [], 'related': []}


def test_related_entries_take_the_other_end_either_direction() -> None:
    """Parent or child alike; each (object, relation) once, sorted; junk and foreign relations left out"""
    relations = [
        {'relation_id': 3, 'relation_parent_id': 10, 'relation_child_id': 20},
        {'relation_id': 4, 'relation_parent_id': 30, 'relation_child_id': 10},
        {'relation_id': 3, 'relation_parent_id': 10, 'relation_child_id': 20},
        {'relation_id': 5, 'relation_parent_id': 40, 'relation_child_id': 50},
        {'relation_id': None, 'relation_parent_id': 10, 'relation_child_id': 60},
        {'relation_id': 6, 'relation_parent_id': 10},
    ]

    assert related_entries(10, relations) == [{'object': 20, 'relation': 3}, {'object': 30, 'relation': 4}]


def test_build_scope_block_carries_the_related_entries() -> None:
    """As handed in"""
    related = [{'object': 20, 'relation': 3}]

    assert build_scope_block({}, [], {}, related)['related'] == related
