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
Field-name and section-name constants for the IPAM SpecialTypes (SUPERNET, SUBNET, VLAN) and
the dg-ipam-interface section template

Each enum is scoped to a single owner (one SpecialType, or the interface template) so a
member name documents which schema the string belongs to. All enums extend BaseStrEnum so
members are interchangeable with their string values for dict lookup, equality and JSON
serialization, and inherit a shared is_valid() classmethod. Use these members instead of
bare 'dg-*' string literals when reading or writing IPAM-related schemas, CmdbObject fields
or MDS rows
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class SupernetField(BaseStrEnum):
    """
    Field names of the SUPERNET SpecialType
    """
    NAME = 'dg-name'
    NETWORK_RANGE = 'dg-network-range'


class SubnetField(BaseStrEnum):
    """
    Field names of the SUBNET SpecialType
    """
    NAME = 'dg-name'
    NETWORK_RANGE = 'dg-network-range'
    PARENT_SUPERNET = 'dg-supernet-ref'


class VlanField(BaseStrEnum):
    """
    Field names of the VLAN SpecialType
    """
    NAME = 'dg-name'
    SUBNET_REF = 'dg-subnet-ref'
    TYPE = 'dg-vlan-type'


class InterfaceField(BaseStrEnum):
    """
    Field names of one row in the dg-ipam-interface MDS section template
    """
    SUBNET = 'dg-interface-subnet'
    IP = 'dg-interface-ip-address'
    MAC = 'dg-interface-mac-address'


class IpamPrefixPolicy:
    """
    Prefix-length thresholds that drive IPAM address-counting policy

    POINT_TO_POINT_THRESHOLD is the prefix length at and above which the network and
    broadcast addresses cease to be reserved: /31 uses both endpoints (RFC 3021
    point-to-point) and /32 is treated as a single host route. Every helper that
    distinguishes 'total' addresses from 'assignable' addresses consults this boundary

    RESERVED_ADDRESSES_PER_NETWORK is the count of addresses removed from the host pool
    for prefixes shorter than the point-to-point threshold (the network address plus the
    broadcast address)

    FIRST_HOST_OFFSET is the offset from the network address to the first assignable host
    when the network/broadcast reservation applies
    """
    POINT_TO_POINT_THRESHOLD: int = 31
    RESERVED_ADDRESSES_PER_NETWORK: int = 2
    FIRST_HOST_OFFSET: int = 1


class IpamAddressFormat:
    """
    Structural constants for IPv4 address notation accepted by the IPAM validators

    DOTTED_QUAD_DOT_COUNT is the exact number of dots in canonical IPv4 dotted-quad form
    (A.B.C.D). The IPAM parsers reject any string with a different dot count so that
    integer-formatted strings such as '3232235521' (which Python's IPv4Address would silently
    accept) cannot be stored as interface values
    """
    DOTTED_QUAD_DOT_COUNT: int = 3


class IpamPagination:
    """
    Page and page-size bounds shared by every IPAM overview route

    MIN_PAGE and MIN_PAGE_SIZE encode the 1-based pagination policy (the first page is page 1
    and the smallest page size is 1 item). MAX_PAGE_SIZE caps the per-request payload so a
    single call cannot pull an unbounded number of rows. DEFAULT_PAGE_SIZE is the value used
    when the client omits the 'page_size' query parameter
    """
    MIN_PAGE: int = 1
    MIN_PAGE_SIZE: int = 1
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 500


class IpamSearch:
    """
    Query-string bounds shared by every IPAM overview search field

    MIN_QUERY_LENGTH is the minimum length (after stripping whitespace) the framework treats as
    an active filter; a shorter value is ignored so the response falls back to the unfiltered
    view. MAX_QUERY_LENGTH caps the value the route accepts from the client, truncating beyond
    that point so a runaway payload cannot drive arbitrarily large substring scans
    """
    MIN_QUERY_LENGTH: int = 2
    MAX_QUERY_LENGTH: int = 200


