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
Which IPAM interface rows a CmdbPort may still be linked to, and how they are shown in the picker

A link addresses an interface by the triple (object, section, multi_data_id), and nothing about an MDS
row is globally addressable - so without this listing a client has to load every candidate CmdbObject
and walk its `multi_data_sections` itself to find out what it may link to. Each row here therefore
carries that triple verbatim under the same key names the create route reads, and selecting a row is a
copy rather than a translation.

Three rules decide what is offered:

  1. **a row without a `multi_data_id` is not offered** - the id IS the reference, so the create route
     refuses such a row outright; listing it would produce a refusal the picker could have avoided
  2. **a row this port already links is not offered** - the unique index on the identity tuple refuses
     the second link, and the exclusion is the port's OWN links only: the relationship is N:M, so a row
     another port already reaches is a legitimate choice
  3. **only rows of an accessible object are offered** - unlike the Rack and Cable pickers, which list
     names, this one hands out the IP and MAC an object holds, so each candidate object's type must
     pass the caller's READ ACL

The values are resolved rather than passed through: the MDS row's {name, value, type} entries become
named keys and the subnet reference becomes {public_id, name}. That is the deliberate trade of this
module - a field added to the interface template later has to be named here to reach the picker, and in
exchange no consumer needs to know a single `dg-interface-*` field name. The link READ routes keep
handing back the raw row, so nothing that needs the full row lost it.

Pure: every read happens in the route and its result is passed in, so the shaping, the exclusion and
the search are unit-testable without a database
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectFieldKey,
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.object_model.cmdb_object_helpers import extract_field_value
from cmdb.models.port_interface_link_model.port_interface_link_constants import (
    AssignableInterfaceKey,
    AssignableInterfaceObjectKey,
    AssignableInterfaceSubnetKey,
)
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpamOverviewKey,
    IpamSection,
    SubnetField,
)

from cmdb.framework.ipam.pagination import clamp_page
from cmdb.framework.ipam.search import active_search
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The interface field answering each value key of a picker row. Written once as a mapping rather than
# as seven assignments, so naming a newly declared template field here is a one-line change
ROW_KEY_BY_INTERFACE_FIELD: dict[AssignableInterfaceKey, InterfaceField] = {
    AssignableInterfaceKey.ACTIVE: InterfaceField.ACTIVE,
    AssignableInterfaceKey.IP: InterfaceField.IP,
    AssignableInterfaceKey.MAC: InterfaceField.MAC,
    AssignableInterfaceKey.HOSTNAME: InterfaceField.HOST,
    AssignableInterfaceKey.DOMAIN: InterfaceField.DOMAIN,
    AssignableInterfaceKey.ADDRESS_FAMILY: InterfaceField.TYPE,
}

