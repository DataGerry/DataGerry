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
Change guards and usage payloads for CmdbType API routes

What an update or a delete of a CmdbType may not do while CmdbObjects depend on it, and the pre-check payloads the
UI asks for before it tries:

    - the usage payloads behind the sibling GET routes (which objects use the location field, the ports of a
      uses_ports Type)
    - each refused change as a pair: a ``*_blocker`` that answers the reason (or None) for a caller that collects
      reasons, and a ``guard_*`` that aborts with it for a route - uses_ports switched off, selectable_as_parent
      switched off, the location field removed, a field or multi-data-section identifier changed
    - the delete guard (``verify_type_deletable``): a Type with CmdbObjects, or one another Type's reference section
      names, is not deleted

Every refusal is a 400, the code's answer to a business-rule rejection
"""
from typing import Any

from flask import abort

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.ports_manager import PortsManager
from cmdb.manager import ObjectsManager, ReportsManager
from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.user_model.cmdb_user import CmdbUser
from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey
from cmdb.models.port_model import PortKey
from cmdb.models.reports_model.report_constants import ReportKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import get_location_field
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_reference_section_helper import (
    describe_section_dependents,
    get_types_referencing_section,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    FIELD_IDENTIFIER_IMMUTABLE_MESSAGE,
    MDS_SECTION_IDENTIFIER_IMMUTABLE_MESSAGE,
    TYPE_NOT_FOUND_MESSAGE,
    USES_PORTS_DISABLE_MESSAGE,
    UsesPortsUsageKey,
    REFERENCED_TYPE_DELETE_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

def get_objects_using_location_field(
    request_user: CmdbUser,
    target_type: CmdbType,
) -> list[int]:
    """
    Returns the public_ids of CmdbObjects that currently store a location value
    (an integer > 0) in the location-typed field of the given CmdbType

    Returns an empty list if the CmdbType has no location field. The result is unbounded - every
    matching public_id is returned, which for a large type is a large list

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        list[int]: public_ids of CmdbObjects that have a value in the location field
    """
    location_field: dict[str, Any] | None = get_location_field(target_type)

    if not location_field:
        return []

    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    criteria: dict[str, Any] = {
        CmdbObjectKey.TYPE_ID: target_type.get_public_id(),
        CmdbObjectKey.FIELDS: {
            '$elemMatch': {
                CmdbObjectFieldKey.NAME: location_field[FieldKey.NAME],
                CmdbObjectFieldKey.VALUE: {'$gt': 0},
            },
        },
    }

    # Only the public_ids are used, so the query projects them instead of loading whole documents -
    # this runs on every type-edit page load and inside both update guards
    matching_objects: list[dict[str, Any]] = objects_manager.find_objects(
        criteria,
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )

    return [obj[CmdbObjectKey.PUBLIC_ID] for obj in matching_objects]


def build_location_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the shared "is this Type's location placement in use" pre-check payload

    Resolves the CmdbObjects of the given CmdbType that currently store a location value and packs
    them into the {in_use, count, object_public_ids} shape returned by the location-field-usage GET
    route. That one answer pre-checks both location guards on update - removing the location field and
    turning 'selectable_as_parent' off - because both ask whether any object of the type is placed in
    the location tree

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use: bool, count: int, object_public_ids: list[int]}
    """
    object_public_ids: list[int] = get_objects_using_location_field(request_user, target_type)

    return {
        'in_use': bool(object_public_ids),
        'count': len(object_public_ids),
        'object_public_ids': object_public_ids,
    }