class IpamDistributionLimits:
    """
    Maximum dimensions of the subnet 'IP-Verteilung' grid

    The grid divides a subnet into up to MAX_RANGES rows, each containing up to
    MAX_SECTORS_PER_RANGE cells; for smaller subnets the layout scales down so that no cell
    covers fewer than one address. The limits cap the visual density of the heatmap, not the
    subnet size itself
    """
    MAX_RANGES: int = 4
    MAX_SECTORS_PER_RANGE: int = 16


class IpamValidationDetailKey(BaseStrEnum):
    """
    Keys of the 'details' payload carried by IPAM validation errors

    A structured validation error has the shape {code, message, details}: the envelope keys
    are named in ValidationErrorKey, while the per-domain keys inside 'details' are named
    here. Use these members instead of bare string literals when populating the details dict
    so frontend and backend stay aligned on field names. Members are grouped by topic in the
    declaration order below
    """
    # Identity of the candidate object / row being validated
    CANDIDATE = 'candidate'
    OBJECT_ID = 'object_id'
    ROW_INDEX = 'row_index'

    # Subnet / supernet references
    SUBNET_OBJECT_ID = 'subnet_object_id'
    SUPERNET_OBJECT_ID = 'supernet_object_id'
    PARENT_SUPERNET_ID = 'parent_supernet_id'

    # Range strings (the parsed or stored CIDR / network range)
    NETWORK_RANGE = 'network_range'
    SUBNET_RANGE = 'subnet_range'
    SUPERNET_RANGE = 'supernet_range'
    SIBLING_RANGE = 'sibling_range'

    # Sibling / child references
    SIBLING_SUBNET_ID = 'sibling_subnet_id'
    CHILD_SUBNET_ID = 'child_subnet_id'
    PARENT_OBJECT_ID = 'parent_object_id'

    # Range-change guard payload
    CHILD_RANGE = 'child_range'
    NEW_RANGE = 'new_range'

    # Interface row payload
    IP_ADDRESS = 'ip_address'
    FIRST_ROW_INDEX = 'first_row_index'
    DUPLICATE_ROW_INDEX = 'duplicate_row_index'

    # Generic fall-throughs
    STORED_VALUE = 'stored_value'
    REFERENCES = 'references'


class IpamOverviewKey(BaseStrEnum):
    """
    Output payload keys returned by the IPAM overview routes (subnet and supernet)

    Names every dict key emitted to the frontend by the overview builders, grouped by topic in
    the declaration order below. Single shared enum because the same key name carries the same
    meaning across scopes (e.g. 'used_ips' on a row and on the supernet summary both denote
    interface-IP usage counts). For dict keys read from CmdbObject documents (public_id /
    type_id) use the scope-specific CmdbObjectKey instead — those are CmdbObject-document
    keys, not overview-output keys
    """
    # Top-level response envelope
    SUPERNET = 'supernet'
    SUBNET = 'subnet'
    SUBNETS = 'subnets'
    IPS = 'ips'
    PARENT = 'parent'
    ROWS = 'rows'
    PAGE = 'page'
    PAGE_SIZE = 'page_size'
    SEARCH = 'search'
    SORT = 'sort'
    ORDER = 'order'
    TOTAL = 'total'
    TYPE_DISTRIBUTION = 'type_distribution'
    IP_DISTRIBUTION = 'ip_distribution'

    # Supernet / subnet summary metrics
    CIDR = 'cidr'
    IP_RANGE = 'ip_range'
    TOTAL_IPS = 'total_ips'
    ASSIGNABLE_IPS = 'assignable_ips'
    USED_IPS = 'used_ips'
    FREE_IPS = 'free_ips'
    USED_PERCENT = 'used_percent'
    FREE_PERCENT = 'free_percent'
    UTILIZATION_PERCENT = 'utilization_percent'
    SUBNET_COUNT = 'subnet_count'
    INVALID_COUNT = 'invalid_count'

    # Per-subnet row fields specific to the supernet row table
    USAGE_PERCENT = 'usage_percent'
    PARENT_ID = 'parent_id'
    HAS_CHILDREN = 'has_children'
    IS_VALID = 'is_valid'
    VLANS = 'vlans'
    NAME = 'name'

    # IP-range sub-dict (subnet summary + supernet summary)
    FIRST = 'first'
    LAST = 'last'

    # IP-table row (subnet overview)
    IP = 'ip'
    STATUS = 'status'
    TYPE_INFO = 'type_info'
    ASSIGNED_TO = 'assigned_to'
    MAC_ADDRESS = 'mac_address'
    SUMMARY_LINE = 'summary_line'

    # Type metadata (type-distribution buckets and per-row type_info)
    LABEL = 'label'
    CI_EXPLORER_COLOR = 'ci_explorer_color'

    # Distribution bucket fields (type distribution and ip distribution sectors)
    COUNT = 'count'
    PERCENTAGE = 'percentage'

    # IP-distribution grid structure
    SECTOR_SIZE = 'sector_size'
    RANGES = 'ranges'
    SECTORS = 'sectors'
    IP_START = 'ip_start'
    IP_END = 'ip_end'
    USED_COUNT = 'used_count'


