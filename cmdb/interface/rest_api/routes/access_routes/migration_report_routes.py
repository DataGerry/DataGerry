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
The REST route of the access migration reports: how the stored type ACLs became scope roles and assignments, and which
user groups were given which access rule right (under ``rights``)
"""
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.access_model import (
    ACCESS_RIGHTS_MIGRATION_REPORT_ID,
    TYPE_ACL_MIGRATION_REPORT_ID,
)
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import (
    MIGRATION_RIGHTS_KEY,
    AccessRightName,
    AccessRouteMessage,
)
# -------------------------------------------------------------------------------------------------------------------- #

migration_report_blueprint = APIBlueprint('migration_report', __name__)


@migration_report_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@migration_report_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the type ACL migration report")
def get_migration_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the access migration reports: the type ACL migration's keys - its status, the groups
    that existed, per Type its stored ACL with the roles and assignments made from it and the dropped groups, the Types
    without an activated ACL, the role and assignment documents made - and under ``rights`` the access rights
    migration's (the groups given access rule rights), null when it gave none

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when neither migration wrote a report on this database (no type ACL was activated and no
            group qualified for a right, or the database was created after the migrations)

    Returns:
        GetSingleResponse: The type ACL report as stored (absent keys when it was never written) plus ``rights``
    """
    manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    reports: dict[str, dict[str, Any]] = manager.migration_reports()

    if not reports:
        abort(404, AccessRouteMessage.NO_MIGRATION_REPORT.value)

    answer: dict[str, Any] = {**reports.get(TYPE_ACL_MIGRATION_REPORT_ID, {}),
                              MIGRATION_RIGHTS_KEY: reports.get(ACCESS_RIGHTS_MIGRATION_REPORT_ID)}

    return GetSingleResponse(answer, body=request_wants_body()).make_response()
