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
The steps of the bulk object delete (`DELETE /objects/delete/<ids>`)

The route runs them in a fixed order - every guard for the whole selection first, then the
risk-assessment cascade, then one delete per target with its side effects, then the selection-wide
clean-up - so a refused selection changes nothing. The managers are resolved once for the whole
selection (`BulkDeleteManagers`) instead of once per target
"""
from dataclasses import dataclass
from typing import Any

from flask import abort

from cmdb.manager import LocationsManager, ObjectsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.port_connections_manager import PortConnectionsManager
from cmdb.manager.port_interface_links_manager import PortInterfaceLinksManager
from cmdb.manager.ports_manager import PortsManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, ObjectWriteVerb
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.port_routes.port_object_hooks import (
    handle_object_deleted as handle_port_object_deleted,
)
from cmdb.interface.rest_api.routes.rack_routes.rack_object_hooks import (
    handle_object_deleted as handle_rack_object_deleted,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    handle_create_object_log,
    handle_delete_invalid_object_relations,
    handle_delete_object_location,
    handle_notify_webhooks,
)
from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError
# -------------------------------------------------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BulkDeleteManagers:
    """
    The managers a bulk object delete uses, resolved once for every target

    Attributes:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        types_manager (TypesManager): db interface for CmdbTypes
        locations_manager (LocationsManager): Removes each target's CmdbLocation, promoting its children
        ports_manager (PortsManager): Removes the ports a target owns
        port_connections_manager (PortConnectionsManager): Removes the connections of those ports
        port_interface_links_manager (PortInterfaceLinksManager): Removes the links of those ports
    """
    objects_manager: ObjectsManager
    types_manager: TypesManager
    locations_manager: LocationsManager
    ports_manager: PortsManager
    port_connections_manager: PortConnectionsManager
    port_interface_links_manager: PortInterfaceLinksManager

    @classmethod
    def for_request(cls, request_user: CmdbUser) -> 'BulkDeleteManagers':
        """
        Resolves the caller's managers once, for the whole selection

        Args:
            request_user (CmdbUser): The CmdbUser making the request

        Returns:
            BulkDeleteManagers: The six managers, bound to the caller's database
        """
        return cls(
            objects_manager=ManagerProvider.get_manager(ManagerType.OBJECTS, request_user),
            types_manager=ManagerProvider.get_manager(ManagerType.TYPES, request_user),
            locations_manager=ManagerProvider.get_manager(ManagerType.LOCATIONS, request_user),
            ports_manager=ManagerProvider.get_manager(ManagerType.PORTS, request_user),
            port_connections_manager=ManagerProvider.get_manager(ManagerType.PORT_CONNECTIONS, request_user),
            port_interface_links_manager=ManagerProvider.get_manager(ManagerType.PORT_INTERFACE_LINKS, request_user),
        )


def load_delete_target_types(types_manager: TypesManager, targets: list[dict[str, Any]]) -> dict[int, CmdbType]:
    """
    Reads the CmdbTypes of a delete selection in one lookup

    Args:
        types_manager (TypesManager): db interface for CmdbTypes
        targets (list[dict[str, Any]]): The CmdbObject documents to delete

    Returns:
        dict[int, CmdbType]: public_id -> CmdbType for every type the selection uses that exists
    """
    type_ids: list[int] = [
        target[CmdbObjectKey.TYPE_ID.value] for target in targets if target.get(CmdbObjectKey.TYPE_ID.value) is not None
    ]

    return types_manager.get_types_lookup(type_ids)


def guard_delete_target_types(
        objects_manager: ObjectsManager,
        request_user: CmdbUser,
        targets: list[dict[str, Any]],
        type_map: dict[int, CmdbType],
    ) -> None:
    """
    Refuses the whole selection when any target's type is missing or may not be deleted from

    Evaluated for EVERY target before anything is deleted: checking inside the delete loop would abort mid-way,
    after the risk-assessment cascade and the earlier targets' deletes

    Args:
        objects_manager (ObjectsManager): db interface for CmdbObjects
        request_user (CmdbUser): The CmdbUser making the request
        targets (list[dict[str, Any]]): The CmdbObject documents to delete
        type_map (dict[int, CmdbType]): The selection's types (``load_delete_target_types``)

    Raises:
        HTTPException: 404 when a target's type is missing
        ObjectsManagerDeleteError / AccessDeniedError: When a type is deactivated or its ACL denies DELETE
    """
    for target in targets:
        type_id: int | None = target.get(CmdbObjectKey.TYPE_ID.value)
        target_type: CmdbType | None = type_map.get(type_id)

        if target_type is None:
            abort(404, f"Type of Object with ID:{target.get(CmdbObjectKey.PUBLIC_ID.value)} not found in database!")

        objects_manager.guard_writable_type(
            type_id, request_user, AccessControlPermission.DELETE,
            ObjectsManagerDeleteError, ObjectWriteVerb.REMOVED.value, target_type,
        )


def delete_selected_object(
        request_user: CmdbUser,
        target: CmdbObject,
        target_type: CmdbType,
        managers: BulkDeleteManagers,
    ) -> None:
    """
    Deletes one target of a guarded selection and runs its own side effects

    In order: its CmdbLocation goes and the location's direct children are promoted onto its parent (keeping
    the tree connected); the object is deleted with its already resolved type (the risk-assessment cascade ran
    for the whole selection); its now-invalid relations go; the Rack state it leaves behind is removed; the
    ports it owns - stored outside its document, so nothing else removes them - go with their connections and
    links; a DELETE webhook is sent and a deletion log written. The selection-wide clean-up (object groups,
    references, the cloud count) is the route's, once for all targets

    Args:
        request_user (CmdbUser): The CmdbUser making the request
        target (CmdbObject): The object to delete
        target_type (CmdbType): Its type, resolved for the selection
        managers (BulkDeleteManagers): The selection's managers
    """
    public_id: int = target.get_public_id()
    target_document: dict[str, Any] = CmdbObject.to_json(target)

    handle_delete_object_location(request_user, public_id, managers.locations_manager, managers.objects_manager)

    managers.objects_manager.delete_object(
        public_id, request_user, AccessControlPermission.DELETE, object_type=target_type,
    )

    handle_delete_invalid_object_relations(request_user, public_id)
    handle_rack_object_deleted(
        request_user, target_document, managers.objects_manager, managers.types_manager, managers.locations_manager,
    )
    handle_port_object_deleted(
        request_user, target_document, managers.ports_manager, managers.port_connections_manager,
        managers.port_interface_links_manager,
    )
    handle_notify_webhooks(request_user, target, WebhookEventType.DELETE)
    handle_create_object_log(request_user, target, LogAction.DELETE)
