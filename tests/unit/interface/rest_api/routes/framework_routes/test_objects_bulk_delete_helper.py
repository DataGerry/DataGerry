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
Unit tests for cmdb_objects.objects_bulk_delete_helper

The bulk delete resolves its six managers once, reads the selection's types in one lookup, refuses the whole
selection when any target's type is missing or may not be deleted from, and deletes each target with its own
side effects in a fixed order
"""
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import ObjectWriteVerb
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_delete_helper import (
    BulkDeleteManagers,
    delete_selected_object,
    guard_delete_target_types,
    load_delete_target_types,
)
# -------------------------------------------------------------------------------------------------------------------- #

BULK_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_delete_helper'

TYPE_A: int = 1
TYPE_B: int = 2
MISSING_TYPE: int = 9
TARGET_ID: int = 11
SECOND_TARGET_ID: int = 12

DELETE_SIDE_EFFECTS: tuple[str, ...] = (
    'handle_delete_object_location',
    'handle_rack_object_deleted',
    'handle_port_object_deleted',
    'handle_notify_webhooks',
    'handle_create_object_log',
)


def _managers() -> BulkDeleteManagers:
    """Six MagicMock managers."""
    return BulkDeleteManagers(*(MagicMock() for _ in range(6)))


def test_the_managers_are_frozen() -> None:
    """The selection's managers cannot be swapped between targets"""
    managers = _managers()

    with pytest.raises(FrozenInstanceError):
        managers.objects_manager = MagicMock()  # type: ignore[misc]


def test_for_request_resolves_the_six_managers_once_for_the_caller() -> None:
    """Each kind once, bound to the caller"""
    request_user = MagicMock()

    with patch(f'{BULK_PATH}.ManagerProvider.get_manager', side_effect=lambda kind, _user: kind) as get_manager:
        managers = BulkDeleteManagers.for_request(request_user)

    kinds = [ManagerType.OBJECTS, ManagerType.TYPES, ManagerType.LOCATIONS, ManagerType.PORTS,
             ManagerType.PORT_CONNECTIONS, ManagerType.PORT_INTERFACE_LINKS]
    assert get_manager.call_args_list == [call(kind, request_user) for kind in kinds]
    assert managers.port_interface_links_manager == ManagerType.PORT_INTERFACE_LINKS


def test_the_selection_types_are_read_in_one_lookup_skipping_untyped_targets() -> None:
    """One get_types_lookup for every type id present; a target without one contributes nothing"""
    types_manager = MagicMock()
    targets = [{'type_id': TYPE_A}, {'type_id': TYPE_B}, {'public_id': TARGET_ID}]

    result = load_delete_target_types(types_manager, targets)

    types_manager.get_types_lookup.assert_called_once_with([TYPE_A, TYPE_B])
    assert result is types_manager.get_types_lookup.return_value


def test_every_target_type_is_guarded_for_delete() -> None:
    """The writable-type guard runs once per target, with DELETE, the delete error and the REMOVED verb"""
    objects_manager, request_user = MagicMock(), MagicMock()
    type_map = {TYPE_A: SimpleNamespace(), TYPE_B: SimpleNamespace()}

    guard_delete_target_types(objects_manager, request_user, [{'type_id': TYPE_A}, {'type_id': TYPE_B}], type_map)

    assert objects_manager.guard_writable_type.call_args_list == [
        call(type_id, request_user, AccessControlPermission.DELETE, ObjectsManagerDeleteError,
             ObjectWriteVerb.REMOVED.value, type_map[type_id])
        for type_id in (TYPE_A, TYPE_B)
    ]


def test_a_missing_type_refuses_the_selection_with_404() -> None:
    """The target's id is named, and no later target is checked"""
    objects_manager = MagicMock()
    targets = [{'type_id': MISSING_TYPE, 'public_id': TARGET_ID}, {'type_id': TYPE_A, 'public_id': SECOND_TARGET_ID}]

    with pytest.raises(HTTPException) as exc_info:
        guard_delete_target_types(objects_manager, MagicMock(), targets, {TYPE_A: SimpleNamespace()})

    assert exc_info.value.code == 404
    assert str(TARGET_ID) in exc_info.value.description
    objects_manager.guard_writable_type.assert_not_called()


def test_a_target_is_deleted_with_its_side_effects_in_order() -> None:
    """Location first, then the delete with the resolved type, then Rack, ports, webhook and log (relations: route)"""
    recorder = MagicMock()
    managers = _managers()
    recorder.attach_mock(managers.objects_manager.delete_object, 'delete_object')
    target = MagicMock()
    target.get_public_id.return_value = TARGET_ID
    target_type, request_user = SimpleNamespace(), MagicMock()
    patches = []

    for step in DELETE_SIDE_EFFECTS:
        mock = MagicMock()
        recorder.attach_mock(mock, step)
        patches.append(patch(f'{BULK_PATH}.{step}', mock))
    patches.append(patch(f'{BULK_PATH}.CmdbObject.to_json', return_value={'public_id': TARGET_ID}))

    for active in patches:
        active.start()

    try:
        delete_selected_object(request_user, target, target_type, managers)
    finally:
        for active in reversed(patches):
            active.stop()

    assert [name for name, _args, _kwargs in recorder.mock_calls] == [
        'handle_delete_object_location', 'delete_object', *DELETE_SIDE_EFFECTS[1:],
    ]
    managers.objects_manager.delete_object.assert_called_once_with(
        TARGET_ID, request_user, AccessControlPermission.DELETE, object_type=target_type,
    )
    recorder.handle_port_object_deleted.assert_called_once_with(
        request_user, {'public_id': TARGET_ID}, managers.ports_manager, managers.port_connections_manager,
        managers.port_interface_links_manager,
    )
    recorder.handle_notify_webhooks.assert_called_once_with(request_user, target, WebhookEventType.DELETE)
    recorder.handle_create_object_log.assert_called_once_with(request_user, target, LogAction.DELETE)
