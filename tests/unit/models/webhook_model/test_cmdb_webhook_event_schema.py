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
Unit tests for CmdbWebhookEvent.SCHEMA - the contract of a stored webhook delivery

Nothing validates an event at write time (the delivery record is written best-effort), so the schema is
kept honest here: every document shape `webhook_helper` produces must validate against it, and the shapes
it never produces must not. The documents are built with the real `build_webhook_payload` plus the three
fields the delivery adds, so a change to the writer that the schema does not follow fails this module.
"""
from typing import Any

import pytest
from cerberus import Validator  # type: ignore

from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_type_enum import WebhookEventType
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WEBHOOK_NO_RESPONSE_CODE
from cmdb.interface.rest_api.routes.webhook_routes.webhook_helper import build_webhook_payload
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_ID: int = 7
DELIVERED_CODE: int = 204
OBJECT_BEFORE: dict[str, Any] = {'public_id': 1, 'fields': [{'name': 'dg-name', 'value': 'old'}]}
OBJECT_AFTER: dict[str, Any] = {'public_id': 1, 'fields': [{'name': 'dg-name', 'value': 'new'}]}
FIELD_DIFF: dict[str, Any] = {
    'old': [{'name': 'dg-name', 'value': 'old'}],
    'new': [{'name': 'dg-name', 'value': 'new'}],
}


def _delivered(payload: dict[str, Any], response_code: int = DELIVERED_CODE, status: bool = True) -> dict[str, Any]:
    """The stored document: the payload plus the three fields `deliver_webhook_event` adds"""
    return {**payload, 'webhook_id': WEBHOOK_ID, 'response_code': response_code, 'status': status}


def _errors(document: dict[str, Any]) -> dict[str, Any]:
    """The schema's complaints about a document; empty when it validates"""
    validator = Validator(CmdbWebhookEvent.SCHEMA)
    validator.validate(document)

    return validator.errors


# The four document shapes the writer produces, one per call site in objects_side_effects_helper
WRITTEN_SHAPES: dict[str, dict[str, Any]] = {
    'create': build_webhook_payload(WebhookEventType.CREATE, None, OBJECT_AFTER, None),
    'update': build_webhook_payload(WebhookEventType.UPDATE, OBJECT_BEFORE, OBJECT_AFTER, FIELD_DIFF),
    'activation-toggle': build_webhook_payload(WebhookEventType.UPDATE, OBJECT_BEFORE, OBJECT_AFTER, {'state': True}),
    'delete': build_webhook_payload(WebhookEventType.DELETE, OBJECT_BEFORE, None, None),
}


class TestWhatTheWriterProduces:
    """Every stored event validates"""

    @pytest.mark.parametrize('shape', list(WRITTEN_SHAPES), ids=list(WRITTEN_SHAPES))
    def test_a_delivered_event_validates(self, shape: str) -> None:
        """CREATE / UPDATE / activation toggle / DELETE, each as the writer builds it"""
        assert _errors(_delivered(WRITTEN_SHAPES[shape])) == {}

    @pytest.mark.parametrize('shape', list(WRITTEN_SHAPES), ids=list(WRITTEN_SHAPES))
    def test_a_failed_delivery_validates(self, shape: str) -> None:
        """No response at all is recorded as code 0 and status False - still a valid record"""
        assert _errors(_delivered(WRITTEN_SHAPES[shape], WEBHOOK_NO_RESPONSE_CODE, False)) == {}

    def test_the_event_time_is_a_datetime(self) -> None:
        """What the writer stores, and what the schema now declares"""
        document: dict[str, Any] = _delivered(WRITTEN_SHAPES['create'])

        assert _errors({**document, 'event_time': {'$date': 0}}) != {}
        assert _errors(document) == {}


class TestWhatItRefuses:
    """The shapes the writer never produces"""

    def test_an_unknown_operation_is_refused(self) -> None:
        """operation is a WebhookEventType value"""
        assert 'operation' in _errors({**_delivered(WRITTEN_SHAPES['create']), 'operation': 'RENAME'})

    @pytest.mark.parametrize('key', ['event_time', 'operation', 'webhook_id', 'response_code', 'status'])
    def test_a_field_every_event_carries_is_required(self, key: str) -> None:
        """The writer always writes these; a document without one is not an event it made"""
        document: dict[str, Any] = _delivered(WRITTEN_SHAPES['update'])
        del document[key]

        assert key in _errors(document)

    @pytest.mark.parametrize('key', ['object_before', 'object_after', 'changes'])
    def test_a_payload_field_that_is_not_a_dict_is_refused(self, key: str) -> None:
        """None is allowed (the operation did not set it); any other non-dict is not"""
        assert key in _errors({**_delivered(WRITTEN_SHAPES['update']), key: ['not', 'a', 'dict']})

    def test_a_missing_response_code_is_not_filled_in_as_a_success(self) -> None:
        """No default: a record without its code stays without one instead of being normalised to 200"""
        document: dict[str, Any] = _delivered(WRITTEN_SHAPES['create'])
        del document['response_code']

        validator = Validator(CmdbWebhookEvent.SCHEMA)
        validator.validate(document)

        assert 'response_code' not in validator.document
