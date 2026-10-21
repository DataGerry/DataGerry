# DATAGERRY - OpenSource Enterprise CMDB
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
The cleanup steps that run after a CmdbObject was deleted, and the one rule they share

By the time these steps run the object is gone, and nothing undoes that. A step that fails therefore must not
answer the delete as failed - the caller would be told the object still exists, and the steps behind it would never
run. Every step is run through `run_delete_cleanup_step`: it catches the typed errors that step's calls raise (its
managers' errors, a lost connection or lock timeout, and for the Rack and Port hooks the 500 their own undo answers
when it cannot finish), logs them under the fixed `DELETE_CLEANUP_INCOMPLETE_MARKER` with the step and the object ids,
and lets the next step run. A programming error is not caught: it still answers 500.

What a failed step leaves behind is named by the marker line: a group still listing the object, a relation or a Rack
membership pointing at it, an attachment reference, a reference field on another object, or the object's ports - whole,
since the port cascade undoes itself (`cascade.delete_ports_with_dependents`).

The webhook and the deletion log are best-effort on their own (`handle_notify_webhooks`, `handle_create_object_log`),
since the create and update paths share them; they are not run through this helper
"""
from logging import Logger, getLogger
from typing import Any, Callable

from werkzeug.exceptions import HTTPException

from cmdb.errors.database import TRANSIENT_DATABASE_ERRORS
from cmdb.errors.manager import (
    BaseManagerDeleteError,
    BaseManagerGetError,
    BaseManagerInsertError,
    BaseManagerUpdateError,
)
from cmdb.errors.manager.locations_manager import LocationsManagerError
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
from cmdb.errors.manager.object_relation_logs_manager import ObjectRelationLogsManagerError
from cmdb.errors.manager.object_relations_manager import ObjectRelationsManagerError
from cmdb.errors.manager.objects_manager import ObjectsManagerError, ObjectsManagerUpdateError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerError
from cmdb.errors.manager.types_manager import TypesManagerError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    DELETE_CLEANUP_INCOMPLETE_MARKER,
    DeleteCleanupStep,
)
from cmdb.interface.rest_api.routes.port_routes.port_route_helper import PORT_DELETE_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

__all__: list[str] = [
    'DELETE_CLEANUP_STEP_ERRORS',
    'run_delete_cleanup_step',
]

# What each step's calls raise when the database refuses or fails them - the failures a step tolerates. Every step
# also tolerates a lost connection and a lock timeout: the object is gone, so a 503 / 423 would misreport the delete
DELETE_CLEANUP_STEP_ERRORS: dict[DeleteCleanupStep, tuple[type[Exception], ...]] = {
    DeleteCleanupStep.REFERENCES: (ObjectsManagerUpdateError, *TRANSIENT_DATABASE_ERRORS),
    DeleteCleanupStep.OBJECT_GROUPS: (BaseManagerUpdateError, *TRANSIENT_DATABASE_ERRORS),
    DeleteCleanupStep.RELATIONS: (
        BaseManagerGetError, BaseManagerDeleteError, BaseManagerInsertError, ObjectRelationsManagerError,
        ObjectRelationLogsManagerError, *TRANSIENT_DATABASE_ERRORS,
    ),
    DeleteCleanupStep.ATTACHMENTS: (MediaFileManagerUpdateError, *TRANSIENT_DATABASE_ERRORS),
    DeleteCleanupStep.RACK: (
        RackMountsManagerError, LocationsManagerError, ObjectsManagerError, TypesManagerError, HTTPException,
        *TRANSIENT_DATABASE_ERRORS,
    ),
    DeleteCleanupStep.PORTS: (*PORT_DELETE_ERRORS, HTTPException, *TRANSIENT_DATABASE_ERRORS),
}


def run_delete_cleanup_step(step: DeleteCleanupStep, object_ids: list[int], call: Callable[[], Any]) -> bool:
    """
    Runs one cleanup step of a deleted CmdbObject, logging its failure instead of raising it

    Args:
        step (DeleteCleanupStep): Which step it is - it decides which errors are tolerated, and names the log line
        object_ids (list[int]): public_ids of the deleted CmdbObjects the step cleans up after
        call (Callable[[], Any]): The step itself

    Returns:
        bool: True when the step ran through, False when it failed and the failure was logged
    """
    try:
        call()
    except DELETE_CLEANUP_STEP_ERRORS[step] as err:
        LOGGER.error(
            "%s step=%s objects=%s: %s: %s",
            DELETE_CLEANUP_INCOMPLETE_MARKER, step.value, object_ids, type(err).__name__, err, exc_info=True,
        )
        return False

    return True
