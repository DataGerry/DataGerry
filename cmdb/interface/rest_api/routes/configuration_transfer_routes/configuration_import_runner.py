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

``POST /configuration_transfer/import`` imports an uploaded file; the start assistant applies bundled best-practice
models, combined into a transfer file too. Both hand the decoded document to ``import_transfer_document``, so every
rule of the import holds for both - nothing written before the last step, all or nothing, and one at a time: the
whole import, from the reset check to the last write, runs inside the configuration lock (``configuration_lock``),
which the reset takes too. Without it, two imports could both pass the reset check, and the one whose write then
clashed would undo by id - deleting the documents the other one had just stored. A caller's own write that must stand
or fall with the import (the start assistant's decision) joins it as ``final_write``: last, inside the lock, on the
import's ledger.
``POST /configuration_transfer/import/preview`` runs the same judgement (``judge_transfer_document``) without the
writes: ``preview_transfer_document`` answers what the import would say instead of refusing
"""
from logging import Logger, getLogger
from typing import Any, Callable

from flask import abort, current_app

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SectionTemplatesManager, SettingsManager, TypesManager, UserSettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.framework.ipam.special_type_wiring import get_special_type_id, handle_special_types
from cmdb.framework.configuration_transfer import (
    TRANSFER_COMPONENTS,
    TRANSFER_COMPONENT_NAMES,
    find_import_blockers,
    import_configuration,
    migrate_transfer_file,
    read_database_version,
    readable_information,
)

from cmdb.framework.write_ledger import WriteLedger
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    abort_with_problems,
    build_transfer_components,
    configuration_lock,
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
    PreviewResponseKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'import_transfer_document',
    'judge_transfer_document',
    'migrate_to_version',
    'preview_transfer_document',
    'read_target_version',
]

LOGGER: Logger = getLogger(__name__)

# The IPAM SpecialTypes whose reference fields are cross-wired, in the order their wiring depends on each other
IPAM_SPECIAL_TYPES: tuple[SpecialType, ...] = (SpecialType.SUPERNET, SpecialType.SUBNET, SpecialType.VLAN)


def wire_imported_special_types(types_manager: TypesManager, templates_manager: SectionTemplatesManager) -> None:
    """
    Cross-wires the imported IPAM SpecialTypes the way creating them through the type routes does

    The import seeds the predefined section templates afresh, so the 'dg-ipam-interface' template's Subnet reference
    starts out empty, and every type's copy of the template is reconciled to that empty reference. Without the wiring
    an interface could not name its subnet: the frontend resolves a reference cell through the field's 'ref_types'.
    ``handle_special_types`` is idempotent and wires both directions, so it runs once per imported IPAM SpecialType;
    it only touches documents this import wrote, which the import's undo removes again

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        templates_manager (SectionTemplatesManager): db interface for section templates

    Raises:
        TypesManagerGetError / TypesManagerUpdateError / SectionTemplatesManager*Error: When the wiring could not be
            read or written - the caller undoes the import
    """
    for special_type in IPAM_SPECIAL_TYPES:
        special_type_id: int | None = get_special_type_id(types_manager, special_type)

        if special_type_id is not None:
            handle_special_types(types_manager, special_type, templates_manager, special_type_id)


def read_target_version(request_user: CmdbUser) -> int:
    """
    Reads the updater version of the database a file is imported into, strictly

    Args:
        request_user (CmdbUser): The importing user, whose tenant database is read

    Raises:
        HTTPException: 500 when the database records no valid version

    Returns:
        int: The version
    """
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    db_version: int | None = read_database_version(settings_manager)

    if db_version is None:
        abort(500, NO_DB_VERSION_MESSAGE)

    return db_version


def migrate_to_version(transfer_file: Any, db_version: int) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Judges what has to hold before a decoded transfer file can be migrated, then brings it to the given version

    The envelope and a version not newer than the target's (``find_file_problems``); a file of an older version is
    migrated with the real updaters in a temporary database (``migrate_transfer_file``, dropped either way), a file of
    the same version is answered as it is

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        db_version (int): The updater version to bring it to

    Raises:
        HTTPException: 500 when the migration failed

    Returns:
        tuple[dict[str, Any] | None, list[str]]: The file in that version (None when it has problems) and its
                                                 problems - empty when it could be migrated
    """
    problems: list[str] = find_file_problems(transfer_file, db_version)

    if problems:
        return None, problems

    return migrate_transfer_file(current_app.database_manager, transfer_file, db_version, TRANSFER_COMPONENTS), []


def judge_transfer_document(transfer_file: Any, request_user: CmdbUser,
                            db_version: int) -> tuple[dict[str, Any] | None, list[str]]:
    """
    Judges a decoded transfer file completely, without writing anything to the system

    In order: the envelope, and a version not newer than the system's; a file of an older version is migrated with
    the real updaters in a temporary database (``migrate_transfer_file``, dropped either way); the migrated file's
    entries are judged; every type's copies of its global templates are reconciled. A step with problems stops the
    judgement - the later steps cannot be asked of such a file

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        request_user (CmdbUser): The importing user, whose tenant database the file is judged against
        db_version (int): The updater version of that database

    Raises:
        HTTPException: 500 when the migration failed

    Returns:
        tuple[dict[str, Any] | None, list[str]]: The migrated and reconciled file (None when the envelope already had
                                                 problems) and every problem found - empty when it may be imported
    """
    migrated, problems = migrate_to_version(transfer_file, db_version)

    if migrated is None:
        return None, problems

    context: ImportContext = build_import_context(request_user)
    problems = find_import_problems(migrated, db_version, context)

    if problems:
        return migrated, problems

    return migrated, reconcile_template_copies(migrated, context)


def preview_transfer_document(transfer_file: Any, request_user: CmdbUser) -> dict[str, Any]:
    """
    Answers what importing a decoded transfer file would say, writing nothing to the system

    The reset blockers and the file's problems are both answered, rather than the first refusal only, so a user sees
    everything that stands in the way at once. The file's `information` is answered as it is whenever it has no
    problem of its own

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        request_user (CmdbUser): The importing user, whose tenant database the file is judged against

    Raises:
        HTTPException: 500 when the database records no version or the migration failed

    Returns:
        dict[str, Any]: ``{information, reset_blockers, problems, importable}`` (``PreviewResponseKey``)
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    blockers: list[str] = find_import_blockers(types_manager)
    problems: list[str] = judge_transfer_document(transfer_file, request_user, read_target_version(request_user))[1]

    return {
        PreviewResponseKey.INFORMATION.value: readable_information(transfer_file, TRANSFER_COMPONENT_NAMES),
        PreviewResponseKey.RESET_BLOCKERS.value: blockers,
        PreviewResponseKey.PROBLEMS.value: problems,
        PreviewResponseKey.IMPORTABLE.value: not blockers and not problems,
    }


def import_transfer_document(transfer_file: Any, request_user: CmdbUser,
                             final_write: Callable[[WriteLedger], None] | None = None) -> dict[str, int]:
    """
    Imports a decoded transfer file into a reset system, in the caller's tenant database

    The whole import runs inside the configuration lock (``configuration_lock``): a second import, best-practice apply
    or reset of the same database is refused while it runs (400). Then, in order, nothing written to the system
    before the last step: the system must be reset - every collection the
    reset clears empty but the user settings (400 naming the others), the database version is read strictly (500), the
    file is judged by ``judge_transfer_document`` - envelope, version, the migration of an older file (500 when that
    fails), the entries, the template copies - and refused with every problem it names (400). Then every write runs
    on one ledger (``import_configuration``): a failure undoes them all

    A caller with a write of its own that must stand or fall with the import passes it as ``final_write``: it runs
    last, still inside the lock and on the import's ledger, which it records itself on. When it fails, the import is
    undone with it - so no import is left that the caller could not finish, and no reset can run in between

    Who may import is the caller's to decide - the routes ask for the master right ``base.*``

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        request_user (CmdbUser): The importing user, whose tenant database the file is imported into
        final_write (Callable[[WriteLedger], None] | None): A write run after the import, on its ledger; None for
            none

    Raises:
        HTTPException: 400 while another import or reset holds the configuration lock, for a system that is not
                       reset, a file of a newer version or a file with problems; 500 when
                       the database records no version or a write failed (undone - or, when the undo could not finish,
                       naming what is left)

    Returns:
        dict[str, int]: The number of documents imported per component
    """
    with configuration_lock(request_user):
        imported: dict[str, int] = _import_while_locked(transfer_file, request_user, final_write)

    LOGGER.warning("[import_transfer_document] A configuration was imported by user %s: %s",
                   request_user.public_id, imported)

    return imported


def _import_while_locked(transfer_file: Any, request_user: CmdbUser,
                         final_write: Callable[[WriteLedger], None] | None = None) -> dict[str, int]:
    """
    The import's steps, run by ``import_transfer_document`` inside the configuration lock

    Args:
        transfer_file (Any): The decoded transfer file - dates as datetimes
        request_user (CmdbUser): The importing user
        final_write (Callable[[WriteLedger], None] | None): The caller's write run last, on the import's ledger

    Raises:
        HTTPException: As ``import_transfer_document`` names them, the lock's refusal excepted

    Returns:
        dict[str, int]: The number of documents imported per component
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    blockers: list[str] = find_import_blockers(types_manager)

    if blockers:
        abort(400, NOT_RESET_MESSAGE.format(collections=blockers))

    migrated, problems = judge_transfer_document(transfer_file, request_user, read_target_version(request_user))
    abort_with_problems(problems)

    templates_manager: SectionTemplatesManager = ManagerProvider.get_manager(ManagerType.SECTION_TEMPLATES,
                                                                              request_user)
    user_settings_manager: UserSettingsManager = ManagerProvider.get_manager(ManagerType.USER_SETTINGS,
                                                                             request_user)

    with undone_on_failure(IMPORT_UNDO_INCOMPLETE_MESSAGE) as ledger:
        imported: dict[str, int] = import_configuration(
            build_transfer_components(request_user), migrated, (templates_manager, user_settings_manager),
            ledger, request_user.public_id,
        )
        wire_imported_special_types(types_manager, templates_manager)

        if final_write is not None:
            final_write(ledger)

    return imported
