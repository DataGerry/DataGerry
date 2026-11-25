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
The REST route of the type ACL migration report: how the stored type ACLs became scope roles and assignments
"""
from typing import Any

from flask import abort
from werkzeug import Response

from cmdb.manager import ScopeRolesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.route_utils import handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.rest_api.responses import GetSingleResponse
from cmdb.interface.rest_api.routes.routes_helper import request_wants_body
from cmdb.interface.rest_api.routes.access_routes.access_route_constants import AccessRightName, AccessRouteMessage
# -------------------------------------------------------------------------------------------------------------------- #

migration_report_blueprint = APIBlueprint('migration_report', __name__)


@migration_report_blueprint.route('', methods=['GET', 'HEAD'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@migration_report_blueprint.protect(auth=True, right=AccessRightName.VIEW.value)
@handle_route_errors("while retrieving the type ACL migration report")
def get_migration_report(request_user: CmdbUser) -> Response:
    """
    HTTP `GET`/`HEAD` route for the type ACL migration report: its status, the groups that existed, per Type its
    stored ACL with the roles and assignments made from it and the dropped groups, the Types without an activated ACL,
    and the role and assignment documents made

    Args:
        request_user (CmdbUser): The caller

    Raises:
        HTTPException: 404 when no type ACL was translated on this database (none was activated, or the database was
            created after the migration)

    Returns:
        GetSingleResponse: The report as stored, without its ``_id``
    """
    manager: ScopeRolesManager = ManagerProvider.get_manager(ManagerType.SCOPE_ROLES, request_user)
    report: dict[str, Any] | None = manager.type_acl_migration_report()

    if report is None:
        abort(404, AccessRouteMessage.NO_MIGRATION_REPORT.value)

    return GetSingleResponse(report, body=request_wants_body()).make_response()
