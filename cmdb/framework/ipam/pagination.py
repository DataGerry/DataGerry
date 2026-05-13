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
but share the same page / page_size clamping semantics. Centralising the constants and the
clamp helper keeps both endpoints in lockstep, so a change to defaults or limits only happens
in one place
"""
# -------------------------------------------------------------------------------------------------------------------- #


DEFAULT_PAGE_SIZE: int = 50
MAX_PAGE_SIZE: int = 500


def clamp_page(page: int, page_size: int, total: int) -> tuple[int, int]:
    """
    Clamps page / page_size into safe values given the total item count

    page_size is bounded to [1, MAX_PAGE_SIZE]. When 'total' is zero the page falls back to 1;
    otherwise page is bounded to [1, last_page] where last_page is the page that still contains
    at least one item

    Args:
        page (int): Requested 1-based page number
        page_size (int): Requested page size
        total (int): Total number of available items

    Returns:
        tuple[int, int]: (clamped_page, clamped_page_size)
    """
    safe_size: int = max(1, min(page_size, MAX_PAGE_SIZE))

    if total <= 0:
        return 1, safe_size

    last_page: int = max(1, (total + safe_size - 1) // safe_size)
    safe_page: int = max(1, min(page, last_page))

    return safe_page, safe_size