def get_port_usage_of_type(request_user: CmdbUser, target_type: CmdbType) -> dict[str, int]:
    """
    Counts the CmdbPorts that exist on the CmdbObjects of one CmdbType

    A port stores its owner CmdbObject, not its type, so the question is two steps: which objects
    belong to this type, and how many ports name one of them. Resolved that way round on purpose - the
    alternative, a `$lookup` from framework.ports into framework.objects, would pay a join on every
    type-edit page load, and storing a type_id on the port would duplicate a fact the owner already
    holds and go stale if an object ever changed type.

    Only the object public_ids are read, never whole documents. Both counts are returned because the
    refusal message names them; the caller that only needs "any" reads the port count

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, int]: {'port_count': ports in total, 'object_count': objects of the type carrying at
            least one port}. Both zero when the type has no objects or none of them has ports
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    ports_manager: PortsManager = ManagerProvider.get_manager(ManagerType.PORTS, request_user)

    object_documents: list[dict[str, Any]] = objects_manager.find_objects(
        {CmdbObjectKey.TYPE_ID: target_type.get_public_id()},
        as_dict=True,
        projection={CmdbObjectKey.PUBLIC_ID: 1},
    )
    object_ids: list[int] = [document[CmdbObjectKey.PUBLIC_ID] for document in object_documents]

    if not object_ids:
        return {UsesPortsUsageKey.PORT_COUNT.value: 0, UsesPortsUsageKey.OBJECT_COUNT.value: 0}

    owned_criteria: dict[str, Any] = {PortKey.OBJECT_ID.value: {'$in': object_ids}}

    port_count: int = ports_manager.count_documents(owned_criteria)
    owners_with_ports: list[Any] = ports_manager.get_distinct(PortKey.OBJECT_ID.value, owned_criteria)

    return {
        UsesPortsUsageKey.PORT_COUNT.value: port_count,
        UsesPortsUsageKey.OBJECT_COUNT.value: len(owners_with_ports),
    }


def build_uses_ports_usage_payload(request_user: CmdbUser, target_type: CmdbType) -> dict[str, Any]:
    """
    Builds the "may 'uses_ports' be turned off" pre-check payload

    Counts only, never an id list - the equivalent location payload is unbounded for a large type,
    and the type builder only needs to know whether the flag may be cleared.
    `in_use: false` means it may

    Args:
        request_user (CmdbUser): User performing the request
        target_type (CmdbType): The CmdbType to inspect

    Returns:
        dict[str, Any]: {in_use, port_count, object_count}
    """
    usage: dict[str, int] = get_port_usage_of_type(request_user, target_type)

    return {
        UsesPortsUsageKey.IN_USE.value: usage[UsesPortsUsageKey.PORT_COUNT.value] > 0,
        **usage,
    }


def uses_ports_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'uses_ports' off, if it may not

    A CmdbType may only stop using ports once no port of its objects is left: the frontend renders the
    ports panel only for a port-bearing type, so clearing the flag would leave those ports as rows
    nothing in the UI can reach - and the port create route would refuse to recreate them.

    Only the true -> false transition is guarded. Turning it ON is always allowed here (the
    license guard `enforce_uses_ports_license` governs that direction), and keeping it off is a no-op. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_uses_ports_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = bool(old_type.uses_ports) and not bool(new_type.uses_ports)

    if not turning_off:
        return None

    usage: dict[str, int] = get_port_usage_of_type(request_user, old_type)

    if not usage[UsesPortsUsageKey.PORT_COUNT.value]:
        return None

    return USES_PORTS_DISABLE_MESSAGE.format(
        port_count=usage[UsesPortsUsageKey.PORT_COUNT.value],
        object_count=usage[UsesPortsUsageKey.OBJECT_COUNT.value],
    )


def guard_uses_ports_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'uses_ports' off while ports of the Type still exist

    The route-level wrapper around `uses_ports_change_blocker`. 400 follows the codebase convention
    for business-rule rejections, like the location-field and selectable-as-parent guards beside it

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the flag may not be turned off
    """
    blocker: str | None = uses_ports_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def selectable_as_parent_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not turn 'selectable_as_parent' off, if it may not

    A CmdbType may only stop being selectable as a parent once no CmdbObject of that type is placed
    in the location tree; otherwise a placed object of a now-non-selectable type would remain in the
    tree (and could still act as a parent) while its type forbids it. Only the true -> false
    transition is guarded - keeping it off, or turning it on, is always allowed. The reason is
    returned instead of raised so both write paths can use it: the route aborts with it
    (`guard_selectable_as_parent_change`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    turning_off: bool = old_type.selectable_as_parent and not new_type.selectable_as_parent

    if not turning_off:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot disable 'selectable as parent': "
        f"{len(object_public_ids)} Object(s) of this Type are placed in the location tree. "
    )


