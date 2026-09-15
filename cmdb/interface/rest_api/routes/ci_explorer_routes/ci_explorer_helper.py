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
Helper methods shared by the CI Explorer REST routes

Holds the request schemas of the two single-field update routes, the fetch-guard-persist step both
share, and the edit log the object-side write records
"""
from logging import Logger, getLogger
from typing import Any, Callable

from flask import abort

from cmdb.manager.logs_manager import LogsManager

from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Comment stored on the edit log of a tooltip change, so the history says where the change came from
TOOLTIP_LOG_COMMENT: str = 'CI Explorer tooltip changed'


def get_ci_explorer_tooltip_schema() -> dict[str, Any]:
    """
    Builds the request schema of the ``/tooltip/<public_id>`` route

    The body carries the new tooltip and nothing else; the validator purges unknown keys, so a caller
    can not smuggle further CmdbObject keys into the write. An empty string is allowed - it is how a
    tooltip is cleared - but a missing key is not, because that would silently store nothing

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping for the tooltip body
    """
    return {
        CmdbObjectKey.CI_EXPLORER_TOOLTIP.value: {
            'type': 'string',
            'required': True,
            'nullable': True,
            'empty': True,
        },
    }


def get_ci_explorer_label_schema() -> dict[str, Any]:
    """
    Builds the request schema of the ``/type_label/<public_id>`` route

    Mirrors the tooltip schema for the CmdbType side

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping for the type-label body
    """
    return {
        TypeSchemaKey.CI_EXPLORER_LABEL.value: {
            'type': 'string',
            'required': True,
            'nullable': True,
            'empty': True,
        },
    }


def load_ci_explorer_entity(
    fetch: Callable[[int], dict[str, Any] | None],
    public_id: int,
    field: str,
    entity_label: str,
) -> tuple[dict[str, Any], Any]:
    """
    Loads the entity a CI Explorer field write targets

    Shared by the ``/tooltip`` and ``/type_label`` routes: both have to answer 404 for an unknown id
    and both need what the field held before, the tooltip route to record the change in the object's
    history. The write itself stays in the route, because each entity has its own targeted
    single-field update

    Args:
        fetch (Callable[[int], dict | None]): Loads the target entity by public_id (e.g.
            ``objects_manager.get_object``); returns None when it does not exist
        public_id (int): public_id of the entity to update
        field (str): The document key that is about to be set
        entity_label (str): Human-readable entity name used in the 404 message (e.g. "Object")

    Raises:
        HTTPException: 404 when the entity does not exist

    Returns:
        tuple[dict[str, Any], Any]: The entity as it was read, and the value the field held BEFORE the
            write (None when it held nothing)
    """
    entity: dict[str, Any] | None = fetch(public_id)

    if not entity:
        abort(404, f"The {entity_label} with ID:{public_id} was not found!")

    return entity, entity.get(field)


def record_tooltip_edit_log(
    logs_manager: LogsManager,
    request_user: CmdbUser,
    stored_object: dict[str, Any],
    previous_value: Any,
    new_value: Any,
) -> None:
    """
    Writes the CmdbObject edit log for a tooltip change

    A tooltip set from the CI Explorer is a change to the CmdbObject, so it belongs in that object's
    history like any other edit. Best-effort and isolated: a logging failure is logged and swallowed
    so it never fails the write that already happened. There is no CmdbType history in DataGerry,
    which is why the ``/type_label`` route has no counterpart to this

    Args:
        logs_manager (LogsManager): Manager used to persist the edit log
        request_user (CmdbUser): The CmdbUser making the request
        stored_object (dict[str, Any]): The object document as it was read before the write
        previous_value (Any): The tooltip before the change
        new_value (Any): The tooltip after the change
    """
    try:
        logs_manager.insert_log(
            action=LogAction.EDIT,
            log_type=CmdbObjectLog.__name__,
            object_id=stored_object[CmdbObjectKey.PUBLIC_ID.value],
            version=stored_object.get(CmdbObjectKey.VERSION.value),
            user_id=request_user.get_public_id(),
            user_name=request_user.get_display_name(),
            comment=TOOLTIP_LOG_COMMENT,
            changes=[{
                'type': 'change',
                'name': CmdbObjectKey.CI_EXPLORER_TOOLTIP.value,
                'old': previous_value,
                'new': new_value,
            }],
        )
    except Exception as err:
        LOGGER.error("[record_tooltip_edit_log] Failed to create Log. Error: %s. Type: %s", err, type(err))
