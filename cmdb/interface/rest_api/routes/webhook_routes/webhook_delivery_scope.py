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
Which webhooks may receive one object event: those whose owner may read the object

A delivery carries the whole object, before and after, to the webhook's URL - outside the installation, where no
type ACL applies any more. So **a webhook only receives the writes of objects its owner may READ**: the owner is the
user who last saved the webhook (``owner_id``, set by the server on every create and update - whoever sets the URL
decides where the data goes), and each event is checked against that user's groups on the object's CmdbType, the
check ``GET /objects/<id>`` applies.

A webhook whose owner no longer exists, is deactivated, or was never recorded receives nothing. An object whose type
cannot be read back (deleted) is not refused for it - the rule the type ACL stage applies everywhere. A skipped
delivery leaves no trace: the owner was never entitled to the event, and a record of it would itself say that a
hidden object changed
"""
from typing import Any

from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.helpers import has_type_document_reach, object_access_allowed
from cmdb.security.acl.permission import AccessControlPermission

from cmdb.models.webhook_model.webhook_constants import WebhookKey
# -------------------------------------------------------------------------------------------------------------------- #

# The key a CmdbObject document names its type by
OBJECT_TYPE_ID_KEY: str = 'type_id'


def event_type_id(object_before: dict[str, Any] | None, object_after: dict[str, Any] | None) -> int | None:
    """
    The CmdbType an object event is about

    Args:
        object_before (dict[str, Any] | None): The object before the change (an update or a delete)
        object_after (dict[str, Any] | None): The object after the change (a create or an update)

    Returns:
        int | None: The object's type_id - the state after the change wins - or None when neither carries one
    """
    for document in (object_after, object_before):
        if document and isinstance(document.get(OBJECT_TYPE_ID_KEY), int):
            return document[OBJECT_TYPE_ID_KEY]

    return None


def owner_may_receive(owner: CmdbUser | None, type_document: dict[str, Any] | None,
                      states: tuple[dict[str, Any], ...] = ()) -> bool:
    """
    Whether one webhook owner may receive an event about an object

    The event carries the object's states before and after the change: the owner must be allowed to view every one of
    them - its scope conditions judged per state (phase 9, R25), so a change moving the object into or out of the
    owner's scope delivers nothing

    Args:
        owner (CmdbUser | None): The webhook's owner, or None when it does not exist (any more)
        type_document (dict[str, Any] | None): The object's CmdbType document, or None when it cannot be read
        states (tuple[dict[str, Any], ...]): The object states the event carries

    Returns:
        bool: True when the owner exists, is active, reaches the Type and may view the object in every state the event
            carries
    """
    if owner is None or not owner.active:
        return False

    if type_document is None:
        return True

    # The Type gate first: a Type document without its public_id, or one the owner reaches no object of, refuses even
    # an event without states
    if not has_type_document_reach(type_document, owner, AccessControlPermission.READ):
        return False

    return all(object_access_allowed(state, owner, AccessControlPermission.READ) for state in states)


def scope_webhooks_to_owners(
        webhooks: list[Any],
        type_document: dict[str, Any] | None,
        owners: dict[int, CmdbUser],
        states: tuple[dict[str, Any], ...] = ()) -> list[Any]:
    """
    Keeps the webhooks whose owner may receive the event

    Args:
        webhooks (list[Any]): The active webhooks subscribed to the operation
        type_document (dict[str, Any] | None): The object's CmdbType document, or None when it cannot be read
        owners (dict[int, CmdbUser]): The webhooks' owners by public_id
        states (tuple[dict[str, Any], ...]): The object states the event carries - each judged for the owner

    Returns:
        list[Any]: The webhooks to deliver to, in the order given
    """
    return [
        webhook for webhook in webhooks
        if owner_may_receive(owners.get(getattr(webhook, WebhookKey.OWNER_ID.value, None)), type_document, states)
    ]
