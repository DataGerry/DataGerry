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
The bulk object update - `PUT /objects/<public_id>?objectIDs=` (one full-object payload for many objects) and
`PATCH /objects/?objectIDs=` (one field subset merged into each object)

All or nothing. The targets are written one after another - each validated against what is stored, the targets
written before it included, so two targets cannot be given the same interface IP or overlapping subnets - and
every write is recorded in the request's ``WriteLedger`` right before it runs. A target that is refused (400 /
403 / 404) or whose write fails undoes every earlier write and the request fails with that target's error.
Only once every target is written do the consequences run - the location mirror, the Rack consequences, the
re-read, the select-option sync, the update webhook and the edit log - so a refused bulk update leaves no
object, location, log or event behind

The selection is ``objectIDs`` as repeated query parameters, read by ``read_bulk_update_targets``: duplicates
are dropped (an object is updated once however often it is named) and at most ``MAX_BULK_UPDATE_OBJECTS``
distinct objects may be named. Without ``objectIDs`` the PUT's path public_id is the one target; the PATCH has none

What each target is written with is a payload builder, called with that target's stored object and type:
``complete_put_payload`` hands every target the PUT's payload but refuses one that would drop a field the stored
object carries (a PUT replaces the whole object, and its ``fields`` replace the stored list), and
``bulk_patch_payload`` merges the PATCH's field subset into each target the way the single PATCH does
(``build_patched_object_data``), so every field it does not name keeps its stored value
"""
from typing import Any

from flask import abort

from cmdb.models.object_model import CmdbObject, CmdbObjectFieldKey, CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.interface.rest_api.routes.routes_helper import normalize_public_id_list, undone_on_failure
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    BULK_UPDATE_RESIDUE_MESSAGE,
    BULK_UPDATE_TOO_MANY_MESSAGE,
    MAX_BULK_UPDATE_OBJECTS,
    OBJECT_IDS_REQUIRED_MESSAGE,
    PUT_DROPS_STORED_FIELDS_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_helper import (
    finish_object_update,
    write_object_update,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_patch_helper import (
    build_patched_object_data,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_write_context import (
    ObjectPayloadBuilder,
    ObjectWriteContext,
    WrittenObjectUpdate,
)
# -------------------------------------------------------------------------------------------------------------------- #


def read_bulk_update_targets(raw_object_ids: list[str], fallback_id: int | None) -> list[int]:
    """
    The distinct objects a bulk update targets, in the order they were first named

    Args:
        raw_object_ids (list[str]): Every ``objectIDs`` value of the query string (repeated parameters)
        fallback_id (int | None): The path's public_id, the one target when ``objectIDs`` is absent; None for a
            route without one, which then requires ``objectIDs``

    Raises:
        HTTPException: 400 naming the first unusable id, when more than MAX_BULK_UPDATE_OBJECTS distinct ids are
            named, or when no id is named and there is no fallback

    Returns:
        list[int]: The target public_ids, duplicates dropped
    """
    if not raw_object_ids:
        if fallback_id is None:
            abort(400, OBJECT_IDS_REQUIRED_MESSAGE)

        return [fallback_id]

    object_ids: list[int] = list(dict.fromkeys(normalize_public_id_list(raw_object_ids)))

    if len(object_ids) > MAX_BULK_UPDATE_OBJECTS:
        abort(400, BULK_UPDATE_TOO_MANY_MESSAGE.format(limit=MAX_BULK_UPDATE_OBJECTS, count=len(object_ids)))

    return object_ids


def guard_put_keeps_stored_fields(
        payload: dict[str, Any],
        current_object: CmdbObject,
        current_type: CmdbType) -> None:
    """
    Refuses a full-object payload that would drop a field the stored object carries

    A PUT's ``fields`` replace the stored list, so a field it leaves out loses its value. Only fields the type
    still declares count: a stored field the type no longer has may go, as any update drops it (stale names)

    Args:
        payload (dict[str, Any]): The PUT's full-object payload
        current_object (CmdbObject): The stored object it replaces
        current_type (CmdbType): The object's type

    Raises:
        HTTPException: 400 naming the object and the fields it would lose
    """
    sent: set[Any] = {field.get(CmdbObjectFieldKey.NAME) for field in payload.get(CmdbObjectKey.FIELDS.value) or []}
    declared: set[Any] = {field.get(FieldKey.NAME) for field in current_type.get_fields()}
    missing: list[Any] = [
        field.get(CmdbObjectFieldKey.NAME) for field in current_object.fields
        if field.get(CmdbObjectFieldKey.NAME) in declared and field.get(CmdbObjectFieldKey.NAME) not in sent
    ]

    if missing:
        abort(400, PUT_DROPS_STORED_FIELDS_MESSAGE.format(public_id=current_object.get_public_id(), missing=missing))


def complete_put_payload(payload: dict[str, Any]) -> ObjectPayloadBuilder:
    """
    The payload builder of a PUT: the same full-object payload for every target, held to what each target stores

    Args:
        payload (dict[str, Any]): The validated full-object payload (never mutated)

    Returns:
        ObjectPayloadBuilder: Answers ``payload`` for a target it does not drop a stored field of, else refuses (400)
    """
    def _build(current_object: CmdbObject, current_type: CmdbType) -> dict[str, Any]:
        guard_put_keeps_stored_fields(payload, current_object, current_type)

        return payload

    return _build


def bulk_patch_payload(patch: dict[str, Any]) -> ObjectPayloadBuilder:
    """
    The payload builder of a bulk PATCH: the field subset (and comment) merged into each target's stored object

    Args:
        patch (dict[str, Any]): The validated bulk PATCH body (``validate_bulk_object_patch_payload``); its
            ``active`` is the route's to apply, not part of the merge

    Returns:
        ObjectPayloadBuilder: Answers the target's stored object with the subset applied - every field the subset
            does not name keeps its stored value
    """
    field_subset: dict[str, Any] = {key: value for key, value in patch.items() if key != CmdbObjectKey.ACTIVE.value}

    def _build(current_object: CmdbObject, current_type: CmdbType) -> dict[str, Any]:
        return build_patched_object_data(current_object, field_subset, current_type.get_mds_section_ids())

    return _build


def apply_object_updates(
        object_ids: list[int],
        payload: dict[str, Any] | ObjectPayloadBuilder,
        active_state: bool | None,
        context: ObjectWriteContext,
    ) -> list[dict[str, Any]]:
    """
    Writes every target, undoing all of them when one fails, then finishes each

    Args:
        object_ids (list[int]): The distinct target public_ids (``read_bulk_update_targets``)
        payload (dict[str, Any] | ObjectPayloadBuilder): The validated full-object payload applied to every target
            (never mutated), or the builder that makes each target's payload from its stored object
        active_state (bool | None): The active flag to apply, or None to keep each object's own
        context (ObjectWriteContext): The caller, the managers and the type cache shared by every target

    Raises:
        HTTPException: The first refused target's error (400 / 403 / 404), after the earlier writes were undone;
            500 naming the objects the undo could not put back

    Returns:
        list[dict[str, Any]]: One persisted document per target, in target order
    """
    with undone_on_failure(BULK_UPDATE_RESIDUE_MESSAGE) as ledger:
        written: list[WrittenObjectUpdate] = [
            write_object_update(object_id, payload, active_state, context, ledger) for object_id in object_ids
        ]

    return [finish_object_update(entry, context) for entry in written]
