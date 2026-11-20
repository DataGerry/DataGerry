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
The user -> person sync on the user management routes: the user write and its sync, all or nothing

``write_with_person_sync`` runs a route's write and the sync it causes on one ledger: when either fails, both are
undone and the route answers the error it hit - a sync failure the 500 below. The change logs and webhooks of the sync
follow once everything stood, credited to the request user. The sync is read from the caller's tenant, once per
request; while it is off the engine writes nothing
"""
from logging import Logger, getLogger
from typing import Callable

from flask import abort, current_app

from cmdb.manager.manager_provider_model import ManagerProvider
from cmdb.models.user_model import CmdbUser
from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.sync_engine import (
    SyncContext,
    SyncResult,
    emit_sync_events,
    sync_user_deleted,
    sync_users,
)
from cmdb.framework.person_sync.sync_hooks import build_sync_context
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper import build_sync_events

from cmdb.errors.person_sync import PersonSyncError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PERSON_SYNC_FAILED_MESSAGE',
    'PERSON_SYNC_UNDO_INCOMPLETE_MESSAGE',
    'person_sync_context',
    'write_with_person_sync',
    'sync_regrouped_users',
]

LOGGER: Logger = getLogger(__name__)

# The 500 of a write whose sync failed - the write is undone with it
PERSON_SYNC_FAILED_MESSAGE: str = "Nothing was saved: the user sync could not mirror the change - {error}"
# The 500 of a write whose undo could not finish
PERSON_SYNC_UNDO_INCOMPLETE_MESSAGE: str = (
    "The change failed and could not be fully undone - these writes are still in effect: {residue}"
)

# A route's write and its sync: receives the ledger and the sync's context, answers what the sync wrote
SyncedWrite = Callable[[WriteLedger, SyncContext], SyncResult]


def person_sync_context(request_user: CmdbUser) -> SyncContext:
    """
    Builds the sync's context on the caller's tenant, credited to the caller

    Args:
        request_user (CmdbUser): The user making the request

    Returns:
        SyncContext: The managers, the stored settings and the acting user
    """
    return build_sync_context(current_app.database_manager, ManagerProvider.tenant_database(request_user), request_user)


def write_with_person_sync(request_user: CmdbUser, write: SyncedWrite,
                           residue_message: str = PERSON_SYNC_UNDO_INCOMPLETE_MESSAGE) -> None:
    """
    Runs a route's write and its sync on one ledger, then the sync's change logs and webhooks

    Args:
        request_user (CmdbUser): The user making the request - credited with the sync's writes
        write (SyncedWrite): Writes the route's change and calls the sync, recording both in the ledger
        residue_message (str): The 500 when the undo cannot finish, with a ``{residue}`` placeholder

    Raises:
        HTTPException: 500 when the sync failed (everything undone) or the undo could not finish; whatever the write
            itself raised, unchanged, after the undo
    """
    context: SyncContext = person_sync_context(request_user)

    try:
        with undone_on_failure(residue_message) as ledger:
            result: SyncResult = write(ledger, context)
    except PersonSyncError as err:
        LOGGER.error("[write_with_person_sync] %s", err, exc_info=True)
        abort(500, PERSON_SYNC_FAILED_MESSAGE.format(error=err))

    emit_sync_events(context.objects_manager, result, build_sync_events(request_user))


def sync_regrouped_users(context: SyncContext, ledger: WriteLedger, regrouped_ids: list[int],
                         deleted_ids: list[int]) -> SyncResult:
    """
    Syncs the members of a deleted user group: the ones that kept or moved groups (their persons, then each mapped
    person group they touch once - ``sync_users``), and the ones deleted with it

    Args:
        context (SyncContext): The sync's context
        ledger (WriteLedger): The request's ledger
        regrouped_ids (list[int]): The members still stored, their groups rewritten
        deleted_ids (list[int]): The sole members deleted with the group

    Returns:
        SyncResult: What the sync wrote
    """
    result: SyncResult = sync_users(
        context, ledger, list(context.users_manager.get_user_lookup(regrouped_ids).values()) if regrouped_ids else [],
    )

    for user_id in deleted_ids:
        result.merge(sync_user_deleted(context, ledger, user_id))

    return result
