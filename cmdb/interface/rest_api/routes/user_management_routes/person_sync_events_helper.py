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
The change logs and webhooks of what the user -> person sync wrote

The sync engine writes in the framework, which may not import this layer; it hands what it wrote to the callbacks
built here (``person_sync.sync_engine.SyncEvents``). They emit what the object routes emit, credited to the acting
user and best-effort like every log and webhook: a created person its CREATE entry and webhook; an edit its EDIT entry
(comment *"Synced from user management"*) and UPDATE webhook when a field changed, and its ACTIVE_CHANGE entry when the
active state did - an edit that only changed the state sends the UPDATE webhook once, with the state - and an EDIT entry
*"Unlinked from user management"* (no changes) when it removed the object's link, so a former user's change log says
that user management let go of it even when nothing else changed. A sync that
linked or unlinked a stored object moved the ConfigItem count, which is reported to the service portal like after any
object create or delete (``config_item_sync.handle_sync_config_item_count``: hosted cloud only, best-effort)
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.manager import LogsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.object_model import CmdbObject, ObjectChangeKey
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.framework.object_edit import ObjectWrite
from cmdb.framework.config_item_sync import handle_sync_config_item_count
from cmdb.framework.person_sync.sync_engine import SyncEvents
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import send_webhook_event
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import ObjectLogComment
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_side_effects_helper import (
    build_object_write_emitter,
    handle_create_object_log,
    handle_notify_webhooks,
    log_object_change,
)

from cmdb.errors.models.cmdb_object import CmdbObjectToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'has_field_changes',
    'is_unlinked',
    'build_sync_events',
]

LOGGER: Logger = getLogger(__name__)

# The key of the state an UPDATE webhook names for an edit that only changed the active state
STATE_CHANGE_KEY: str = 'state'


def has_field_changes(changes: dict[str, Any]) -> bool:
    """
    Whether an edit's diff names any field or multi-data-section change

    Args:
        changes (dict[str, Any]): The diff (``{'old': [...], 'new': [...]}``, plus ``multi_data_sections``)

    Returns:
        bool: True when something besides the active state changed
    """
    return any(changes.get(key) for key in (ObjectChangeKey.OLD.value, ObjectChangeKey.NEW.value)) or any(
        value for key, value in changes.items() if key not in (ObjectChangeKey.OLD.value, ObjectChangeKey.NEW.value)
    )


def is_unlinked(write: ObjectWrite) -> bool:
    """
    Whether an edit removed the object's link to user management - a former user's person

    Args:
        write (ObjectWrite): The stored edit

    Returns:
        bool: True when the object was linked before and is not after
    """
    return write.before.system_ref is not None and write.after.system_ref is None


def build_sync_events(acting_user: CmdbUser) -> SyncEvents:
    """
    Builds the callbacks the sync engine hands its writes to, credited to the acting user

    The LogsManager is resolved on the first state change and reused

    Args:
        acting_user (CmdbUser): The user credited with the sync's writes

    Returns:
        SyncEvents: The create, the edit and the ConfigItem callback
    """
    emit_edit = build_object_write_emitter(acting_user, ObjectLogComment.SYNCED_FROM_USER_MANAGEMENT.value)
    resolved: list[LogsManager] = []

    def on_create(created: CmdbObject) -> None:
        handle_create_object_log(acting_user, created, LogAction.CREATE)
        handle_notify_webhooks(acting_user, created, WebhookEventType.CREATE)

    def _logs_manager() -> LogsManager:
        if not resolved:
            resolved.append(ManagerProvider.get_manager(ManagerType.LOGS, acting_user))

        return resolved[0]

    def on_edit(write: ObjectWrite) -> None:
        state_changed: bool = write.before.active != write.after.active

        if has_field_changes(write.changes):
            emit_edit(write)
        elif state_changed:
            try:
                send_webhook_event(acting_user, WebhookEventType.UPDATE, CmdbObject.to_json(write.before),
                                   CmdbObject.to_json(write.after), {STATE_CHANGE_KEY: write.after.active})
            except CmdbObjectToJsonError as err:
                LOGGER.error("[on_edit] Send Webhook Event Exception: %s, Type:%s", err, type(err))

        if state_changed:
            log_object_change(
                acting_user, _logs_manager(), LogAction.ACTIVE_CHANGE, write.after,
                ObjectLogComment.ACTIVE_CHANGED.value,
                changes={ObjectChangeKey.OLD.value: write.before.active, ObjectChangeKey.NEW.value: write.after.active},
            )

        if is_unlinked(write):
            log_object_change(
                acting_user, _logs_manager(), LogAction.EDIT, write.after,
                ObjectLogComment.UNLINKED_FROM_USER_MANAGEMENT.value, version=write.after.version,
                changes={ObjectChangeKey.OLD.value: [], ObjectChangeKey.NEW.value: []},
            )

    def on_config_items_changed() -> None:
        handle_sync_config_item_count(acting_user)

    return SyncEvents(on_create=on_create, on_edit=on_edit, on_config_items_changed=on_config_items_changed)
