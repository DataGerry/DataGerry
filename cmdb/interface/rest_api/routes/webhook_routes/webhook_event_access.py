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
The object ACL of the webhook delivery log

A CmdbWebhookEvent carries the object it was sent for - ``object_before``, ``object_after`` and the field-level
diff in ``changes``. Reading the log needs only the webhook view right, so the object's own READ ACL is applied
here: for an object whose type the caller may not read, the three keys are blanked (``null``) and the rest of the
row - when, to which webhook, with which answer - stays. The log stays complete for whoever diagnoses a webhook,
and the values are gone.

The list route blanks them IN THE PIPELINE, as the first stage (``build_event_masking_stage``): the caller's
``?filter=`` is a list of aggregation stages that runs after it, so a ``$match`` on a field value cannot find a
masked event either. The single read applies the same rule to the document (``mask_event_object_values``). Both
decide on the event's object type - ``object_after.type_id``, else ``object_before.type_id`` for a delete - against
the caller's denied types (``denied_object_type_ids``), which is one projected read and none when no type has an
active ACL; nothing is denied then, and no stage is added at all.
"""
from typing import Any, Collection

from cmdb.models.object_model.cmdb_object_key_enum import CmdbObjectKey
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.webhook_event_constants import OBJECT_VALUE_KEYS, WebhookEventKey
from cmdb.security.acl.builder import resolve_denied_type_ids
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_event_masking_stage',
    'denied_object_type_ids',
    'event_object_type_id',
    'mask_event_object_values',
]

# The event's object type, as an aggregation expression: the state after the operation, else the one before it
_EVENT_TYPE_EXPRESSION: dict[str, Any] = {
    '$ifNull': [
        f'${WebhookEventKey.OBJECT_AFTER.value}.{CmdbObjectKey.TYPE_ID.value}',
        f'${WebhookEventKey.OBJECT_BEFORE.value}.{CmdbObjectKey.TYPE_ID.value}',
    ],
}


def denied_object_type_ids(request_user: CmdbUser) -> list[int]:
    """
    The CmdbTypes whose objects the caller may not READ

    Args:
        request_user (CmdbUser): The user issuing the request

    Raises:
        BaseManagerGetError: When the types could not be read

    Returns:
        list[int]: public_ids of the denied types; empty when the caller may read every object
    """
    return resolve_denied_type_ids(request_user, AccessControlPermission.READ)


def event_object_type_id(event: dict[str, Any]) -> Any:
    """
    The type of the object an event was sent for

    Args:
        event (dict[str, Any]): The stored CmdbWebhookEvent

    Returns:
        Any: ``object_after.type_id``, else ``object_before.type_id``; None when neither snapshot carries one
    """
    for key in (WebhookEventKey.OBJECT_AFTER, WebhookEventKey.OBJECT_BEFORE):
        snapshot: Any = event.get(key.value)

        if isinstance(snapshot, dict) and snapshot.get(CmdbObjectKey.TYPE_ID.value) is not None:
            return snapshot[CmdbObjectKey.TYPE_ID.value]

    return None


def mask_event_object_values(event: dict[str, Any], denied_type_ids: Collection[int]) -> dict[str, Any]:
    """
    Blanks the object values of an event whose object the caller may not read

    Args:
        event (dict[str, Any]): The stored CmdbWebhookEvent; not modified
        denied_type_ids (Collection[int]): The caller's denied types

    Returns:
        dict[str, Any]: The event as it may be shown - a copy with the value keys set to None when its object's
            type is denied, the event itself otherwise
    """
    if event_object_type_id(event) not in denied_type_ids:
        return event

    return {**event, **{key.value: None for key in OBJECT_VALUE_KEYS}}


def build_event_masking_stage(denied_type_ids: list[int]) -> dict[str, Any] | None:
    """
    The pipeline stage blanking the object values of every event whose object the caller may not read

    Placed before the caller's own stages, so nothing after it sees the masked values. The same rule as
    ``mask_event_object_values``, as an aggregation expression

    Args:
        denied_type_ids (list[int]): The caller's denied types

    Returns:
        dict[str, Any] | None: The ``$set`` stage, or None when nothing is denied - no stage is needed then
    """
    if not denied_type_ids:
        return None

    is_denied: dict[str, Any] = {'$in': [_EVENT_TYPE_EXPRESSION, list(denied_type_ids)]}

    return Builder.set_({
        key.value: {'$cond': [is_denied, None, f'${key.value}']} for key in OBJECT_VALUE_KEYS
    })
