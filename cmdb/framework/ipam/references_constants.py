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
Projections and bounds of the IPAM reference lookups (``references``), the delete guards that list them, the
interface checks (``interface_validator``) that read the referencing objects and the referenced subnets, and the
validators and overviews that read one SUBNET / SUPERNET or a supernet's sibling subnets
"""
from typing import Any

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey, CmdbObjectMdsKey
from cmdb.models.special_type_model.ipam_constants import IpamSection, SubnetField
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

# The two keys a reference lookup answers per object - nothing else of the document is read
REFERENCE_PROJECTION: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.TYPE_ID.value: 1}

# What the interface IP uniqueness check reads of a candidate object: its id, its type (whether the owner of a
# collision may be named) and its interface sections - every one of them, never another section's rows. A $filter
# expression rather than an $elemMatch projection: that one answers only the FIRST matching section, and an object
# may hold the interface section twice
INTERFACE_CANDIDATE_PROJECTION: dict[str, Any] = {
    CmdbObjectKey.PUBLIC_ID.value: 1,
    CmdbObjectKey.TYPE_ID.value: 1,
    CmdbObjectKey.MULTI_DATA_SECTIONS.value: {'$filter': {
        'input': f'${CmdbObjectKey.MULTI_DATA_SECTIONS.value}',
        'cond': {'$eq': [f'$$this.{CmdbObjectMdsKey.SECTION_ID.value}', IpamSection.INTERFACE.value]},
    }},
}

# What the interface checks read of a referenced subnet: its id and its fields (the network range, the type token)
SUBNET_CHECK_PROJECTION: dict[str, Any] = {CmdbObjectKey.PUBLIC_ID.value: 1, CmdbObjectKey.FIELDS.value: 1}

# What a check or an overview reads of one SUBNET / SUPERNET: its id, its type (whether it is one) and its fields (the
# network range, the address family token) - never its audit keys or sections
IPAM_OBJECT_CHECK_PROJECTION: dict[str, Any] = {
    CmdbObjectKey.PUBLIC_ID.value: 1,
    CmdbObjectKey.TYPE_ID.value: 1,
    CmdbObjectKey.FIELDS.value: 1,
}

# What the sibling overlap check reads of every subnet of the supernet: its id and its network range entry alone. The
# check runs on every subnet write and pre-check and grows with the supernet, so the other fields stay in the database
SIBLING_RANGE_PROJECTION: dict[str, Any] = {
    CmdbObjectKey.PUBLIC_ID.value: 1,
    CmdbObjectKey.FIELDS.value: {'$filter': {
        'input': f'${CmdbObjectKey.FIELDS.value}',
        'cond': {'$eq': [f'$$this.{CmdbObjectFieldKey.NAME.value}', SubnetField.NETWORK_RANGE.value]},
    }},
}

# An existence check reads at most one match
EXISTENCE_LIMIT: int = 1

# What a special-type lookup reads of the CmdbType: its id, and the marker when several are asked at once
SPECIAL_TYPE_ID_PROJECTION: dict[str, Any] = {TypeSchemaKey.PUBLIC_ID.value: 1}
SPECIAL_TYPE_MARKER_PROJECTION: dict[str, Any] = {
    TypeSchemaKey.PUBLIC_ID.value: 1,
    TypeSchemaKey.SPECIAL_TYPE.value: 1,
}

# How many blocking ids a delete guard's 400 names; the rest are counted ("... and 12 more")
MAX_LISTED_REFERENCES: int = 20

# The order the referencing objects are listed and capped in, so the 400 names the same ids on every attempt
REFERENCE_SORT: list[tuple[str, int]] = [(CmdbObjectKey.PUBLIC_ID.value, 1)]

# The delete guards' 400 messages; {ids} is the description ``reference_disclosure.describe_reference_ids`` builds:
# the readable ids, capped, then how many more readable ones and how many the caller may not see
SUPERNET_REFERENCED_BY_SUBNETS_MSG: str = "Supernet is referenced by subnets: {ids}"
SUBNET_REFERENCED_BY_VLANS_MSG: str = "Subnet is referenced by vlans: {ids}"
SUBNET_REFERENCED_BY_INTERFACES_MSG: str = "Subnet is referenced by interface rows on objects: {ids}"
# The parts of that description: the listed ids joined by the separator, "and N more" past the cap, the hidden count
# after its own joiner so it never reads as another id - "1, 2 and 135 more", "1, plus 3 object(s) you cannot see",
# "3 object(s) you cannot see"
REFERENCE_ID_SEPARATOR: str = ", "
MORE_REFERENCES_PART: str = "{listed} and {more} more"
HIDDEN_REFERENCES_JOIN: str = ", plus "
HIDDEN_REFERENCES_PART: str = "{hidden} object(s) you cannot see"

# The interface IP uniqueness refusal: the owner of the colliding row named when the writer may READ its type,
# described without its id (or its row) otherwise
IP_ALREADY_USED_MSG: str = "IP {ip_address} is already used in subnet {subnet_id} by {owner}"
IP_OWNER_READABLE_LABEL: str = "object {object_id} (interface row {row_key})"
IP_OWNER_HIDDEN_LABEL: str = "an object you cannot see"
