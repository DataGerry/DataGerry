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
The partial-update (PATCH) payload of a CmdbObject

**The one route in the product that takes a subset of an object.** Every other write path receives the
complete object and treats the payload as authoritative, so the rules a patch needs - what a body may
contain, how a multi-data row is added, edited or removed, and how the result is merged back into a
full object - exist only here.

The merge is deliberately where this module stops: `build_patched_object_data` produces a COMPLETE
object payload which the route then hands to the shared `apply_object_update` pipeline, so a patch gets
exactly the same invariants, versioning, events and side effects as a full update. Nothing in this
module writes to the database.

Split out of `objects_helper.py` on 2026-09-11, with the side-effect cluster, when that module passed
pylint's 1,500-line cap. The group is closed: nothing here calls back into the write pipelines
"""
import copy
from logging import Logger, getLogger
from typing import Any

from cerberus import Validator  # type: ignore
from flask import abort

from cmdb.models.object_model.cmdb_object import CmdbObject
from cmdb.models.object_model import (
    CmdbObjectKey,
    CmdbObjectFieldKey,
    CmdbObjectMdsKey,
    CmdbObjectMdsRowKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectPatchKey
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def get_object_patch_schema() -> dict[str, Any]:
    """
    Builds the Cerberus schema for a partial-update (PATCH) object payload

    Only the patchable parts are described: a subset of regular ``fields`` and three symmetric MDS
    row lists - ``created_mds_rows`` (no multi_data_id; the backend assigns it), ``edited_mds_rows``
    and ``deleted_mds_rows`` - plus an optional ``comment`` for the edit log. Each field entry is a
    ``{name, value, type?}`` triple. The disallowed (immutable / server-managed) keys are rejected
    separately so they can be named in the error

    Returns:
        dict[str, Any]: The Cerberus validation schema for a PATCH body
    """
    field_item: dict[str, Any] = {
        'type': 'dict',
        'schema': {
            'name': {'type': 'string', 'required': True, 'empty': False},
            'value': {'required': True, 'nullable': True},
            'type': {'type': 'string', 'required': False},
        },
    }

    return {
        'fields': {
            'type': 'list',
            'required': False,
            'schema': field_item,
        },
        'created_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'data': {'type': 'list', 'required': True, 'schema': field_item},
                },
            },
        },
        'edited_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'multi_data_id': {'type': 'integer', 'required': True},
                    'data': {'type': 'list', 'required': True, 'schema': field_item},
                },
            },
        },
        'deleted_mds_rows': {
            'type': 'list',
            'required': False,
            'schema': {
                'type': 'dict',
                'schema': {
                    'section_id': {'type': 'string', 'required': True, 'empty': False},
                    'multi_data_id': {'type': 'integer', 'required': True},
                },
            },
        },
        'comment': {'type': 'string', 'required': False, 'nullable': True, 'empty': True},
        'location_name': {'type': 'string', 'required': False, 'nullable': True, 'empty': True},
    }


def validate_object_patch_payload(raw_data: Any) -> dict[str, Any]:
    """
    Validates the raw body of a partial-update (PATCH) object request

    Rejects a non-object body, any key that is not patchable (immutable identifier or
    server-managed field) by naming it, an empty patch that would change nothing, and any body
    whose shape does not match the PATCH schema

    Args:
        raw_data (Any): The raw parsed JSON request body

    Raises:
        HTTPException: 400 when the body is not a JSON object, carries a disallowed key, is empty,
            or fails schema validation

    Returns:
        dict[str, Any]: The validated (and normalized) patch payload
    """
    if not isinstance(raw_data, dict):
        abort(400, "Patch payload must be a JSON object!")

    allowed_keys: set[str] = {member.value for member in ObjectPatchKey}
    disallowed_keys: list[str] = sorted(set(raw_data) - allowed_keys)

    if disallowed_keys:
        abort(400, f"These keys cannot be patched: {disallowed_keys}")

    # LOCATION_NAME counts as a change (a rename of the object's location node); COMMENT alone does not
    changing_keys: list[str] = [
        ObjectPatchKey.FIELDS.value,
        ObjectPatchKey.CREATED_MDS_ROWS.value,
        ObjectPatchKey.EDITED_MDS_ROWS.value,
        ObjectPatchKey.DELETED_MDS_ROWS.value,
        ObjectPatchKey.LOCATION_NAME.value,
    ]

    if not any(raw_data.get(key) for key in changing_keys):
        abort(400, "Patch payload must change at least one field, multi_data_section row or the location name!")

    validator: Validator = Validator(get_object_patch_schema())

    if not validator.validate(raw_data):
        abort(400, f"Invalid patch payload: {validator.errors}")

    return validator.document


def merge_patch_fields(
        stored_fields: list[dict[str, Any]],
        patch_fields: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Merges a subset of field values into a stored field list by field name

    A patched field name that already exists has only its ``value`` overwritten (its stored
    ``type`` is kept); an unknown name is appended as a new entry. Stored fields not mentioned by
    the patch are left untouched. The returned list is a shallow copy — the input is not mutated

    An appended entry carries a ``type`` only when the patch supplied one, which clients normally do
    not. That is intentional and not an incomplete write: the merged payload goes through
    ``apply_object_update``, whose ``validate_and_fill_object_fields`` backfills the ``type`` from the
    type schema before anything is persisted, so the stored entry is always a full triple

    Args:
        stored_fields (list[dict[str, Any]]): The object's current field entries ({name, value, type})
        patch_fields (list[dict[str, Any]]): The subset of field entries to apply ({name, value})

    Returns:
        list[dict[str, Any]]: The merged field list
    """
    merged_fields: list[dict[str, Any]] = [dict(field) for field in stored_fields]
    fields_by_name: dict[Any, dict[str, Any]] = {
        field.get(CmdbObjectFieldKey.NAME): field for field in merged_fields
    }

    for patch_field in patch_fields:
        field_name: str = patch_field[CmdbObjectFieldKey.NAME]

        if field_name in fields_by_name:
            fields_by_name[field_name][CmdbObjectFieldKey.VALUE.value] = patch_field.get(CmdbObjectFieldKey.VALUE)
        else:
            new_field: dict[str, Any] = {
                CmdbObjectFieldKey.NAME.value: field_name,
                CmdbObjectFieldKey.VALUE.value: patch_field.get(CmdbObjectFieldKey.VALUE),
            }

            if CmdbObjectFieldKey.TYPE in patch_field:
                new_field[CmdbObjectFieldKey.TYPE.value] = patch_field[CmdbObjectFieldKey.TYPE]

            merged_fields.append(new_field)
            fields_by_name[field_name] = new_field

    return merged_fields


