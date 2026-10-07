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
Keeps requests away from a tenant database that failed its startup update

In cloud mode the REST app validates and migrates every tenant database before it serves
(`init_rest_api.execute_update_checks`). A tenant that fails is not allowed to take the others down with
it: it is recorded in `BaseCmdbApp.unavailable_tenants` and every other tenant is served. Its own schema,
though, may be half-migrated, so nothing may read or write it until the next start retries the update.

A request is bound to a tenant in three places, and each asks `abort_if_tenant_unavailable` before it
touches the tenant's database: the cloud login (`auth_helper.cloud_login`), a Bearer token's tenant claim
(`route_utils.insert_request_user`) and the Basic + `x-api-key` channel (`route_utils.verify_api_access`).
HTTP Basic without an `x-api-key` is exchanged for a token and then held by the Bearer check
"""
from flask import abort, current_app

from cmdb.interface.tenant_availability_constants import TENANT_UNAVAILABLE_RESPONSE_MESSAGE
# -------------------------------------------------------------------------------------------------------------------- #


def abort_if_tenant_unavailable(database: str | None) -> None:
    """
    Answers 503 when the request's tenant database failed its startup update

    Args:
        database (str | None): The tenant database the request is bound to; None (on premise, or no tenant
            resolved yet) is never unavailable

    Raises:
        HTTPException: 503 when the tenant is in `current_app.unavailable_tenants`
    """
    if database and database in current_app.unavailable_tenants:
        abort(503, TENANT_UNAVAILABLE_RESPONSE_MESSAGE)
