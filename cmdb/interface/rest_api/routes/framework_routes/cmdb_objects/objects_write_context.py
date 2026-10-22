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
What one object write runs with: the caller, its managers, a location change, and a written update

`apply_object_update` validates, writes and then runs the write's consequences in a fixed order. Handing
the caller and every manager through each step one by one made the orchestrator outgrow pylint's locals
limit; these frozen values carry them instead. ``ObjectWriteContext`` and ``LocationChange`` hold handles, never
request data beyond the caller; ``WrittenObjectUpdate`` is what the write half of an update hands its finish half -
a bulk update writes every target before it finishes any
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from cmdb.manager import LocationsManager, LogsManager, ObjectsManager, TypesManager
from cmdb.interface.rest_api.routes.rack_routes.rack_location_target import RackLocationTarget
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

# Builds one target's full-object payload from that target's stored object and its type - how a bulk PATCH merges
# its field subset into each object, and how a PUT holds its payload to the object it replaces
ObjectPayloadBuilder = Callable[[CmdbObject, CmdbType], dict[str, Any]]


@dataclass(frozen=True)
class ObjectWriteContext:
    """
    The caller and the managers an object update runs with

    Attributes:
        request_user (CmdbUser): The CmdbUser making the request
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes (licence and invariant checks)
        logs_manager (LogsManager): Manager used to persist the edit log
        type_cache (dict[int, CmdbType]): Types already resolved, extended in place. A bulk update shares one
            context across its targets, which usually have the same type, so each distinct type is read once
        right_cache (dict[str, bool]): The answers to the right checks the update asks beyond the route's own, by
            right name, extended in place - so a bulk update reads the caller's group once, not once per target
    """
    request_user: CmdbUser
    objects_manager: ObjectsManager
    types_manager: TypesManager
    logs_manager: LogsManager
    type_cache: dict[int, CmdbType] = field(default_factory=dict)
    right_cache: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def for_request(cls, request_user: CmdbUser) -> 'ObjectWriteContext':
        """
        Resolves the caller's managers once, for every target of a request

        Args:
            request_user (CmdbUser): The CmdbUser making the request

        Returns:
            ObjectWriteContext: The caller, its objects / types / logs managers and an empty type cache
        """
        return cls(
            request_user=request_user,
            objects_manager=ManagerProvider.get_manager(ManagerType.OBJECTS, request_user),
            types_manager=ManagerProvider.get_manager(ManagerType.TYPES, request_user),
            logs_manager=ManagerProvider.get_manager(ManagerType.LOGS, request_user),
        )


@dataclass(frozen=True)
class LocationChange:
    """
    The location an object update places the object at, with the manager that keeps the location tree

    Only built when the candidate carries a location field. `parent` is None when the field is cleared

    Attributes:
        parent (int | None): public_id of the parent CmdbObject in the location tree, None when cleared
        locations_manager (LocationsManager): Manager resolved once for the checks before the write and the
            mirror after it
        rack_target (RackLocationTarget | None): The Rack the parent stands for, as the Rack check before the write
            resolved it - the membership reconcile after the write reuses it instead of reading it again
    """
    parent: int | None
    locations_manager: LocationsManager
    rack_target: RackLocationTarget | None = None


@dataclass(frozen=True)
class WrittenObjectUpdate:
    """
    One object update whose document is written and whose consequences have not run yet

    Attributes:
        obj_id (int): public_id of the updated CmdbObject
        new_data (dict[str, Any]): The written document (also the update's response entry)
        previous_object (dict[str, Any]): The object as stored before the write
        current_object (CmdbObject): The stored object before the write
        current_type (CmdbType): The object's type
        location_change (LocationChange | None): The placement validated before the write, None without one
        location_name (str | None): The transient display name for the location mirror
        update_object_instance (CmdbObject): The written candidate as a CmdbObject, with its new version
        changes (dict[str, Any]): The field-level diff the version bump was computed from
        update_comment (str): The edit log's comment, '' when none
    """
    obj_id: int
    new_data: dict[str, Any]
    previous_object: dict[str, Any]
    current_object: CmdbObject
    current_type: CmdbType
    location_change: LocationChange | None
    location_name: str | None
    update_object_instance: CmdbObject
    changes: dict[str, Any]
    update_comment: str