def create_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        created_rows: list[dict[str, Any]],
        valid_mds_section_ids: set[str],
    ) -> list[dict[str, Any]]:
    """
    Appends new multi-data-section rows, assigning each row's ``multi_data_id`` server-side

    The client supplies only ``section_id`` + ``data`` (no id). Each new row gets the next id from
    the section's ``highest_id`` counter (starting at 1), and that counter is advanced - so several
    creates in the same section get consecutive ids. If the object has no container for a section
    yet, one is seeded (first-row-add) as long as the section is declared by the type
    (``valid_mds_section_ids``); a section the type does not declare is refused. The input is
    deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        created_rows (list[dict[str, Any]]): Rows to add, each ``{section_id, data}``
        valid_mds_section_ids (set[str]): The MDS section_ids declared by the object's type

    Raises:
        HTTPException: 400 when a section_id to create a row in is not declared by the type

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the new rows appended
    """
    result_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in result_sections
    }

    for created_row in created_rows:
        section_id: str = created_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            if section_id not in valid_mds_section_ids:
                abort(400, f"Cannot create a row in unknown multi_data_section '{section_id}'!")

            # First-row-add: the type declares this MDS section but the object has no container yet
            stored_section = {
                CmdbObjectMdsKey.SECTION_ID.value: section_id,
                CmdbObjectMdsKey.HIGHEST_ID.value: 0,
                CmdbObjectMdsKey.VALUES.value: [],
            }
            result_sections.append(stored_section)
            sections_by_id[section_id] = stored_section

        new_multi_data_id: int = stored_section.get(CmdbObjectMdsKey.HIGHEST_ID.value, 0) + 1
        stored_section[CmdbObjectMdsKey.HIGHEST_ID.value] = new_multi_data_id

        stored_section.setdefault(CmdbObjectMdsKey.VALUES.value, []).append({
            CmdbObjectMdsRowKey.MULTI_DATA_ID.value: new_multi_data_id,
            CmdbObjectMdsRowKey.DATA.value: [dict(field) for field in created_row.get(CmdbObjectMdsRowKey.DATA, [])],
        })

    return result_sections


