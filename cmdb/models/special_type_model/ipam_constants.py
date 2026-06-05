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
    TYPE = 'dg-supernet-type'


class SubnetField(BaseStrEnum):
    """
    Field names of the SUBNET SpecialType
    """
    NAME = 'dg-name'
    NETWORK_RANGE = 'dg-network-range'
    PARENT_SUPERNET = 'dg-supernet-ref'
    TYPE = 'dg-subnet-type'


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
    TYPE = 'dg-interface-type'


class IpAddressFamily(BaseStrEnum):
    """
    Address-family tokens shared by the SUBNET 'dg-subnet-type' and SUPERNET 'dg-supernet-type'
    selectors

    IPV4 / IPV6 are the option 'name' tokens of those required SELECT fields stored on the
    CmdbObject (the FE renders the 'IPv4' / 'IPv6' labels). They are the canonical family tokens
    the IPAM validators compare a parsed network's family against (see cidr.network_family). A
    missing value is treated as IPV4: legacy objects pre-date the field and the former range
    regex only admitted IPv4
    """
    IPV4 = 'ipv4'
    IPV6 = 'ipv6'


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


class IpVersion:
    """
    IP protocol version numbers as reported by ipaddress' network / address objects

    V4 / V6 mirror the integers returned by the '.version' attribute of IPv4Network /
    IPv6Network (and the address equivalents). The IPAM helpers branch on these instead of
    bare 4 / 6 literals when address-family handling differs (e.g. IPv6 has no network /
    broadcast reservation)
    """
    V4: int = 4
    V6: int = 6


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


class IpamSubnetTableLimits:
    """
    Size bound for candidate-IP materialization in the subnet IP table

    Search, sort and the status / type filters require materializing every assignable IP of
    an IPv4 subnet as a Python string; for very large prefixes that is hundreds of megabytes
    of memory and seconds of CPU per request. MAX_MATERIALIZED_CANDIDATES caps the assignable
    count those operations accept (2**20 admits /12 and narrower) - beyond it the route
    rejects search / sort / filter with HTTP 400 while the lazy ascending-IP browsing path
    keeps working at any subnet size
    """
    MAX_MATERIALIZED_CANDIDATES: int = 2 ** 20


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

    # Sibling references
    SIBLING_SUBNET_ID = 'sibling_subnet_id'

    # Interface row payload
    IP_ADDRESS = 'ip_address'
    FIRST_ROW_INDEX = 'first_row_index'
    DUPLICATE_ROW_INDEX = 'duplicate_row_index'

    # Address family (family-consistency errors)
    SUBNET_TYPE = 'subnet_type'
    SUPERNET_TYPE = 'supernet_type'
    CIDR_FAMILY = 'cidr_family'
    SUPERNET_FAMILY = 'supernet_family'
    INTERFACE_TYPE = 'interface_type'
    IP_FAMILY = 'ip_family'
    SUBNET_FAMILY = 'subnet_family'

    # Generic fall-throughs
    STORED_VALUE = 'stored_value'
    REFERENCES = 'references'


class IpamValidationRequestKey(BaseStrEnum):
    """
    Request-body keys accepted by the IPAM pre-validation routes (/ipam/validate/*)

    Names every JSON body field the four inline pre-check routes read, so route parsing and
    the frontend stay aligned on field names. ROWS / ROW_INDEX / SUBNET_ID / IP_ADDRESS /
    INTERFACE_TYPE / EXCLUDE_OBJECT_ID belong to the interface batch route; NETWORK_RANGE,
    the two selector keys and the parent / exclusion ids belong to the subnet / supernet /
    vlan candidate routes. Keys of the response envelope live in IpamValidationResponseKey,
    keys inside an error's 'details' dict in IpamValidationDetailKey
    """
    # Subnet / supernet / vlan candidate routes
    NETWORK_RANGE = 'network_range'
    SUBNET_TYPE = 'subnet_type'
    SUPERNET_TYPE = 'supernet_type'
    SUBNET_ID = 'subnet_id'
    PARENT_SUPERNET_ID = 'parent_supernet_id'
    EXCLUDE_SUBNET_ID = 'exclude_subnet_id'

    # Interface batch route
    ROWS = 'rows'
    ROW_INDEX = 'row_index'
    IP_ADDRESS = 'ip_address'
    INTERFACE_TYPE = 'interface_type'
    EXCLUDE_OBJECT_ID = 'exclude_object_id'


class IpamValidationResponseKey(BaseStrEnum):
    """
    Response-envelope keys returned by every IPAM pre-validation route (/ipam/validate/*)

    VALID is the boolean summary flag (True when the error list is empty); ERRORS carries the
    structured error list whose per-error keys are named in ValidationErrorKey and whose
    'details' keys are named in IpamValidationDetailKey
    """
    VALID = 'valid'
    ERRORS = 'errors'


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
    TYPE = 'type'
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
    SUBNET_TYPE = 'subnet_type'
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
    TYPE_STATS = 'type_stats'

    # Single-sector drill-down (subnet sector route): request param + response echo
    SECTOR_START = 'sector_start'
    SECTOR = 'sector'


