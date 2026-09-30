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
Validation schema for CmdbWebhookEvent

A CmdbWebhookEvent records a single webhook delivery: operation, payload and response
(collection ``framework.webhookEvents``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbWebhookEvent.SCHEMA.

It describes the document ``webhook_helper`` writes, and nothing validates against it at write time - an
event is recorded best-effort after the delivery, and refusing it would lose the delivery record. It is
kept honest by a test instead: every document shape the writer produces must validate. What that
document looks like:

* ``build_webhook_payload`` writes ``event_time`` (a ``datetime``), ``operation`` and the three payload
  fields; the delivery adds ``webhook_id``, ``response_code`` (``WEBHOOK_NO_RESPONSE_CODE``, 0, when no
  response came back) and ``status``
* which payload fields are set depends on the operation - CREATE: ``object_after`` only; DELETE:
  ``object_before`` only; UPDATE: both, plus ``changes`` (the field diff, or ``{'state': bool}`` for an
  activation toggle). The ones not set are stored as ``None``
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_webhook_event_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbWebhookEvent document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbWebhookEvent.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType

    return {
        'public_id': {  # public_id of the CmdbWebhookEvent
            'type': 'integer',
        },
        'event_time': {  # When the triggering object write happened (UTC); stored as a BSON date
            'type': 'datetime',
            'nullable': True,
            'required': True,
        },
        'operation': {  # Triggering operation: a WebhookEventType value
            'type': 'string',
            'allowed': [event_type.value for event_type in WebhookEventType],
            'required': True,
        },
        'webhook_id': {  # public_id of the CmdbWebhook that produced this event
            'type': 'integer',
            'required': True,
        },
        'object_before': {  # The object before the write; None on CREATE
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        'object_after': {  # The object after the write; None on DELETE
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        'changes': {  # UPDATE only: the field diff, or {'state': bool} for an activation toggle; else None
            'type': 'dict',
            'nullable': True,
            'required': False,
        },
        # No default on purpose: Cerberus applies a default BEFORE the required check, so a default would
        # both disable `required` and fill a missing code in as a success. The writer always sets it
        'response_code': {  # HTTP status the target answered; 0 (WEBHOOK_NO_RESPONSE_CODE) when none came back
            'type': 'integer',
            'required': True,
        },
        'status': {  # Whether the target answered 2xx - i.e. whether the delivery succeeded
            'type': 'boolean',
            'required': True,
        },
    }
