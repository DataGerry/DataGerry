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
Turning a port <-> interface link back into the interface row it names, and noticing when it can not

A link addresses an MDS row by the triple (object, section, multi_data_id), and that row id is the
**non-durable** part of the reference: the full object PUT does not preserve MDS row ids and the CSV
import overwrite renumbers them, so an object write that has nothing to do with ports can leave a link
pointing at a row that no longer exists - or, worse, at a *different* row that inherited the id.

The design answer is a SOFT reference. A link whose row has gone is tolerated on read and **reported**,
never cascaded: deleting it automatically would destroy the only record of what the customer meant,
and the repair is theirs to make. Creating a link that is already dangling is a different thing and is
refused on write, because that mistake is visible at the moment it is made.

Everything here is pure - the CmdbObject documents are handed in by the caller, which does the reading -
so the resolution and the dangling detection can be exercised without a database
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.models.object_model.cmdb_object_key_enum import (
    CmdbObjectKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.models.port_interface_link_model.port_interface_link_constants import PortInterfaceLinkKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def find_interface_row(
        interface_object: dict[str, Any] | None,
        section_id: Any,
        multi_data_id: Any) -> dict[str, Any] | None:
    """
    Finds one MDS row of one CmdbObject by its section and its row id

    The single place the triple is resolved. Both coordinates have to match: a row id is unique only
    WITHIN its section, so looking it up by id alone would return a row of some other section whenever
    the two happen to share a number

    Args:
        interface_object (dict[str, Any] | None): The CmdbObject holding the row, or None when it no
            longer exists
        section_id (Any): Name of the MDS section the row should live in
        multi_data_id (Any): The row's multi_data_id

    Returns:
        dict[str, Any] | None: The matching MDS row, or None when the object, the section or the row
            is gone
    """
    if not interface_object:
        return None

    for section in interface_object.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, []) or []:
        if section.get(CmdbObjectMdsKey.SECTION_ID.value) != section_id:
            continue

        for row in section.get(CmdbObjectMdsKey.VALUES.value, []) or []:
            if row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID.value) == multi_data_id:
                return row

    return None


def resolve_link_row(
        link: dict[str, Any],
        interface_object: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Resolves one link to the live interface row it names

    Args:
        link (dict[str, Any]): The CmdbPortInterfaceLink document
        interface_object (dict[str, Any] | None): The CmdbObject the link points at, or None

    Returns:
        dict[str, Any] | None: The interface row, or None when the link is dangling
    """
    return find_interface_row(
        interface_object,
        link.get(PortInterfaceLinkKey.INTERFACE_SECTION_ID.value),
        link.get(PortInterfaceLinkKey.INTERFACE_MULTI_DATA_ID.value),
    )


def is_dangling(link: dict[str, Any], interface_object: dict[str, Any] | None) -> bool:
    """
    Reports whether a link's interface row has gone

    Args:
        link (dict[str, Any]): The CmdbPortInterfaceLink document
        interface_object (dict[str, Any] | None): The CmdbObject the link points at, or None

    Returns:
        bool: True when the row can no longer be resolved
    """
    return resolve_link_row(link, interface_object) is None


def group_links_by_interface_object(links: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    """
    Groups links by the CmdbObject holding the interface row they name

    Whether a row still exists is a question about ONE object, so grouping first is what lets the
    caller read each object once instead of once per link - the difference between one query and one
    per row on an installation that has documented a lot of cabling

    Args:
        links (list[dict[str, Any]]): The CmdbPortInterfaceLink documents

    Returns:
        dict[int, list[dict[str, Any]]]: The links keyed by interface_object_id. A link whose object id
            is unusable is dropped, because there is no object to check it against
    """
    grouped: dict[int, list[dict[str, Any]]] = {}

    for link in links:
        object_id: Any = link.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value)

        if not isinstance(object_id, int):
            continue

        grouped.setdefault(object_id, []).append(link)

    return grouped


def collect_dangling_links(
        links: list[dict[str, Any]],
        interface_objects: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns every link whose interface row can no longer be resolved

    The body of the repair report. A link is dangling when its object is gone, when the section is
    gone, or when the row inside that section is gone - all three read the same to a customer, who
    needs to be told which port pointed at what so they can re-link it.

    An object MISSING from the mapping is treated as deleted rather than as unknown: the caller reads
    exactly the objects the links name, so absence means the read found nothing

    Args:
        links (list[dict[str, Any]]): The CmdbPortInterfaceLink documents to judge
        interface_objects (dict[int, dict[str, Any]]): The CmdbObjects those links name, keyed by
            public_id, as read in one batched query by the caller

    Returns:
        list[dict[str, Any]]: The dangling links, in the order they were given
    """
    return [
        link for link in links
        if is_dangling(
            link, interface_objects.get(link.get(PortInterfaceLinkKey.INTERFACE_OBJECT_ID.value)),
        )
    ]
