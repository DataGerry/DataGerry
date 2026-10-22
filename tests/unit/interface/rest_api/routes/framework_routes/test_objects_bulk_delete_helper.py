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
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.errors.manager import BaseManagerGetError, BaseManagerUpdateError
from cmdb.errors.manager.objects_manager import ObjectsManagerDeleteError, ObjectsManagerUpdateError
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
from cmdb.errors.manager.ports_manager import PortsManagerGetError
from cmdb.errors.manager.rack_mounts_manager import RackMountsManagerDeleteError
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import ObjectWriteVerb
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_bulk_delete_helper import (
    BulkDeleteManagers,
    cleanup_deleted_selection,
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


# -------------------------------------------------------------------------------------------------------------------- #
#                                   after a target is deleted, every step is best-effort                               #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('failing_step, failure', [
    ('handle_rack_object_deleted', RackMountsManagerDeleteError('db')),
    ('handle_port_object_deleted', PortsManagerGetError('db')),
], ids=['rack', 'ports'])
def test_a_failing_hook_after_the_delete_lets_the_rest_run(failing_step: str, failure: Exception) -> None:
    """The target is gone: the webhook and the log still go out"""
    managers = _managers()
    target = MagicMock()
    target.get_public_id.return_value = TARGET_ID
    mocks: dict[str, MagicMock] = {step: MagicMock() for step in DELETE_SIDE_EFFECTS}
    mocks[failing_step].side_effect = failure
    patches = [patch(f'{BULK_PATH}.{step}', mock) for step, mock in mocks.items()]
    patches.append(patch(f'{BULK_PATH}.CmdbObject.to_json', return_value={'public_id': TARGET_ID}))

    for active in patches:
        active.start()

    try:
        delete_selected_object(MagicMock(), target, SimpleNamespace(), managers)
    finally:
        for active in reversed(patches):
            active.stop()

    mocks['handle_notify_webhooks'].assert_called_once()
    mocks['handle_create_object_log'].assert_called_once()


SELECTION_STEPS: tuple[str, ...] = (
    'handle_delete_invalid_object_relations',
    'handle_delete_object_attachments',
    'handle_delete_from_object_groups',
)


def _patched_selection_steps() -> tuple[dict[str, MagicMock], list[Any]]:
    """The three selection-wide side-effect functions, patched"""
    mocks: dict[str, MagicMock] = {step: MagicMock() for step in SELECTION_STEPS}

    return mocks, [patch(f'{BULK_PATH}.{step}', mock) for step, mock in mocks.items()]


def test_the_selection_cleanup_covers_exactly_the_deleted_ids() -> None:
    """Relations, attachments, groups and references - each once, for the deleted ids"""
    objects_manager, request_user = MagicMock(), MagicMock()
    mocks, patches = _patched_selection_steps()

    for active in patches:
        active.start()

    try:
        cleanup_deleted_selection(request_user, objects_manager, [TARGET_ID, SECOND_TARGET_ID])
    finally:
        for active in reversed(patches):
            active.stop()

    for step in SELECTION_STEPS:
        mocks[step].assert_called_once_with(request_user, [TARGET_ID, SECOND_TARGET_ID])
    objects_manager.delete_all_object_references.assert_called_once_with([TARGET_ID, SECOND_TARGET_ID])


def test_nothing_deleted_needs_no_cleanup() -> None:
    """A selection that failed at its first target costs no cleanup query"""
    objects_manager = MagicMock()
    mocks, patches = _patched_selection_steps()

    for active in patches:
        active.start()

    try:
        cleanup_deleted_selection(MagicMock(), objects_manager, [])
    finally:
        for active in reversed(patches):
            active.stop()

    for step in SELECTION_STEPS:
        mocks[step].assert_not_called()
    objects_manager.delete_all_object_references.assert_not_called()


@pytest.mark.parametrize('failing, failure', [
    ('handle_delete_invalid_object_relations', BaseManagerGetError('db')),
    ('handle_delete_from_object_groups', BaseManagerUpdateError('db')),
    ('references', ObjectsManagerUpdateError('db')),
], ids=['relations', 'groups', 'references'])
def test_one_failing_selection_step_lets_the_others_run(failing: str, failure: Exception) -> None:
    """Each step is best-effort on its own"""
    objects_manager = MagicMock()
    mocks, patches = _patched_selection_steps()

    if failing == 'references':
        objects_manager.delete_all_object_references.side_effect = failure
    else:
        mocks[failing].side_effect = failure

    for active in patches:
        active.start()

    try:
        cleanup_deleted_selection(MagicMock(), objects_manager, [TARGET_ID])
    finally:
        for active in reversed(patches):
            active.stop()

    for step in SELECTION_STEPS:
        mocks[step].assert_called_once()
    objects_manager.delete_all_object_references.assert_called_once()


@pytest.mark.parametrize('failing, failure, step_name', [
    ('handle_delete_invalid_object_relations', BaseManagerGetError('db'), 'relations'),
    ('handle_delete_object_attachments', MediaFileManagerUpdateError('db'), 'attachments'),
    ('handle_delete_from_object_groups', BaseManagerUpdateError('db'), 'object_groups'),
    ('references', ObjectsManagerUpdateError('db'), 'references'),
], ids=['relations', 'attachments', 'groups', 'references'])
def test_a_failed_selection_step_names_the_deleted_ids(failing: str, failure: Exception, step_name: str,
                                                       caplog) -> None:
    """The marker line is what an operator repairs from: it names the step and exactly the deleted ids"""
    objects_manager = MagicMock()
    mocks, patches = _patched_selection_steps()

    if failing == 'references':
        objects_manager.delete_all_object_references.side_effect = failure
    else:
        mocks[failing].side_effect = failure

    for active in patches:
        active.start()

    try:
        with caplog.at_level('ERROR'):
            cleanup_deleted_selection(MagicMock(), objects_manager, [TARGET_ID, SECOND_TARGET_ID])
    finally:
        for active in reversed(patches):
            active.stop()

    assert f'step={step_name} objects={[TARGET_ID, SECOND_TARGET_ID]}' in caplog.text