def guard_selectable_as_parent_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update turns 'selectable_as_parent' off while objects of the type are placed

    The route-level wrapper around `selectable_as_parent_change_blocker`. 400 follows the codebase
    convention for business-rule rejections (the same as the location-field removal guard)

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when 'selectable_as_parent' may not be turned off
    """
    blocker: str | None = selectable_as_parent_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def count_objects_of_type(objects_manager: ObjectsManager, type_id: int) -> int:
    """
    Counts every CmdbObject of a CmdbType - the one question the delete guard and its pre-check both ask

    Active and inactive objects alike, and unscoped by the object ACL: an ACL lives on the Type, so a
    scoped count of one Type is either the total or 0, and a 0 would offer a delete the guard refuses

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        type_id (int): public_id of the CmdbType

    Raises:
        ObjectsManagerGetError: When the count failed

    Returns:
        int: The number of CmdbObjects of the Type
    """
    return objects_manager.count_documents({CmdbObjectKey.TYPE_ID: type_id})


def verify_type_deletable(
    request_user: CmdbUser,
    public_id: int,
    to_delete_type: dict[str, Any] | None = None
) -> None:
    """
    Confirms a CmdbType can be safely deleted, aborting the request when it cannot

    Aborts with HTTP 404 when the CmdbType does not exist, and with HTTP 400 when at least one
    CmdbObject of this CmdbType still exists, at least one CmdbReport still references it, or at
    least one other CmdbType pulls fields from it through a reference section. 400 follows the
    codebase convention for business-rule rejections (CLAUDE.md) - the same convention the
    location-field removal guard uses.

    The reference-section check is the type-level half of
    `referenced_section_removal_blocker`: deleting the referenced type leaves the dependent's
    ref-section pointing at a type_id that no longer resolves, which loses the referenced block from
    every object view of that type just as deleting the single section does

    Args:
        request_user (CmdbUser): User performing the request
        public_id (int): public_id of the CmdbType being checked
        to_delete_type (dict[str, Any] | None): The CmdbType document to delete, or None
            when the lookup already returned no result
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)
    reports_manager: ReportsManager = ManagerProvider.get_manager(ManagerType.REPORTS, request_user)

    if not to_delete_type:
        abort(404, TYPE_NOT_FOUND_MESSAGE.format(public_id=public_id))

    # Only possible to delete types when there are no objects
    if count_objects_of_type(objects_manager, public_id) > 0:
        abort(400, "Delete not possible if Objects of this Type exist!")

    # Only possible to delete types when there are no reports using it
    reports_count = reports_manager.count_documents({ReportKey.TYPE_ID: public_id})

    if reports_count > 0:
        abort(400, "Delete not possible if Reports exist which are using this Type!")

    # Only possible to delete types no other type references in a ref-section. Self-references are
    # excluded: a type whose own ref-section points at itself goes away with it
    referencing_types: list[dict[str, Any]] = get_types_referencing_section(
        request_user, public_id, exclude_type_id=public_id,
    )

    if referencing_types:
        abort(400, REFERENCED_TYPE_DELETE_MESSAGE.format(
            dependents=describe_section_dependents(referencing_types),
        ))


def location_field_removal_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not remove the CmdbType's location field, if it may not

    A CmdbType's location field may only be dropped once no CmdbObject of that type still stores a
    location value, otherwise those stored values would be silently orphaned. The reason is returned
    instead of raised so both write paths can use it: the route aborts with it
    (`guard_location_field_removal`), the type import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the removal is refused, or None when the update is allowed
    """
    removing_location_field: bool = get_location_field(old_type) is not None and get_location_field(new_type) is None

    if not removing_location_field:
        return None

    object_public_ids: list[int] = get_objects_using_location_field(request_user, old_type)

    if not object_public_ids:
        return None

    return (
        "Cannot remove the location field: "
        f"{len(object_public_ids)} Object(s) of this Type still have a location value. "
    )


def guard_location_field_removal(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update removes the location field while CmdbObjects still hold a location value

    The route-level wrapper around `location_field_removal_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when the location field may not be removed
    """
    blocker: str | None = location_field_removal_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def type_has_objects(request_user: CmdbUser, type_id: int) -> bool:
    """
    Whether at least one CmdbObject of the CmdbType exists

    One count, no documents loaded. Shared by the identifier guards below, which only refuse a change
    once there is stored data it could damage - a Type still being designed may be reshaped freely

    Args:
        request_user (CmdbUser): User performing the request
        type_id (int): public_id of the CmdbType

    Returns:
        bool: True when the Type has at least one Object
    """
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, request_user)

    return objects_manager.count_documents({CmdbObjectKey.TYPE_ID: type_id}) > 0


