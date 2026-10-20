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
Helper methods of the CI Explorer REST routes

Holds the request schema of the label-field update route and the fetch-or-404 step it takes before
writing.
"""
from logging import Logger, getLogger
from typing import Any, Callable

from flask import abort

from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.models.ci_explorer_model import CiExplorerProfileKey
from cmdb.interface.rest_api.routes.ci_explorer_routes.ci_explorer_constants import PROFILE_FILTER_UNKNOWN_IDS_MSG
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# Every stored document - profile, type, relation - is identified under the same key
PUBLIC_ID_KEY: str = CiExplorerProfileKey.PUBLIC_ID.value

def get_ci_explorer_label_schema() -> dict[str, Any]:
    """
    Builds the request schema of the ``/label_field/<public_id>`` route

    The value is the NAME of one of the Type's own fields, whose value the CI Explorer then shows on
    every node of the Type - never a label to display. The schema can only say "a string"; that the
    string names a field the Type offers is checked in the route, against the Type it just loaded
    (``ci_explorer.label_field.label_field_error``). Null and the empty string both mean "no field
    nominated"

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping for the label-field body
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

    Answers 404 for an unknown id and returns what the field held before the write. The write itself
    stays in the route, because each entity has its own targeted single-field update

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


def find_unknown_ids(manager: Any, public_ids: list[int] | None) -> list[int]:
    """
    Answers which of the given public_ids name no document of the manager's collection

    One projected query for the whole list, however long it is

    Args:
        manager (Any): The manager of the collection the ids have to exist in (a `BaseManager`)
        public_ids (list[int] | None): The ids to check; None or empty checks nothing

    Returns:
        list[int]: The ids that do not exist, sorted; empty when every id exists
    """
    if not public_ids:
        return []

    existing: set[int] = {
        document[PUBLIC_ID_KEY]
        for document in manager.find(criteria={PUBLIC_ID_KEY: {'$in': list(public_ids)}}, projection={PUBLIC_ID_KEY: 1})
    }

    return sorted(set(public_ids) - existing)


def abort_if_profile_filters_name_unknown_ids(
    data: dict[str, Any],
    types_manager: Any,
    relations_manager: Any,
) -> None:
    """
    Refuses a CiExplorer profile whose filters name types or relations that do not exist

    Such a profile is accepted by its shape but fails far from where it was written: applying it
    filters the graph to nothing for an unknown id. It is refused where it is written instead

    Args:
        data (dict[str, Any]): The validated profile payload
        types_manager (Any): The TypesManager the type filter is checked against
        relations_manager (Any): The RelationsManager the relation filter is checked against

    Raises:
        HTTPException: 400 naming the filter and the unknown ids
    """
    for field, manager in (
        (CiExplorerProfileKey.TYPES_FILTER.value, types_manager),
        (CiExplorerProfileKey.RELATIONS_FILTER.value, relations_manager),
    ):
        unknown_ids: list[int] = find_unknown_ids(manager, data.get(field))

        if unknown_ids:
            abort(400, PROFILE_FILTER_UNKNOWN_IDS_MSG.format(field=field, ids=unknown_ids))