class IpamTreeKey(BaseStrEnum):
    """
    Output payload keys returned by the IPAM sidebar-tree routes

    Names every dict key emitted to the frontend by the tree builders
    (cmdb.framework.ipam.tree_overview). SUPERNETS and UNASSIGNED are the two blocks of the
    initial tree payload: a flat list of every SUPERNET (each entry carrying HAS_CHILDREN so
    the FE can render an expand caret without a probe request) and a flat list of every
    SUBNET without a parent supernet. CHILDREN is the recursive nesting key of the
    per-supernet subtree payload. The node-level keys (NAME, CIDR, TYPE, HAS_CHILDREN) are
    scoped here even where their string values coincide with IpamOverviewKey members because
    the tree nodes form their own wire schema: TYPE carries the node's address family
    (IpAddressFamily token), unlike the overview routes where 'type' is a type-filter query
    parameter. The node's 'public_id' key is CmdbObjectKey.PUBLIC_ID, matching the overview
    rows
    """
    # Envelope blocks of the tree payloads
    SUPERNETS = 'supernets'
    UNASSIGNED = 'unassigned'
    CHILDREN = 'children'

    # Per-node fields
    NAME = 'name'
    CIDR = 'cidr'
    TYPE = 'type'
    HAS_CHILDREN = 'has_children'


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
    Request and response payload keys for the IPAM 'unassign' routes

    SUBNET_IDS is the request-body field of the supernet route carrying the list of subnet
    public_ids the caller asks to detach from the supernet. IPS is the request-body field of
    the subnet route carrying the list of canonical IP strings whose dg-ipam-interface rows
    should be unassigned from their owner CmdbObjects. MODE is the optional request-body field
    of the subnet route selecting whether to clear the subnet reference or delete the whole row
    (see IpamUnassignMode); it is also echoed in the response. UNASSIGNED_COUNT is the response
    field echoing how many rows the route actually affected. All four are scoped to the unassign
    routes alone - keys shared with the read-side overview payload live in IpamOverviewKey
    instead
    """
    SUBNET_IDS = 'subnet_ids'
    IPS = 'ips'
    MODE = 'mode'
    UNASSIGNED_COUNT = 'unassigned_count'


class IpamUnassignMode(BaseStrEnum):
    """
    Allowed values of the subnet unassign route's 'mode' field

    REFERENCE clears only the dg-interface-subnet reference on each matching dg-ipam-interface
    row (the row, its IP and MAC are kept; the row is just detached from the subnet). ROW deletes
    the whole matching row from its owner object. The mode applies to every IP in one request -
    it is not chosen per row. REFERENCE is the default when the field is omitted, preserving the
    original behaviour
    """
    REFERENCE = 'reference'
    ROW = 'row'


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


class IpamExport:
    """
    Constants for the supernet 'assigned subnets' Excel (.xlsx) export

    SHEET_TITLE names the single worksheet; HEADERS is the ordered base column header row shared by
    both address families (CIDR, IP range, used / free counts). USAGE_HEADER is the IPv4-only
    trailing 'Usage (%)' column: it is appended to HEADERS for an IPv4 supernet's export but omitted
    for an IPv6 one, where a used/total ratio against a 2**n address space is meaningless.
    IP_RANGE_SEPARATOR joins the range's first and last address into a single cell. MIMETYPE is the
    OpenXML spreadsheet content type and FILENAME_TEMPLATE builds the download filename
    """
    SHEET_TITLE: str = 'Assigned Subnets'
    HEADERS: list[str] = ['CIDR', 'IP Range', 'Used IPs', 'Free IPs']
    USAGE_HEADER: str = 'Usage (%)'
    IP_RANGE_SEPARATOR: str = ' - '
    MIMETYPE: str = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    FILENAME_TEMPLATE: str = 'supernet_{public_id}_subnets_{timestamp}.xlsx'


class IpamSubnetIpsExport:
    """
    Constants for the subnet 'IP overview' Excel (.xlsx) export

    SHEET_TITLE names the single worksheet; HEADERS is the ordered column row, identical for both
    address families (the family difference is which rows are emitted, not which columns). The
    columns mirror the overview IP table: the address, its type label, its status, the assigned
    owner's summary line and its MAC. MAX_EXPORT_ROWS caps how many IP rows may be exported - an
    export that would exceed it is rejected (HTTP 400) and no workbook is built; the counted volume
    is the IPv4 assignable count (free + assigned) or the IPv6 assigned count. FILENAME_TEMPLATE
    builds the download filename. The OpenXML content type is shared via IpamExport.MIMETYPE
    """
    SHEET_TITLE: str = 'Subnet IPs'
    HEADERS: list[str] = ['IP', 'Type', 'Status', 'Assigned To', 'MAC Address']
    MAX_EXPORT_ROWS: int = 2500
    FILENAME_TEMPLATE: str = 'subnet_{public_id}_ips_{timestamp}.xlsx'
