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
The materialised scope block of an object (``_scope``) - what it is built from and how, without a read

An object's block is derived from three things: where it is placed (the location parent its location field names, a
CmdbLocation node id), the subnets and addresses of its ``dg-ipam-interface`` rows, and the supernets of those
subnets. The two facts outside the object - the location chain above a node and a subnet's supernet - are read by the
caller (``cmdb.manager.object_scope_blocks``) and handed in, so the block is computed the same way for a stored object
and for a state about to be written. The ``related`` list is no fact of the document at all: it is read from the object
relations naming the object's id (the caller hands it in, empty for an object without an id).

Every interface row counts, active or not (R19). An address is encoded as fixed-width lowercase hex behind its
version, ``4:`` + 8 and ``6:`` + 32 digits, so text order is numeric order and a CIDR is one range per version
"""
import ipaddress
from collections.abc import Mapping
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
    CmdbObjectScopeKey,
    CmdbObjectScopeRelatedKey,
)
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationKey
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.models.type_model.field_type_enum import FieldType
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'scope_path',
    'encode_ip',
    'network_bounds',
    'location_entry',
    'interface_subnets',
    'interface_addresses',
    'related_entries',
    'build_scope_block',
]

# Hex digits of an encoded address per IP version, and the separator behind the version
_HEX_WIDTH: dict[int, int] = {4: 8, 6: 32}
_VERSION_SEPARATOR: str = ':'


def scope_path(key: CmdbObjectScopeKey) -> str:
    """
    The dotted path of one list of the block

    Args:
        key (CmdbObjectScopeKey): LOCATIONS, NETWORKS or IPS

    Returns:
        str: e.g. ``_scope.locations``
    """
    return f'{CmdbObjectScopeKey.BLOCK.value}.{key.value}'


def encode_ip(value: Any) -> str | None:
    """
    An address in its block form

    Args:
        value (Any): The stored address text

    Returns:
        str | None: ``4:`` + 8 or ``6:`` + 32 lowercase hex digits; None for anything that is no address
    """
    if not isinstance(value, str):
        return None

    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None

    return _encode(address.version, int(address))


def network_bounds(cidr: str) -> tuple[str, str]:
    """
    The first and the last address of a CIDR in their block form

    Args:
        cidr (str): A CIDR (host bits allowed)

    Raises:
        ValueError: When the text is no CIDR

    Returns:
        tuple[str, str]: The encoded lower and upper bound, both inclusive
    """
    network = ipaddress.ip_network(cidr, strict=False)

    return (_encode(network.version, int(network.network_address)),
            _encode(network.version, int(network.broadcast_address)))


def _encode(version: int, number: int) -> str:
    """
    The block form of an address number

    Args:
        version (int): 4 or 6
        number (int): The address as a number

    Returns:
        str: The version, the separator and the fixed-width hex digits
    """
    return f'{version}{_VERSION_SEPARATOR}{number:0{_HEX_WIDTH[version]}x}'


def location_entry(document: Mapping[str, Any]) -> tuple[bool, int | None]:
    """
    The location field entry of a document

    Args:
        document (Mapping[str, Any]): An object document or state

    Returns:
        tuple[bool, int | None]: Whether it carries one, and the node it names (None when unplaced)
    """
    for entry in document.get(CmdbObjectKey.FIELDS.value) or []:
        if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.TYPE.value) == FieldType.LOCATION:
            return True, _node_id(entry.get(CmdbObjectFieldKey.VALUE.value))

    return False, None


def _node_id(value: Any) -> int | None:
    """
    A usable node id

    Args:
        value (Any): A stored value

    Returns:
        int | None: The id; None for anything that is no positive whole number
    """
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value

    return None


def _interface_rows(document: Mapping[str, Any]) -> list[list[Any]]:
    """
    The data of every ``dg-ipam-interface`` row of a document

    Args:
        document (Mapping[str, Any]): An object document or state

    Returns:
        list[list[Any]]: Each row's field entries
    """
    rows: list[list[Any]] = []

    for section in document.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        if not isinstance(section, dict) or section.get(CmdbObjectMdsKey.SECTION_ID.value) != IpamSection.INTERFACE:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value) or []:
            if isinstance(row, dict) and isinstance(row.get(CmdbObjectMdsRowKey.DATA.value), list):
                rows.append(row[CmdbObjectMdsRowKey.DATA.value])

    return rows


def _row_values(document: Mapping[str, Any], field_name: str) -> list[Any]:
    """
    The value one interface field has in every row

    Args:
        document (Mapping[str, Any]): An object document or state
        field_name (str): The interface field

    Returns:
        list[Any]: The values, in row order
    """
    return [entry.get(CmdbObjectFieldKey.VALUE.value) for data in _interface_rows(document) for entry in data
            if isinstance(entry, dict) and entry.get(CmdbObjectFieldKey.NAME.value) == field_name]


def interface_subnets(document: Mapping[str, Any]) -> list[int]:
    """
    The subnets a document's interface rows name

    Args:
        document (Mapping[str, Any]): An object document or state

    Returns:
        list[int]: Their ids, ascending, once each
    """
    return sorted({subnet for subnet in map(_node_id, _row_values(document, InterfaceField.SUBNET.value)) if subnet})


def interface_addresses(document: Mapping[str, Any]) -> list[str]:
    """
    The addresses of a document's interface rows, encoded

    Args:
        document (Mapping[str, Any]): An object document or state

    Returns:
        list[str]: The encoded addresses, ascending, once each; text that is no address is left out
    """
    return sorted({encoded for encoded in map(encode_ip, _row_values(document, InterfaceField.IP.value)) if encoded})


def related_entries(object_id: Any, relations: list[Mapping[str, Any]]) -> list[dict[str, int]]:
    """
    The ``related`` list of an object from the object relations naming it - the other end of each, either direction

    Args:
        object_id (Any): The object's id
        relations (list[Mapping[str, Any]]): Object relation documents (parent, child and relation ids)

    Returns:
        list[dict[str, int]]: ``{object, relation}`` entries, sorted, once each
    """
    entries: set[tuple[int, int]] = set()

    for relation in relations:
        parent: Any = relation.get(ObjectRelationKey.RELATION_PARENT_ID.value)
        child: Any = relation.get(ObjectRelationKey.RELATION_CHILD_ID.value)
        definition: Any = relation.get(ObjectRelationKey.RELATION_ID.value)
        other: Any = child if parent == object_id else parent if child == object_id else None

        if _node_id(other) and _node_id(definition):
            entries.add((other, definition))

    return [{CmdbObjectScopeRelatedKey.OBJECT.value: other, CmdbObjectScopeRelatedKey.RELATION.value: definition}
            for other, definition in sorted(entries)]


def build_scope_block(document: Mapping[str, Any], location_chain: list[int], supernets: Mapping[int, int],
                      related: list[dict[str, int]] | None = None) -> dict[str, list[Any]]:
    """
    A document's block

    Args:
        document (Mapping[str, Any]): An object document or state
        location_chain (list[int]): The object ids of the location the document is placed in and of every location
            above it - empty when unplaced
        supernets (Mapping[int, int]): The supernet of each subnet that has one
        related (list[dict[str, int]] | None): The ``related`` entries (``related_entries``). Defaults to None (none)

    Returns:
        dict[str, list[Any]]: ``locations``, ``networks``, ``ips`` and ``related``, each ascending, once each
    """
    subnets: list[int] = interface_subnets(document)

    return {
        CmdbObjectScopeKey.LOCATIONS.value: sorted(set(location_chain)),
        CmdbObjectScopeKey.NETWORKS.value: sorted({*subnets, *(supernets[subnet] for subnet in subnets
                                                               if subnet in supernets)}),
        CmdbObjectScopeKey.IPS.value: interface_addresses(document),
        CmdbObjectScopeKey.RELATED.value: list(related or []),
    }
