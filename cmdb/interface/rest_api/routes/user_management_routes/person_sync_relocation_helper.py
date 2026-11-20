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
A target change on the person sync routes: the persons it moves, and the choice for those that cannot move

The pre-check and the settings write plan the same relocations (``person_sync.sync_relocation``). One choice covers
the whole change: ``cancel`` (the default) refuses it when a person cannot move - 400 naming each with its blockers,
nothing written; ``copy`` leaves a deactivated copy of each blocked person and creates a new one. The relocation is
one ledger - all or nothing, a failure the 500 below - and its change logs and webhooks follow, credited to the caller
"""
from typing import Any

from flask import abort

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.person_sync.person_sync_constants import OnBlocked
from cmdb.framework.person_sync.sync_engine import SyncContext, SyncResult, emit_sync_events
from cmdb.framework.person_sync.sync_relocation import RelocationStores, relocate_persons
from cmdb.framework.person_sync.sync_relocation_rules import PersonRelocation
from cmdb.interface.rest_api.routes.routes_helper import undone_on_failure
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_events_helper import build_sync_events
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_hook_helper import (
    PERSON_SYNC_UNDO_INCOMPLETE_MESSAGE,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_sync_route_constants import (
    PersonSyncAnswerKey,
    PersonSyncMessage,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'BLOCKED_SEPARATOR',
    'BLOCKER_SEPARATOR',
    'relocation_stores',
    'relocations_view',
    'relocation_counts',
    'refuse_blocked',
    'apply_relocations',
]

# Joins the blocked persons of one refusal, and the blockers of one person
BLOCKED_SEPARATOR: str = '; '
BLOCKER_SEPARATOR: str = ', '


def relocation_stores(request_user: CmdbUser) -> RelocationStores:
    """
    Builds the managers of what is stamped with an object's Type, on the caller's tenant

    Args:
        request_user (CmdbUser): The caller

    Returns:
        RelocationStores: The logs, relations, relation logs and locations
    """
    return RelocationStores(
        logs_manager=ManagerProvider.get_manager(ManagerType.LOGS, request_user),
        relations_manager=ManagerProvider.get_manager(ManagerType.RELATIONS, request_user),
        object_relations_manager=ManagerProvider.get_manager(ManagerType.OBJECT_RELATIONS, request_user),
        relation_logs_manager=ManagerProvider.get_manager(ManagerType.OBJECT_RELATION_LOGS, request_user),
        locations_manager=ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user),
    )


def relocations_view(relocations: list[PersonRelocation]) -> dict[str, Any]:
    """
    Answers the pre-check: every person the change relocates, and how many cannot move

    Args:
        relocations (list[PersonRelocation]): The planned relocations

    Returns:
        dict[str, Any]: ``relocations`` and ``blocked``
    """
    return {
        PersonSyncAnswerKey.RELOCATIONS.value: [relocation.to_json() for relocation in relocations],
        PersonSyncAnswerKey.BLOCKED.value: sum(1 for relocation in relocations if relocation.blocked),
    }


def relocation_counts(relocations: list[PersonRelocation]) -> dict[str, int]:
    """
    Counts what a target change did: the persons moved and the persons copied

    Args:
        relocations (list[PersonRelocation]): The relocations written

    Returns:
        dict[str, int]: ``moved`` and ``copied``
    """
    copied: int = sum(1 for relocation in relocations if relocation.blocked)

    return {PersonSyncAnswerKey.MOVED.value: len(relocations) - copied, PersonSyncAnswerKey.COPIED.value: copied}


def refuse_blocked(relocations: list[PersonRelocation], on_blocked: str) -> None:
    """
    Refuses a change with blocked persons unless they are to be copied

    Args:
        relocations (list[PersonRelocation]): The planned relocations
        on_blocked (str): The caller's choice (``OnBlocked``)

    Raises:
        HTTPException: 400 naming every blocked person and why
    """
    blocked: list[PersonRelocation] = [relocation for relocation in relocations if relocation.blocked]

    if blocked and on_blocked != OnBlocked.COPY.value:
        details: str = BLOCKED_SEPARATOR.join(
            PersonSyncMessage.PERSON_BLOCKED.value.format(person_id=relocation.person_id, user_id=relocation.user_id,
                                                          blockers=BLOCKER_SEPARATOR.join(relocation.blockers))
            for relocation in blocked
        )
        abort(400, PersonSyncMessage.PERSONS_BLOCKED.value.format(count=len(blocked), details=details))


def apply_relocations(request_user: CmdbUser, context: SyncContext, stores: RelocationStores,
                      relocations: list[PersonRelocation]) -> SyncResult:
    """
    Writes the relocations on one ledger, then their change logs and webhooks

    Args:
        request_user (CmdbUser): The caller, credited with the writes
        context (SyncContext): The managers and the NEW settings
        stores (RelocationStores): The logs, relations, relation logs and locations
        relocations (list[PersonRelocation]): The relocations, judged by ``refuse_blocked``

    Raises:
        HTTPException: 500 when the undo of a failed relocation could not finish; whatever the relocation raised,
            after the undo

    Returns:
        SyncResult: What the relocation wrote
    """
    if not relocations:
        return SyncResult()

    with undone_on_failure(PERSON_SYNC_UNDO_INCOMPLETE_MESSAGE) as ledger:
        result: SyncResult = relocate_persons(context, stores, ledger, relocations, copy_blocked=True)

    emit_sync_events(context.objects_manager, result, build_sync_events(request_user))

    return result
