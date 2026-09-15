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
Helper functions for the OpenCelium license REST routes

These are **OpenCelium's** licence routes, not DataGerry's own (`/rest/license`,
`cmdb/interface/rest_api/routes/cmdb_license/`) - two different products' licensing in one API.

The manager construction the two routes repeated lives here, and so does the paging the usage report
accepts, kept out of the route so the rule is stated once and testable without a request context.
"""
from flask import current_app, request

from cmdb.manager import OcLicenseManager

from cmdb.models.user_model import CmdbUser

from cmdb.open_celium.oc_constants import (
    OC_DEFAULT_USAGE_PAGE,
    OC_DEFAULT_USAGE_SIZE,
    OC_PAGE_PARAM,
    OC_SIZE_PARAM,
)
# -------------------------------------------------------------------------------------------------------------------- #


def build_license_manager(request_user: CmdbUser) -> OcLicenseManager:
    """
    Builds the OcLicenseManager for the requesting user

    Both license routes need the same two arguments - the process-wide database manager and the
    caller's database, which is what selects the OpenCelium installation to ask - so the construction
    lives here instead of twice in the route module

    Args:
        request_user (CmdbUser): The user making the request; its database scopes the manager

    Returns:
        OcLicenseManager: The manager to talk to OpenCelium with
    """
    return OcLicenseManager(current_app.database_manager, request_user.database)


def read_usage_paging() -> tuple[int, int]:
    """
    Reads the `page` / `size` of the license-usage report off the query string

    Both are forwarded to OpenCelium, which decides what exists. **A value that cannot be read as a
    whole number answers the default** rather than a 400: `type=int` is deliberate here (a bare
    `int()` used to crash into a generic 500), but it means `?page=abc` reads as page 0 as though the
    caller had asked for it, and a negative or enormous value passes straight through. Whether an
    unreadable value should be refused instead is discussion-backlog #226, to be decided together
    with #223 - the identical question on the invoker route's flag - which is why the rule sits in one
    place

    Returns:
        tuple[int, int]: The requested page and page size
    """
    page: int = request.args.get(OC_PAGE_PARAM, default=OC_DEFAULT_USAGE_PAGE, type=int)
    size: int = request.args.get(OC_SIZE_PARAM, default=OC_DEFAULT_USAGE_SIZE, type=int)

    return page, size
