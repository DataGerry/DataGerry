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
Shared pagination helpers for IPAM overview endpoints

The subnet and supernet overviews paginate different things (host IPs vs. top-level subnets)
but share the same page / page_size clamping semantics. The bounds themselves live in
IpamPagination (cmdb.models.special_type_model.ipam_constants) alongside the other IPAM
constants; this module is the algorithmic clamp helper that consults them
"""
from cmdb.models.special_type_model.ipam_constants import IpamPagination
# -------------------------------------------------------------------------------------------------------------------- #


def clamp_page(page: int, page_size: int, total: int) -> tuple[int, int]:
    """
    Clamps page / page_size into safe values given the total item count

    page_size is bounded to [IpamPagination.MIN_PAGE_SIZE, IpamPagination.MAX_PAGE_SIZE]. When
    'total' is zero or negative the page falls back to IpamPagination.MIN_PAGE; otherwise page
    is bounded to [MIN_PAGE, last_page] where last_page is the page that still contains at
    least one item

    Args:
        page (int): Requested 1-based page number
        page_size (int): Requested page size
        total (int): Total number of available items

    Returns:
        tuple[int, int]: (clamped_page, clamped_page_size)
    """
    safe_size: int = max(IpamPagination.MIN_PAGE_SIZE, min(page_size, IpamPagination.MAX_PAGE_SIZE))

    if total <= 0:
        return IpamPagination.MIN_PAGE, safe_size

    last_page: int = max(IpamPagination.MIN_PAGE, (total + safe_size - 1) // safe_size)
    safe_page: int = max(IpamPagination.MIN_PAGE, min(page, last_page))

    return safe_page, safe_size