def describe_identifier_swap(old_names: set[str], new_names: set[str]) -> tuple[list[str], list[str]] | None:
    """
    Reports the removed and added identifiers of an edit, but only when it looks like a rename

    A field and a multi-data-section are identified by their **name** and by nothing else - there is
    no stable id underneath - so a rename is indistinguishable from one removal plus one addition in
    the same write. That is precisely what this detects: identifiers disappearing *and* appearing
    together. A pure removal or a pure addition is not a rename and is not reported

    Args:
        old_names (set[str]): The identifiers the stored CmdbType declares
        new_names (set[str]): The identifiers the update would persist

    Returns:
        tuple[list[str], list[str]] | None: (removed, added), sorted, or None when the edit does not
            have the shape of a rename
    """
    removed: set[str] = old_names - new_names
    added: set[str] = new_names - old_names

    if not removed or not added:
        return None

    return sorted(removed), sorted(added)


def field_identifier_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not rename a field identifier, if it may not

    **A field's `name` is its identifier and is immutable once the Type has Objects.** Every
    CmdbObject stores its values keyed by that name, and the realignment that follows a Type update
    reads a rename as one removal plus one addition: the Object loses the value it held and gains an
    empty field. The same is true of a multi-data-section row. Nothing about the payload distinguishes
    a rename from a deliberate remove-plus-add, so the shape itself is refused and the caller is asked
    to perform the two as separate updates.

    This covers ordinary AND multi-data-section fields, because a Type declares every field in its
    flat `fields` list and its sections only reference them by name.

    Only applies once the Type has Objects: a Type still being designed carries no values to lose, and
    the sibling guards are conditioned the same way. The reason is returned rather than raised so both
    write paths can use it - the route aborts with it (`guard_field_identifier_change`), the type
    import reports it per entry

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    swap = describe_identifier_swap(
        {field[FieldKey.NAME] for field in old_type.fields},
        {field[FieldKey.NAME] for field in new_type.fields},
    )

    if swap is None or not type_has_objects(request_user, old_type.public_id):
        return None

    removed, added = swap

    return FIELD_IDENTIFIER_IMMUTABLE_MESSAGE.format(
        removed=', '.join(removed), added=', '.join(added),
    )


def guard_field_identifier_change(request_user: CmdbUser, old_type: CmdbType, new_type: CmdbType) -> None:
    """
    Aborts 400 when an update would rename a field identifier while the CmdbType has Objects

    The route-level wrapper around `field_identifier_change_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when a field identifier would change
    """
    blocker: str | None = field_identifier_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)


def mds_section_identifier_change_blocker(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> str | None:
    """
    Reports why an update may not rename a multi-data-section identifier, if it may not

    **A multi-data-section's `name` is the `section_id` every CmdbObject stores its rows under.** The
    MDS propagation matches sections on `(type, name)`, so a renamed section reads as a section the
    Type no longer declares - and every Object drops **all** of its rows for it, not just one value.
    That makes this the most destructive of the identifier renames, and it is refused in the same
    shape: identifiers disappearing and appearing in one write.

    Only applies once the Type has Objects, like its field counterpart

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Returns:
        str | None: The reason the change is refused, or None when the update is allowed
    """
    swap = describe_identifier_swap(old_type.get_mds_section_ids(), new_type.get_mds_section_ids())

    if swap is None or not type_has_objects(request_user, old_type.public_id):
        return None

    removed, added = swap

    return MDS_SECTION_IDENTIFIER_IMMUTABLE_MESSAGE.format(
        removed=', '.join(removed), added=', '.join(added),
    )


def guard_mds_section_identifier_change(
    request_user: CmdbUser,
    old_type: CmdbType,
    new_type: CmdbType,
) -> None:
    """
    Aborts 400 when an update would rename a multi-data-section while the CmdbType has Objects

    The route-level wrapper around `mds_section_identifier_change_blocker`

    Args:
        request_user (CmdbUser): User performing the request
        old_type (CmdbType): State of the CmdbType before the update
        new_type (CmdbType): State of the CmdbType the update would persist

    Raises:
        HTTPException: 400 when a multi-data-section identifier would change
    """
    blocker: str | None = mds_section_identifier_change_blocker(request_user, old_type, new_type)

    if blocker:
        abort(400, blocker)
