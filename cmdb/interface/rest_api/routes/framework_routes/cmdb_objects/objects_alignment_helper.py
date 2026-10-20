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
Re-aligning stored CmdbObjects after their CmdbType changed

``align_objects_to_type`` runs the statements that bring every object of a type in line with its fields;
``realign_objects_to_type`` and ``clean_type_reports`` are the route-layer wrappers that own the HTTP error mapping
(500) around the object and the report repair. Split off ``objects_helper``, whose subject is one object's create /
update / delete pipeline
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, ReportsManager
from cmdb.manager.objects_propagation_helper import (
    build_add_field_update,
    build_field_entry,
    build_remove_undeclared_fields_update,
)
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.errors.manager.objects_manager import ObjectsManagerUpdateError
from cmdb.interface.route_utils import abort_if_too_large
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def align_objects_to_type(objects_manager: ObjectsManager, type_instance: CmdbType) -> None:
    """
    Re-aligns every CmdbObject of a CmdbType with that type's current field definition, raising on failure

    The statements of ``realign_objects_to_type`` without its HTTP mapping, for a caller that reports the failure
    its own way (the type update names the step that failed)

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_instance (CmdbType): The CmdbType whose objects should be re-aligned

    Raises:
        ObjectsManagerUpdateError: When a statement fails
    """
    declared_names: list[str] = sorted(type_field[FieldKey.NAME] for type_field in type_instance.fields)
    objects_manager.apply_raw_updates([
        build_remove_undeclared_fields_update(type_instance.public_id, declared_names),
        *(build_add_field_update(type_instance.public_id, build_field_entry(type_field))
          for type_field in type_instance.fields),
    ])


def realign_objects_to_type(
        objects_manager: ObjectsManager,
        type_instance: CmdbType,
    ) -> None:
    """
    Re-aligns every CmdbObject of a CmdbType with that type's current field definition

    Drops every ``fields`` entry the type does not declare - whether the edit just removed it or the
    object never should have carried it - and adds each declared field an object is missing, seeded
    with the field's default value (``value`` on the definition) or None. Both run as server-side
    statements (`objects_propagation_helper`), so no object is read: one ``$pull`` for the undeclared
    names, and one ``$push`` per declared field matching only the objects that lack it. Each is
    idempotent, so a second run modifies nothing

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_instance (CmdbType): The CmdbType whose objects should be re-aligned

    Raises:
        HTTPException: 500 when a statement fails
    """
    try:
        align_objects_to_type(objects_manager, type_instance)
    except ObjectsManagerUpdateError as error:
        abort_if_too_large(error)
        LOGGER.error(
            "[realign_objects_to_type] Clean objects Exception: %s, Type: %s", error, type(error)
        )
        abort(500, "An internal server error occured while cleaning objects!")


def clean_type_reports(
        reports_manager: ReportsManager,
        reports_for_type: list[dict[str, Any]],
        removed_field_names: set[str],
        type_instance: CmdbType,
    ) -> None:
    """
    Strips removed field occurrences from a CmdbType's reports and rebuilds their queries

    The route-layer wrapper around ``ReportsManager.strip_removed_fields_from_reports``: it owns only
    the HTTP error mapping, so the same cleanup can be reused by the non-route callers (the global
    section-template removal and the database updaters). A no-op when no field names were removed

    Args:
        reports_manager (ReportsManager): db interface for CmdbReports
        reports_for_type (list[dict[str, Any]]): The stored reports belonging to the type
        removed_field_names (set[str]): Field names that were dropped from the objects
        type_instance (CmdbType): The CmdbType the reports belong to (for the query rebuild)

    Raises:
        HTTPException: 500 when the bulk write of the cleaned reports fails
    """
    try:
        reports_manager.strip_removed_fields_from_reports(reports_for_type, removed_field_names, type_instance)
    except Exception as error:
        LOGGER.error(
            "[clean_type_reports] Clean Reports Exception: %s, Type: %s", error, type(error)
        )
        abort(500, "An internal server error occured while cleaning reports!")
