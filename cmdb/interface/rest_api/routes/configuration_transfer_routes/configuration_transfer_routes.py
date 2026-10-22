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
Implementation of the configuration transfer routes

    - ``GET /configuration_transfer/export``: the user-defined configuration as one JSON file - every type,
      category, user section template and relation with its public_id, each component's counter, stamped with the
      database's updater version (``cmdb.framework.configuration_transfer``). Behind ``base.system.export``
    - ``POST /configuration_transfer/import``: writes an exported file into a reset system - every public_id and
      counter as exported, the type ACLs replaced by the default, the importing administrator as author; the
      predefined section templates re-seeded and every type's copies of them reconciled, every user's settings
      cleared. A file of an older version is migrated with the real updaters first. Judged completely before
      anything is written (one 400 listing every problem), and all or nothing
    - ``POST /configuration_transfer/reset``: clears a system for an import - every type, category, user section
      template and relation, and everything that depends on them (objects and their logs, relations, locations,
      ports, racks, object groups, reports, webhooks, CI-Explorer profiles, DocAPI templates, object attachments,
      ISMS risk assessments, every user's settings). Counters are set back, the start assistant may run again. What
      stays is listed in ``cmdb.framework.configuration_transfer.reset_scope``

The reset and the import are the administrator account's alone (public_id 1, not the admin group) and asks for a typed
confirmation in the body. It cannot be undone; it is re-run safe instead - a reset that fails midway is finished
by running it again
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager, TypesManager
from cmdb.models.user_model import CmdbUser
from cmdb.framework.config_item_sync import handle_sync_config_item_count
from cmdb.framework.configuration_transfer import (
    export_configuration,
    read_database_version,
    run_reset,
)

from cmdb.interface.request_limits_constants import RequestSizeLimit
from cmdb.interface.route_utils import accepts_upload, handle_route_errors, insert_request_user, verify_api_access
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    administrator_only,
    build_configuration_export_response,
    build_transfer_components,
    read_uploaded_transfer_file,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner import (
    import_transfer_document,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_EXPORT_RIGHT,
    EXPORT_FAILED_MESSAGE,
    IMPORT_FAILED_MESSAGE,
    NO_DB_VERSION_MESSAGE,
    ImportResponseKey,
    RESET_REQUEST_SCHEMA,
    RESET_FAILED_MESSAGE,
    ResetResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

configuration_transfer_blueprint = APIBlueprint('configuration_transfer', __name__)

# ---------------------------------------------------- CRUD - READ --------------------------------------------------- #

@configuration_transfer_blueprint.route('/export', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.ADMIN)
@configuration_transfer_blueprint.protect(auth=True, right=CONFIGURATION_EXPORT_RIGHT)
@handle_route_errors(EXPORT_FAILED_MESSAGE)
def export_configuration_file(request_user: CmdbUser) -> Response:
    """
    Exports the user-defined configuration as a downloadable JSON file

    Every registered component writes its section - the documents as stored (without `_id`), in public_id order,
    and its counter. The type ACLs travel along as stored; the import drops them. The file is stamped with the
    database's updater version, read strictly: without a valid one no importable file can be produced

    Args:
        request_user (CmdbUser): The requesting user, whose tenant is exported

    Raises:
        HTTPException: 403 without ``base.system.export``, 500 when the database records no valid version or a
                       component could not be read

    Returns:
        Response: The transfer file as a JSON attachment
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    db_version: int | None = read_database_version(settings_manager)

    if db_version is None:
        abort(500, NO_DB_VERSION_MESSAGE)

    transfer_file: dict[str, Any] = export_configuration(build_transfer_components(request_user), db_version)

    return build_configuration_export_response(transfer_file, db_version)

# --------------------------------------------------- CRUD - CREATE -------------------------------------------------- #

@configuration_transfer_blueprint.route('/import', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@administrator_only
@accepts_upload(RequestSizeLimit.UPLOAD_MAX_CONTENT_LENGTH)
@handle_route_errors(IMPORT_FAILED_MESSAGE)
def import_configuration_file(request_user: CmdbUser) -> Response:
    """
    Imports an exported configuration into a reset system

    The administrator account only; the upload is decoded (400). Everything after it is ``import_transfer_document``
    - the pipeline a best-practice model of the start assistant runs through too, its docstring lists the order: the
    system must be reset, the file is judged completely and migrated when older, and every write runs on one ledger,
    so nothing is written before the last step and a failure undoes them all

    Args:
        request_user (CmdbUser): The administrator account, whose tenant database the file is imported into

    Raises:
        HTTPException: 403 for any user but the administrator account, 400 for a missing or undecodable file, a
                       system that is not reset, a file of a newer version or a file with problems, 500 when the
                       database records no version, the migration failed or a write failed (undone - or, when the
                       undo could not finish, naming what is left)

    Returns:
        Response: The number of documents imported per component
    """
    imported: dict[str, int] = import_transfer_document(read_uploaded_transfer_file(request), request_user)

    return DefaultResponse({ImportResponseKey.IMPORTED.value: imported}).make_response()

# --------------------------------------------------- CRUD - DELETE -------------------------------------------------- #

@configuration_transfer_blueprint.route('/reset', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.SUPER_ADMIN)
@administrator_only
@configuration_transfer_blueprint.validate(RESET_REQUEST_SCHEMA)
@handle_route_errors(RESET_FAILED_MESSAGE)
def reset_configuration(data: dict[str, Any], request_user: CmdbUser) -> Response:
    """
    Clears the configuration and everything depending on it, so an exported file can be imported

    Walks the reset list in order (dependents first, the type definitions last), then removes the start assistant's
    decision - last, so a failed reset does not offer the assistant on a system that still has its types. The reset
    deletes every CmdbObject, so the ConfigItem count is reported afterwards - also when a step failed, since what
    was already deleted stays deleted (hosted cloud only, best-effort: it never changes the answer)

    Args:
        data (dict[str, Any]): The validated body - `confirm` is the typed confirmation; its value is all the schema
                               asks for, so nothing else is read from it
        request_user (CmdbUser): The administrator account, whose tenant database is reset

    Raises:
        HTTPException: 403 for any user but the administrator account, 400 without the confirmation, 500 when a
                       step fails (the reset is then finished by running it again)

    Returns:
        Response: The number of documents deleted per collection
    """
    del data
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    try:
        deleted: dict[str, int] = run_reset(types_manager)
        settings_manager.delete_section(START_ASSISTANT_SETTINGS_SECTION)
    finally:
        handle_sync_config_item_count(request_user)

    LOGGER.warning("[reset_configuration] The configuration was reset by user %s: %s",
                   request_user.public_id, deleted)

    return DefaultResponse({ResetResponseKey.DELETED.value: deleted}).make_response()