# The row keys a search matches against. The subnet name and the owning object's summary line are
# matched too, because "which interface is this" is answered by the device at least as often as by the
# address - they are added by the caller-facing haystack builder rather than read from the MDS row
SEARCHABLE_ROW_KEYS: tuple[AssignableInterfaceKey, ...] = (
    AssignableInterfaceKey.IP,
    AssignableInterfaceKey.MAC,
    AssignableInterfaceKey.HOSTNAME,
    AssignableInterfaceKey.DOMAIN,
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                                    ROW SHAPING                                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def read_row_value(interface_row: dict[str, Any], field_name: str) -> Any:
    """
    Reads one field value out of an interface MDS row, by name rather than by position

    Args:
        interface_row (dict[str, Any]): One entry of the section's `values` list
        field_name (str): The `dg-interface-*` field to read

    Returns:
        Any: The stored value, or None when the row carries no such entry
    """
    for entry in interface_row.get(CmdbObjectMdsRowKey.DATA.value) or []:
        if entry.get(CmdbObjectFieldKey.NAME.value) == field_name:
            return entry.get(CmdbObjectFieldKey.VALUE.value)

    return None


def interface_rows_of_object(object_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Returns the dg-ipam-interface rows of one CmdbObject

    An object carries at most one interface section, but the lookup is written as a scan so a document
    holding a second interface-bearing section later contributes its rows too

    Args:
        object_doc (dict[str, Any]): The CmdbObject document

    Returns:
        list[dict[str, Any]]: The section's rows, empty when the object carries none
    """
    rows: list[dict[str, Any]] = []

    for section in object_doc.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID.value) == IpamSection.INTERFACE.value:
            rows.extend(section.get(CmdbObjectMdsKey.VALUES.value) or [])

    return rows


def build_subnet_lookup(subnet_docs: list[dict[str, Any]]) -> dict[int, str]:
    """
    Bulk-resolves SUBNET CmdbObjects to their name

    Args:
        subnet_docs (list[dict[str, Any]]): The SUBNET CmdbObject documents the rows reference

    Returns:
        dict[int, str]: {subnet public_id: name} for every subnet that carries one
    """
    return {
        subnet_doc[CmdbObjectKey.PUBLIC_ID.value]: extract_field_value(subnet_doc, SubnetField.NAME.value)
        for subnet_doc in subnet_docs
        if subnet_doc.get(CmdbObjectKey.PUBLIC_ID.value) is not None
    }


def build_assignable_interface_row(
        object_doc: dict[str, Any],
        interface_row: dict[str, Any],
        type_labels: dict[int, str],
        summary_lines: dict[int, str],
        subnet_names: dict[int, str]) -> dict[str, Any]:
    """
    Shapes one picker row from a CmdbObject and one of its interface rows

    Args:
        object_doc (dict[str, Any]): The CmdbObject holding the row
        interface_row (dict[str, Any]): One dg-ipam-interface MDS row
        type_labels (dict[int, str]): {type_id: label}, resolved in bulk by the caller
        summary_lines (dict[int, str]): {object public_id: summary line}, resolved in bulk
        subnet_names (dict[int, str]): {subnet public_id: name}, resolved in bulk

    Returns:
        dict[str, Any]: The picker row - the link triple, the resolved interface values, the referenced
            subnet as {public_id, name} (None when the row references none or it no longer resolves)
            and the owning object under `object_info`
    """
    object_id: Any = object_doc.get(CmdbObjectKey.PUBLIC_ID.value)
    type_id: Any = object_doc.get(CmdbObjectKey.TYPE_ID.value)
    subnet_id: Any = read_row_value(interface_row, InterfaceField.SUBNET.value)

    row: dict[str, Any] = {
        AssignableInterfaceKey.INTERFACE_OBJECT_ID.value: object_id,
        AssignableInterfaceKey.INTERFACE_SECTION_ID.value: IpamSection.INTERFACE.value,
        AssignableInterfaceKey.INTERFACE_MULTI_DATA_ID.value: interface_row.get(
            CmdbObjectMdsRowKey.MULTI_DATA_ID.value),
        AssignableInterfaceKey.SUBNET.value: None,
        AssignableInterfaceKey.OBJECT_INFO.value: {
            AssignableInterfaceObjectKey.PUBLIC_ID.value: object_id,
            AssignableInterfaceObjectKey.TYPE_ID.value: type_id,
            AssignableInterfaceObjectKey.TYPE_LABEL.value: type_labels.get(type_id, ''),
            AssignableInterfaceObjectKey.SUMMARY_LINE.value: summary_lines.get(object_id, ''),
        },
    }

    for row_key, interface_field in ROW_KEY_BY_INTERFACE_FIELD.items():
        row[row_key.value] = read_row_value(interface_row, interface_field.value)

    if isinstance(subnet_id, int) and subnet_id in subnet_names:
        row[AssignableInterfaceKey.SUBNET.value] = {
            AssignableInterfaceSubnetKey.PUBLIC_ID.value: subnet_id,
            AssignableInterfaceSubnetKey.NAME.value: subnet_names[subnet_id],
        }

    return row


# -------------------------------------------------------------------------------------------------------------------- #
#                                              SELECTION AND ASSEMBLY                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def is_offerable(interface_row: dict[str, Any], object_id: Any, linked_rows: set[tuple[Any, Any]]) -> bool:
    """
    Reports whether one interface row may still be offered for this port

    Args:
        interface_row (dict[str, Any]): One dg-ipam-interface MDS row
        object_id (Any): public_id of the CmdbObject holding it
        linked_rows (set[tuple[Any, Any]]): (object_id, multi_data_id) pairs this port already links

    Returns:
        bool: False for a row carrying no multi_data_id, and for a row this port already links
    """
    multi_data_id: Any = interface_row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value)

    if not isinstance(multi_data_id, int):
        return False

    return (object_id, multi_data_id) not in linked_rows


def referenced_subnet_ids(object_docs: list[dict[str, Any]]) -> list[int]:
    """
    Returns the distinct SUBNET public_ids every interface row of the given objects references

    Collected up front so the subnet names cost ONE query for the whole page rather than one per row -
    a device with a bond and four VLAN sub-interfaces on the same subnet would otherwise read it five
    times

    Args:
        object_docs (list[dict[str, Any]]): The candidate CmdbObject documents

    Returns:
        list[int]: The distinct referenced subnet public_ids, empty when no row references one
    """
    subnet_ids: set[int] = set()

    for object_doc in object_docs:
        for interface_row in interface_rows_of_object(object_doc):
            subnet_id: Any = read_row_value(interface_row, InterfaceField.SUBNET.value)

            if isinstance(subnet_id, int):
                subnet_ids.add(subnet_id)

    return sorted(subnet_ids)


def row_matches_search(row: dict[str, Any], needle: str) -> bool:
    """
    Reports whether a picker row matches a normalized search query, case-insensitively

    Args:
        row (dict[str, Any]): One shaped picker row
        needle (str): The normalized, active search query

    Returns:
        bool: True when the query appears in an address value, the subnet name or the summary line
    """
    haystack: list[str] = [str(row.get(key.value) or '') for key in SEARCHABLE_ROW_KEYS]
    haystack.append(str((row.get(AssignableInterfaceKey.SUBNET.value) or {}).get(
        AssignableInterfaceSubnetKey.NAME.value, '')))
    haystack.append(str(row[AssignableInterfaceKey.OBJECT_INFO.value].get(
        AssignableInterfaceObjectKey.SUMMARY_LINE.value, '')))

    return needle.lower() in ' '.join(haystack).lower()


def build_assignable_interface_rows(
        object_docs: list[dict[str, Any]],
        linked_rows: set[tuple[Any, Any]],
        type_labels: dict[int, str],
        summary_lines: dict[int, str],
        subnet_names: dict[int, str]) -> list[dict[str, Any]]:
    """
    Shapes every offerable interface row of the given objects, in a stable order

    Ordered by (object public_id, multi_data_id) so a page boundary means the same thing on every
    request - the rows come out of documents rather than out of an ordered query, so nothing else
    would guarantee it

    Args:
        object_docs (list[dict[str, Any]]): The candidate CmdbObject documents
        linked_rows (set[tuple[Any, Any]]): (object_id, multi_data_id) pairs this port already links
        type_labels (dict[int, str]): {type_id: label}, resolved in bulk
        summary_lines (dict[int, str]): {object public_id: summary line}, resolved in bulk
        subnet_names (dict[int, str]): {subnet public_id: name}, resolved in bulk

    Returns:
        list[dict[str, Any]]: The shaped rows, empty when nothing is offerable
    """
    rows: list[dict[str, Any]] = []

    for object_doc in sorted(object_docs, key=lambda doc: doc.get(CmdbObjectKey.PUBLIC_ID.value) or 0):
        object_id: Any = object_doc.get(CmdbObjectKey.PUBLIC_ID.value)

        offerable = [row for row in interface_rows_of_object(object_doc)
                     if is_offerable(row, object_id, linked_rows)]

        for interface_row in sorted(offerable,
                                    key=lambda row: row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value) or 0):
            rows.append(build_assignable_interface_row(
                object_doc, interface_row, type_labels, summary_lines, subnet_names,
            ))

    return rows


def build_assignable_interfaces_page(
        rows: list[dict[str, Any]],
        *,
        page: int,
        page_size: int,
        search: str) -> dict[str, Any]:
    """
    Filters, paginates and wraps the shaped rows into the picker's response envelope

    The envelope is the one the IPAM assignable-objects picker answers with, for the same reason: these
    are ROWS inside documents rather than documents, so a `?filter=` pipeline cannot express them and
    the page is cut after the shaping. `total` is the count AFTER the search, so a client paginating a
    filtered list is not told about rows it will never see

    Args:
        rows (list[dict[str, Any]]): Every offerable row, already shaped
        page (int): Requested 1-based page number; clamped server-side
        page_size (int): Requested page size; clamped server-side
        search (str): Raw search query; ignored when shorter than the minimum query length

    Returns:
        dict[str, Any]: {'page', 'page_size', 'total', 'search', 'rows'}
    """
    needle: str | None = active_search(search)

    if needle is not None:
        rows = [row for row in rows if row_matches_search(row, needle)]

    total: int = len(rows)
    safe_page, safe_page_size = clamp_page(page, page_size, total)
    start: int = (safe_page - 1) * safe_page_size

    return {
        IpamOverviewKey.PAGE: safe_page,
        IpamOverviewKey.PAGE_SIZE: safe_page_size,
        IpamOverviewKey.TOTAL: total,
        IpamOverviewKey.SEARCH: needle or '',
        IpamOverviewKey.ROWS: rows[start:start + safe_page_size],
    }
