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
The sync's entry points for the user writes that happen outside a REST route of user management

Every place that writes a user or a user group calls the sync (``tests/unit/test_person_sync_hook_census.py`` holds the
list). The REST routes run it on their own ledger - the write and its sync stand or fall together
(``user_management_routes.person_sync_hook_helper``). Two writers run outside them and cannot refuse a login over a
failed sync: an LDAP sign-in and the hosted cloud's admin set-up. ``sync_user_outside_request`` serves both: the user is
the acting user, the sync runs on a ledger of its own, and a failure undoes the sync's writes, marks the user
``sync_pending`` (the next reconciliation pass catches it up) and lets the sign-in go on. A lost connection or a lock
timeout is the request's own failure and is raised.

The change logs and webhooks are the route layer's, which the security layer may not import: the route layer registers
its builder once at start (``register_sync_events_builder``) and a sync outside a request uses it. Without one -
outside the app - nothing is logged
"""
from logging import Logger, getLogger
from typing import Any, Callable

from cmdb.database import MongoDatabaseManager
from cmdb.manager import GroupsManager, ObjectsManager, SettingsManager, TypesManager, UsersManager
from cmdb.models.user_model import CmdbUser, CmdbUserKey

from cmdb.framework.write_ledger import WriteLedger
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncEvents, SyncResult, emit_sync_events, sync_user
from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, read_sync_settings

from cmdb.errors.database import APP_HANDLED_DATABASE_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'SyncEventsBuilder',
    'register_sync_events_builder',
    'registered_sync_events',
    'build_sync_context',
    'sync_user_outside_request',
]

LOGGER: Logger = getLogger(__name__)

SyncEventsBuilder = Callable[[CmdbUser], SyncEvents]

# The route layer's builder, registered once at start; a list so the module holds no rebound global
_EVENTS_BUILDERS: list[SyncEventsBuilder] = []


def register_sync_events_builder(builder: SyncEventsBuilder) -> None:
    """
    Registers the route layer's builder of the sync's change logs and webhooks - the last registration counts

    Args:
        builder (SyncEventsBuilder): Builds the callbacks for an acting user
    """
    _EVENTS_BUILDERS[:] = [builder]


def registered_sync_events(acting_user: CmdbUser) -> SyncEvents | None:
    """
    Builds the sync's callbacks for an acting user through the registered builder

    Args:
        acting_user (CmdbUser): The user credited with the writes

    Returns:
        SyncEvents | None: The callbacks; None when no builder is registered
    """
    return _EVENTS_BUILDERS[0](acting_user) if _EVENTS_BUILDERS else None


def build_sync_context(dbm: MongoDatabaseManager, db_name: str | None, acting_user: CmdbUser,
                       settings: PersonSyncSettings | None = None) -> SyncContext:
    """
    Builds the sync's context on one tenant database, reading the settings unless given

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str | None): The tenant database; None for the manager's default
        acting_user (CmdbUser): The user credited with the writes
        settings (PersonSyncSettings | None): The settings, when already read

    Returns:
        SyncContext: The managers, the settings and the acting user
    """
    settings_manager = SettingsManager(dbm, db_name)

    return SyncContext(
        objects_manager=ObjectsManager(dbm, db_name),
        types_manager=TypesManager(dbm, db_name),
        users_manager=UsersManager(dbm, db_name),
        groups_manager=GroupsManager(dbm, db_name),
        settings=settings if settings is not None else read_sync_settings(settings_manager),
        acting_user=acting_user,
        settings_manager=settings_manager,
    )


def sync_user_outside_request(dbm: MongoDatabaseManager, db_name: str | None, user: CmdbUser) -> None:
    """
    Syncs a user written outside the user management routes - never failing the write that called it

    The user is the acting user. Nothing is read beyond the settings while the user sync is off. A failure undoes the
    sync's writes and marks the user ``sync_pending``; a sync that succeeds removes a mark left by an earlier one

    Args:
        dbm (MongoDatabaseManager): The database manager
        db_name (str | None): The tenant database
        user (CmdbUser): The user as stored after its write

    Raises:
        DocumentNetworkError / DocumentLockTimeoutError: A lost connection or a lock timeout - the request's failure
    """
    settings: PersonSyncSettings = read_sync_settings(SettingsManager(dbm, db_name))

    if not settings.users.active:
        return

    context: SyncContext = build_sync_context(dbm, db_name, user, settings)
    ledger = WriteLedger()

    try:
        result: SyncResult = sync_user(context, ledger, user)
    except APP_HANDLED_DATABASE_ERRORS:
        ledger.undo()
        raise
    except Exception:  # pylint: disable=broad-exception-caught
        LOGGER.error("[sync_user_outside_request] The sync of user %s failed - marked %s, residue: %s",
                     user.public_id, CmdbUserKey.SYNC_PENDING.value, ledger.undo(), exc_info=True)
        context.users_manager.update({CmdbUserKey.PUBLIC_ID.value: user.public_id},
                                     {CmdbUserKey.SYNC_PENDING.value: True})

        return

    marked: dict[str, Any] = {CmdbUserKey.PUBLIC_ID.value: user.public_id,
                              CmdbUserKey.SYNC_PENDING.value: {'$exists': True}}
    context.users_manager.update(marked, {'$unset': {CmdbUserKey.SYNC_PENDING.value: ''}})
    emit_sync_events(context.objects_manager, result, registered_sync_events(user))