class IpamRowStatus(BaseStrEnum):
    """
    'status' field values on each row of the subnet IP-Übersicht table

    ASSIGNED indicates the IP has a dg-ipam-interface row referencing it; FREE indicates the
    address is part of the assignable range but has no interface row. The string values are
    the literal wire-format strings the frontend reads
    """
    ASSIGNED = 'assigned'
    FREE = 'free'


class IpamUnassignKey(BaseStrEnum):
    """
    Request and response payload keys for the supernet 'unassign subnets' route

    SUBNET_IDS is the request-body field carrying the list of subnet public_ids the caller
    asks to detach from the supernet. UNASSIGNED_COUNT is the response field echoing how
    many subnets the route actually cleared. Both are scoped to the unassign route alone -
    keys shared with the read-side overview payload live in IpamOverviewKey instead
    """
    SUBNET_IDS = 'subnet_ids'
    UNASSIGNED_COUNT = 'unassigned_count'


class IpamBucketLabel(BaseStrEnum):
    """
    'label' field values for the synthetic buckets in the type_distribution payload

    FREE is the synthetic bucket for unassigned (still-free) addresses; UNKNOWN catches every
    assigned row whose owning CmdbType cannot be resolved (the type was deleted or the
    interface row carried no type id). Both are wire-format strings the frontend reads as
    fixed slice labels, separate from the user-facing CmdbType labels in the type buckets
    """
    FREE = 'Free'
    UNKNOWN = 'Unknown'


class IpamSortColumn(BaseStrEnum):
    """
    Allowed values of the 'sort' query parameter for the subnet IP-Übersicht route

    Each member names one column of the IP-table row that can be the sort key. The values
    are the exact strings the FE places in the URL, so any rename here must be paired with
    a FE adjustment. Free rows (status='free') have no type / assigned_to / mac_address;
    the sort logic places those rows after the rows with values regardless of direction
    """
    IP = 'ip'
    STATUS = 'status'
    TYPE = 'type'
    ASSIGNED_TO = 'assigned_to'
    MAC_ADDRESS = 'mac_address'


class IpamSortDirection(BaseStrEnum):
    """
    Allowed values of the 'order' query parameter for the subnet IP-Übersicht route

    Values are the integer-encoded sort direction the rest of the codebase uses with Mongo
    ('1' for ascending, '-1' for descending; see CollectionParameters, BaseManager). The FE
    sends the value as a query-string token so the enum stores the string form. ASC is the
    default when 'sort' is given without an explicit 'order'. DESC reverses the comparison
    on rows that carry a value but leaves the 'no value' partition trailing (NULLS LAST
    regardless of direction)
    """
    ASC = '1'
    DESC = '-1'


class IpamSection(BaseStrEnum):
    """
    Section names used in IPAM SpecialType schemas and the dg-ipam-interface MDS section template

    INTERFACE is the MDS section template name itself (not a section inside a SpecialType
    schema). The other members are section names that appear inside the SUPERNET / SUBNET / VLAN
    schemas
    """
    INTERFACE = 'dg-ipam-interface'
    INFORMATION = 'dg-information'
    NETWORK_DETAILS = 'dg-network-details'
    VLAN_DETAILS = 'dg-vlan-details'