def edit_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        edited_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Merges field values into existing multi-data-section rows

    Rows are matched by ``section_id`` + ``multi_data_id``; the row's field values are merged by
    name (see merge_patch_fields), fields not listed are kept. Editing a row in a section the
    object does not have, or a ``multi_data_id`` that is not present, is refused (use
    created_mds_rows to add a row). The input is deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        edited_rows (list[dict[str, Any]]): Rows to edit, each ``{section_id, multi_data_id, data}``

    Raises:
        HTTPException: 400 when a section_id or a multi_data_id to edit is not present

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the matched rows merged
    """
    result_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in result_sections
    }

    for edited_row in edited_rows:
        section_id: str = edited_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            abort(400, f"Cannot edit a row in unknown multi_data_section '{section_id}'!")

        multi_data_id: int = edited_row[CmdbObjectMdsRowKey.MULTI_DATA_ID]
        rows_by_id: dict[Any, dict[str, Any]] = {
            row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID): row
            for row in stored_section.get(CmdbObjectMdsKey.VALUES.value, [])
        }
        stored_row: dict[str, Any] | None = rows_by_id.get(multi_data_id)

        if stored_row is None:
            abort(400, f"Cannot edit unknown row multi_data_id {multi_data_id} in section '{section_id}'!")

        stored_row[CmdbObjectMdsRowKey.DATA.value] = merge_patch_fields(
            stored_row.get(CmdbObjectMdsRowKey.DATA.value, []),
            edited_row.get(CmdbObjectMdsRowKey.DATA, []),
        )

    return result_sections


def delete_patch_multi_data_rows(
        stored_sections: list[dict[str, Any]],
        deleted_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Removes multi-data-section rows identified by ``section_id`` + ``multi_data_id``

    A section left with no rows is kept (its ``values`` become an empty list and its ``highest_id``
    counter is preserved). Deleting a row from a section the object does not have, or a row whose
    ``multi_data_id`` is not present, is refused so the client is told exactly what did not match.
    The input is deep-copied — it is not mutated

    Args:
        stored_sections (list[dict[str, Any]]): The object's current multi_data_sections
        deleted_rows (list[dict[str, Any]]): Rows to remove, each ``{section_id, multi_data_id}``

    Raises:
        HTTPException: 400 when a section_id or a multi_data_id to delete is not present

    Returns:
        list[dict[str, Any]]: The multi_data_sections list with the rows removed
    """
    remaining_sections: list[dict[str, Any]] = copy.deepcopy(stored_sections)
    sections_by_id: dict[Any, dict[str, Any]] = {
        section.get(CmdbObjectMdsKey.SECTION_ID): section for section in remaining_sections
    }

    for deleted_row in deleted_rows:
        section_id: str = deleted_row[CmdbObjectMdsKey.SECTION_ID]
        stored_section: dict[str, Any] | None = sections_by_id.get(section_id)

        if stored_section is None:
            abort(400, f"Cannot delete a row from unknown multi_data_section '{section_id}'!")

        multi_data_id: int = deleted_row[CmdbObjectMdsRowKey.MULTI_DATA_ID]
        rows: list[dict[str, Any]] = stored_section.get(CmdbObjectMdsKey.VALUES.value, [])
        kept_rows: list[dict[str, Any]] = [
            row for row in rows if row.get(CmdbObjectMdsRowKey.MULTI_DATA_ID) != multi_data_id
        ]

        if len(kept_rows) == len(rows):
            abort(400, f"Cannot delete unknown row multi_data_id {multi_data_id} in section '{section_id}'!")

        stored_section[CmdbObjectMdsKey.VALUES.value] = kept_rows

    return remaining_sections


def build_patched_object_data(
        current_object: CmdbObject,
        patch_data: dict[str, Any],
        valid_mds_section_ids: set[str],
    ) -> dict[str, Any]:
    """
    Builds a complete object payload by applying a validated patch onto the stored object

    Starts from the stored object's canonical JSON, then merges the patched regular ``fields`` and
    applies the MDS row operations in order - create, edit, delete - carrying the optional edit
    ``comment`` through. The result is a full object dict suitable for the shared apply_object_update
    pipeline (which owns the version bump, invariants, persistence and side effects)

    Args:
        current_object (CmdbObject): The stored CmdbObject being patched
        patch_data (dict[str, Any]): The validated patch payload
        valid_mds_section_ids (set[str]): The MDS section_ids declared by the object's type,
            used to allow first-row-add into a section the object has no container for yet

    Returns:
        dict[str, Any]: The merged full-object payload
    """
    merged_data: dict[str, Any] = CmdbObject.to_json(current_object)

    patch_fields: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.FIELDS.value, [])

    if patch_fields:
        merged_data[CmdbObjectKey.FIELDS.value] = merge_patch_fields(
            merged_data.get(CmdbObjectKey.FIELDS.value, []), patch_fields
        )

    created_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.CREATED_MDS_ROWS.value, [])
    edited_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.EDITED_MDS_ROWS.value, [])
    deleted_rows: list[dict[str, Any]] = patch_data.get(ObjectPatchKey.DELETED_MDS_ROWS.value, [])

    sections: list[dict[str, Any]] = merged_data.get(CmdbObjectKey.MULTI_DATA_SECTIONS.value, [])

    if created_rows:
        sections = create_patch_multi_data_rows(sections, created_rows, valid_mds_section_ids)

    if edited_rows:
        sections = edit_patch_multi_data_rows(sections, edited_rows)

    if deleted_rows:
        sections = delete_patch_multi_data_rows(sections, deleted_rows)

    if created_rows or edited_rows or deleted_rows:
        merged_data[CmdbObjectKey.MULTI_DATA_SECTIONS.value] = sections

    if ObjectPatchKey.COMMENT.value in patch_data:
        merged_data[ObjectPatchKey.COMMENT.value] = patch_data[ObjectPatchKey.COMMENT.value]

    if ObjectPatchKey.LOCATION_NAME.value in patch_data:
        merged_data[ObjectPatchKey.LOCATION_NAME.value] = patch_data[ObjectPatchKey.LOCATION_NAME.value]

    return merged_data
