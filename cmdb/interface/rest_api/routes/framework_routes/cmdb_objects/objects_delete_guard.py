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
What may not be deleted: the pre-delete guards both object delete routes run, before anything is deleted

The IPAM licence (deleting an IPAM special-type object needs it), the IPAM delete invariants (a SUPERNET / SUBNET still
referenced) and the Cable CI guard. Evaluated for the whole selection first and aborting on the first violation, which
is what makes a bulk delete all-or-nothing. Every check is handed the target's already-resolved type - the bulk
route's one lookup for the selection, the single route's one read - so none of them reads it again
"""
from typing import Any

from flask import abort

from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.framework.ipam.enforcement import (
    enforce_delete_guards,
    format_errors_for_abort,
    object_delete_requires_ipam_license,
)
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked
from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import guard_cable_objects_delete
# -------------------------------------------------------------------------------------------------------------------- #

def guard_object_delete_license(
    types_manager: TypesManager,
    request_user: CmdbUser,
    target_object: dict[str, Any],
    object_type: CmdbType | None = None,
) -> None:
    """
    Blocks deleting an IPAM special-type object when the IPAM feature is not licensed

    A no-op unless the target is an IPAM special-type object. For such a target it aborts with HTTP
    403 on-premise when IPAM is unlicensed; it is a no-op in cloud/local mode and when IPAM is
    licensed

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The user performing the deletion
        target_object (dict[str, Any]): The CmdbObject document being deleted
        object_type (CmdbType | None): The target's type when the caller holds it already - then it is not read
    """
    if object_delete_requires_ipam_license(types_manager, target_object, object_type):
        abort_if_feature_locked(LicenseFeature.IPAM, request_user)


def guard_objects_delete(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        request_user: CmdbUser,
        target_objects: list[dict[str, Any]],
        target_types: dict[int, CmdbType] | None = None,
    ) -> None:
    """
    Runs the full pre-delete guard for a WHOLE delete selection: IPAM license + IPAM invariants + cables

    The one place both delete routes state what may not be deleted, so a rule added here lands on the
    single and the bulk delete at once. Evaluated before anything is deleted and aborting on the first
    violation, which is what makes a bulk delete all-or-nothing: refusing halfway would leave the
    earlier targets already gone.

    Per target: the IPAM license guard (deleting an IPAM special-type object needs a valid license) and
    the IPAM delete invariants (e.g. a SUPERNET / SUBNET still referenced by other IPAM objects), both
    handed the target's type from ``target_types``. For the selection as a whole: the Cable CI guard,
    which costs one query however many objects are being deleted - see `guard_cable_objects_delete`. A
    non-IPAM, non-Cable selection with no dangling references is a no-op

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The CmdbUser performing the deletion
        target_objects (list[dict[str, Any]]): The CmdbObject documents being deleted
        target_types (dict[int, CmdbType] | None): The targets' types by public_id, as the caller resolved them; a
            target whose type is not in it is read as before

    Raises:
        HTTPException: 403 when a gated delete is unlicensed, 400 on an IPAM invariant violation or
            when a Cable CI in the selection is still used by a CmdbPortConnection
    """
    for target_object in target_objects:
        target_type: CmdbType | None = (target_types or {}).get(target_object.get(CmdbObjectKey.TYPE_ID.value))

        guard_object_delete_license(types_manager, request_user, target_object, target_type)

        ipam_delete_errors: list[dict[str, Any]] = enforce_delete_guards(
            objects_manager,
            types_manager,
            target_object,
            target_type,
        )

        if ipam_delete_errors:
            abort(400, format_errors_for_abort(ipam_delete_errors))

    # A Port connection describes a physical patch and outlives its cable record, so a used Cable CI
    # is refused rather than cascaded or left dangling
    guard_cable_objects_delete(request_user, types_manager, target_objects)


def guard_object_delete(
        objects_manager: ObjectsManager,
        types_manager: TypesManager,
        request_user: CmdbUser,
        target_object: dict[str, Any],
        object_type: CmdbType | None = None,
    ) -> None:
    """
    Runs the full pre-delete guard for a single CmdbObject

    The one-target form of `guard_objects_delete`, kept because the single-object delete route reads
    exactly one object; the rules themselves live in the batched function so both routes cannot drift

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        request_user (CmdbUser): The CmdbUser performing the deletion
        target_object (dict[str, Any]): The CmdbObject document being deleted
        object_type (CmdbType | None): The target's type when the caller holds it already - then it is not read
    """
    target_types: dict[int, CmdbType] = {object_type.public_id: object_type} if object_type is not None else {}

    guard_objects_delete(objects_manager, types_manager, request_user, [target_object], target_types)
