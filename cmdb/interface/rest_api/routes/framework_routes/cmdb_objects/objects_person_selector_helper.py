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
The person selector on the CmdbObject routes: the write check's HTTP answer, the delete guard and clean-up, and the
picker

The rules themselves live in ``cmdb.framework.person_selector``; this module turns their answers into aborts and
hands them the managers of the request
"""
from typing import Any

from flask import abort, request

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.framework.ipam.reference_disclosure import HiddenTypeIds, hidden_types_of
from cmdb.framework.special_type_marker import read_special_type_marker
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.utils import coerce_whole_number
from cmdb.framework.person_selector.person_selector_constants import (
    DEFAULT_PICKER_LIMIT,
    LABEL_FIELD_BY_KIND,
    MAX_PICKER_LIMIT,
    PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE,
    SELECTOR_DELETE_OBJECT_ID_LIMIT,
    PersonPickerError,
    PersonPickerKey,
    PersonPickerParam,
)
from cmdb.framework.person_selector.selector_picker import PickerQuery, find_person_choices
from cmdb.framework.person_selector.selector_delete import find_required_selector_blockers, scrub_person_selectors
from cmdb.framework.person_selector.selector_write_rule import SelectorRefusal, check_person_selector_values
# -------------------------------------------------------------------------------------------------------------------- #

def validate_person_selector_values(request_user: CmdbUser,
                                    objects_manager: ObjectsManager,
                                    types_manager: TypesManager,
                                    candidate: dict[str, Any],
                                    object_type: CmdbType,
                                    previous_object: dict[str, Any] | None = None) -> None:
    """
    Aborts when an object write's person selector values may not be stored (``check_person_selector_values``)

    Canonicalises the values in place, and on an update puts back the stored ids the writer may not read

    Args:
        request_user (CmdbUser): The writer
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        candidate (dict[str, Any]): The document about to be stored (changed in place)
        object_type (CmdbType): The candidate's type
        previous_object (dict[str, Any] | None): The stored document on an update; None on a create

    Raises:
        HTTPException: 400 for a wrong shape, an unknown id or a kind the selector does not select; 403 for an
            object the writer may not read
    """
    refusal: SelectorRefusal | None = check_person_selector_values(
        objects_manager, types_manager, hidden_types_of(request_user), candidate, object_type.fields, previous_object,
    )

    if refusal:
        abort(refusal.status, refusal.message)


def selectable_target_ids(types_manager: TypesManager,
                          target_objects: list[dict[str, Any]],
                          target_types: dict[int, CmdbType] | None = None) -> list[int]:
    """
    The delete targets a person selector can hold: objects of a type carrying PERSON or PERSON_GROUP

    Only those can be selected, so a delete without one needs neither the guard nor the clean-up. The marker is
    always the target type's - never the one the object stores, which an object written without it lacks: taken
    from the type the caller holds, else read once per type

    Args:
        types_manager (TypesManager): db interface for CmdbTypes, read only for a type the caller does not hold
        target_objects (list[dict[str, Any]]): The objects being deleted
        target_types (dict[int, CmdbType] | None): Their types by public_id, where the caller holds them

    Returns:
        list[int]: The public_ids of the targets a selector can hold
    """
    markers: dict[Any, Any] = {}

    def marker(target: dict[str, Any]) -> Any:
        type_id: Any = target.get(CmdbObjectKey.TYPE_ID.value)

        if type_id not in markers:
            markers[type_id] = read_special_type_marker(types_manager, type_id, (target_types or {}).get(type_id))

        return markers[type_id]

    return sorted(
        target[CmdbObjectKey.PUBLIC_ID.value] for target in target_objects
        if SpecialType.is_valid(marker(target)) and not SpecialType.is_singleton(marker(target))
    )


def guard_person_selector_delete(request_user: CmdbUser,
                                 objects_manager: ObjectsManager,
                                 types_manager: TypesManager,
                                 deleted_ids: list[int]) -> None:
    """
    Aborts 400 when the deletion would leave a required person selector of another object empty

    The refusal names the blocking objects the caller may READ and counts the rest

    Args:
        request_user (CmdbUser): The caller
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        deleted_ids (list[int]): The whole delete selection

    Raises:
        HTTPException: 400 naming the blocking objects
    """
    blockers: list[tuple[int, int]] = find_required_selector_blockers(objects_manager, types_manager, deleted_ids)

    if not blockers:
        return

    hidden: HiddenTypeIds = hidden_types_of(request_user)
    readable: list[int] = [object_id for object_id, type_id in blockers if type_id not in hidden()]

    abort(400, PERSON_SELECTOR_REQUIRED_DELETE_MESSAGE.format(
        object_ids=readable[:SELECTOR_DELETE_OBJECT_ID_LIMIT], hidden=len(blockers) - len(readable),
    ))


def scrub_deleted_from_person_selectors(request_user: CmdbUser,
                                        objects_manager: ObjectsManager,
                                        deleted_ids: list[int]) -> None:
    """
    Lets every person selector go of the deleted objects - a delete clean-up step

    Args:
        request_user (CmdbUser): The caller
        objects_manager (ObjectsManager): db interface for CmdbObjects
        deleted_ids (list[int]): The deleted objects

    Raises:
        BaseManagerGetError: When the types could not be read
        ObjectsManagerUpdateError: When the update fails
    """
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    scrub_person_selectors(objects_manager, types_manager, deleted_ids)


def _read_list_param(name: str) -> list[str] | None:
    """A comma-separated query parameter as its items, or None when it is not sent"""
    raw: str | None = request.args.get(name)

    return None if raw is None else [item.strip() for item in raw.split(',') if item.strip()]


def read_picker_query() -> PickerQuery:
    """
    Reads the person picker's query parameters

    ``kinds`` defaults to both, ``page`` to 1, ``limit`` to ``DEFAULT_PICKER_LIMIT``; ``ids`` resolves the given
    objects instead of browsing

    Raises:
        HTTPException: 400 naming the unusable parameter

    Returns:
        PickerQuery: The parameters
    """
    kinds_raw: list[str] | None = _read_list_param(PersonPickerParam.KINDS.value)
    allowed: list[str] = [kind.value for kind in LABEL_FIELD_BY_KIND]

    if kinds_raw is not None and (not kinds_raw or any(kind not in allowed for kind in kinds_raw)):
        abort(400, PersonPickerError.KINDS.value)

    ids_raw: list[str] | None = _read_list_param(PersonPickerParam.IDS.value)
    ids: list[int | None] | None = None if ids_raw is None else [coerce_whole_number(item) for item in ids_raw]

    if ids is not None and any(object_id is None for object_id in ids):
        abort(400, PersonPickerError.IDS.value)

    page: int | None = coerce_whole_number(request.args.get(PersonPickerParam.PAGE.value, 1))
    limit: int | None = coerce_whole_number(request.args.get(PersonPickerParam.LIMIT.value, DEFAULT_PICKER_LIMIT))

    if page is None or page < 1:
        abort(400, PersonPickerError.PAGE.value)

    if limit is None or not 1 <= limit <= MAX_PICKER_LIMIT:
        abort(400, PersonPickerError.LIMIT.format(maximum=MAX_PICKER_LIMIT))

    return PickerQuery(
        kinds=[SpecialType(kind) for kind in (kinds_raw or allowed)],
        search=request.args.get(PersonPickerParam.SEARCH.value) or None,
        ids=None if ids is None else [object_id for object_id in ids if object_id is not None],
        page=page,
        limit=limit,
    )


def build_person_picker_payload(request_user: CmdbUser, objects_manager: ObjectsManager,
                                types_manager: TypesManager) -> dict[str, Any]:
    """
    Builds one page of the person picker for the caller

    Raises:
        HTTPException: 400 for unusable parameters
        BaseManagerGetError: When a read fails

    Returns:
        dict[str, Any]: ``{results, total, page, limit}``
    """
    query: PickerQuery = read_picker_query()
    results, total = find_person_choices(objects_manager, types_manager, hidden_types_of(request_user), query)

    return {
        PersonPickerKey.RESULTS.value: results,
        PersonPickerKey.TOTAL.value: total,
        PersonPickerKey.PAGE.value: query.page,
        PersonPickerKey.LIMIT.value: query.limit,
    }
