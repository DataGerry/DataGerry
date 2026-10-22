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
One import pipeline for every way a transfer file reaches the system

``POST /configuration_transfer/import`` imports an uploaded file; the start assistant applies a bundled best-practice
model, which is a transfer file too. Both hand the decoded document to ``import_transfer_document``, so every rule of
the import holds for both - nothing written before the last step, all or nothing
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, current_app

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SectionTemplatesManager, SettingsManager, TypesManager, UserSettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENTS,
    find_import_blockers,
    import_configuration,
    migrate_transfer_file,
    read_database_version,
)

from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    abort_with_problems,
    build_transfer_components,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_validation import (
    ImportContext,
    build_import_context,
    find_file_problems,
    find_import_problems,
    reconcile_template_copies,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    IMPORT_UNDO_INCOMPLETE_MESSAGE,
    NO_DB_VERSION_MESSAGE,
    NOT_RESET_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['import_transfer_document']

LOGGER: Logger = getLogger(__name__)


def import_transfer_document(transfer_file: Any, request_user: CmdbUser) -> dict[str, int]:
    """
    Imports a decoded transfer file into a reset system, in the caller's tenant database

    In order, nothing written to the system before the last step: the system must be reset - every collection the
    reset clears empty but the user settings (400 naming the others), the database version is read strictly (500), the
    file's envelope is judged and its version may not be newer than the system's (400). A file of an older version is
    migrated with the real updaters in a temporary database (``migrate_transfer_file``, 500 when that fails - the
    temporary database is dropped either way). The migrated file is judged completely and every type's copies of its
    global templates reconciled (400 listing every problem). Then every write runs on one ledger
    (``import_configuration``): a failure undoes them all

    Who may import is the caller's to decide - the routes ask for the administrator account

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        request_user (CmdbUser): The administrator account, whose tenant database the file is imported into

    Raises:
        HTTPException: 400 for a system that is not reset, a file of a newer version or a file with problems; 500 when
                       the database records no version or a write failed (undone - or, when the undo could not finish,
                       naming what is left)

    Returns:
        dict[str, int]: The number of documents imported per component
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    blockers: list[str] = find_import_blockers(types_manager)

    if blockers:
        abort(400, NOT_RESET_MESSAGE.format(collections=blockers))

    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    db_version: int | None = read_database_version(settings_manager)

    if db_version is None:
        abort(500, NO_DB_VERSION_MESSAGE)

    abort_with_problems(find_file_problems(transfer_file, db_version))

    migrated: dict[str, Any] = migrate_transfer_file(current_app.database_manager, transfer_file, db_version,
                                                     TRANSFER_COMPONENTS)
    context: ImportContext = build_import_context(request_user)

    abort_with_problems(find_import_problems(migrated, db_version, context))
    abort_with_problems(reconcile_template_copies(migrated, context))

    templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES,
                                                                              request_user)
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    with undone_on_failure(IMPORT_UNDO_INCOMPLETE_MESSAGE) as ledger:
        imported: dict[str, int] = import_configuration(
            build_transfer_components(request_user), migrated, (templates_manager, user_settings_manager),
            ledger, request_user.public_id,
        )

    LOGGER.warning("[import_transfer_document] A configuration was imported by user %s: %s",
                   request_user.public_id, imported)

    return imported
