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
Unit tests for cmdb.interface.rest_api.routes.webhook_routes.webhook_event_access

Pure tests: no Mongo, the denied types are given or patched. Pinned:

  - the event's object type is the AFTER snapshot's, else the BEFORE one's (a delete), else none
  - a denied event loses exactly its three value keys - both snapshots and the diff - and keeps the rest of the row;
    an allowed one is returned as it is
  - with every Type restricted (the complement form), an event of a gone Type or of none is masked - while Types are
    only listed, it is shown
  - the pipeline stage applies the same rule, and is no stage at all when nothing is denied
  - the denial is the caller's for READ
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.framework.access_engine import DeniedTypes
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
from cmdb.models.webhook_model.webhook_event_constants import OBJECT_VALUE_KEYS, WebhookEventKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.webhook_routes import webhook_event_access
from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_access import (
    build_event_masking_stage,
    denied_object_types,
    event_object_type_id,
    mask_event_object_values,
)
# -------------------------------------------------------------------------------------------------------------------- #

DENIED_TYPE: int = 7
ALLOWED_TYPE: int = 8
OTHER_DENIED_TYPE: int = 9
GONE_TYPE: int = 99

# The listed form, and the complement form an every-Type role yields - only ALLOWED_TYPE admitted
DENIED: DeniedTypes = DeniedTypes(ids=frozenset({DENIED_TYPE}))
EVERY_TYPE_BUT_ALLOWED: DeniedTypes = DeniedTypes(admitted=frozenset({ALLOWED_TYPE}))


def _event(before_type: Any = None, after_type: Any = None) -> dict[str, Any]:
    """A stored event whose snapshots carry the given types (None leaves that snapshot out)"""
    return {
        'public_id': 1, 'webhook_id': 2, 'operation': 'UPDATE', 'status': True, 'response_code': 200,
        'object_before': {'type_id': before_type, 'fields': [{'name': 'f', 'value': 'old'}]} if before_type else None,
        'object_after': {'type_id': after_type, 'fields': [{'name': 'f', 'value': 'new'}]} if after_type else None,
        'changes': {'old': [{'name': 'f', 'value': 'old'}], 'new': [{'name': 'f', 'value': 'new'}]},
    }


class TestEventObjectTypeId:
    """Which object an event was sent for"""

    @pytest.mark.parametrize('event, expected', [
        (_event(after_type=ALLOWED_TYPE), ALLOWED_TYPE),
        (_event(before_type=DENIED_TYPE), DENIED_TYPE),
        (_event(before_type=DENIED_TYPE, after_type=ALLOWED_TYPE), ALLOWED_TYPE),
        (_event(), None),
        ({'object_after': 'not-a-document', 'object_before': {'type_id': DENIED_TYPE}}, DENIED_TYPE),
    ], ids=['create', 'delete', 'update-after-wins', 'no-snapshot', 'unusable-after'])
    def test_after_else_before(self, event: dict[str, Any], expected: Any) -> None:
        """The after snapshot names the object's current type"""
        assert event_object_type_id(event) == expected


class TestMaskEventObjectValues:
    """A denied event keeps its row and loses its values"""

    def test_a_denied_event_loses_exactly_the_three_value_keys(self) -> None:
        """Both snapshots and the diff; when, to whom and with which answer stay"""
        event = _event(before_type=DENIED_TYPE, after_type=DENIED_TYPE)

        masked = mask_event_object_values(event, DENIED)

        assert {key: masked[key] for key in ('object_before', 'object_after', 'changes')} == dict.fromkeys(
            ('object_before', 'object_after', 'changes'))
        assert {key: masked[key] for key in ('public_id', 'webhook_id', 'operation', 'status', 'response_code')} \
            == {key: event[key] for key in ('public_id', 'webhook_id', 'operation', 'status', 'response_code')}

    def test_the_stored_event_is_not_modified(self) -> None:
        """A copy is answered"""
        event = _event(after_type=DENIED_TYPE)

        mask_event_object_values(event, DENIED)

        assert event['object_after'] is not None

    @pytest.mark.parametrize('denied', [
        DeniedTypes(), DeniedTypes(ids=frozenset({OTHER_DENIED_TYPE})), EVERY_TYPE_BUT_ALLOWED,
    ], ids=['nothing-denied', 'another-type-denied', 'every-type-but-this'])
    def test_an_allowed_event_is_returned_as_it_is(self, denied: DeniedTypes) -> None:
        """The same object, not a copy"""
        event = _event(after_type=ALLOWED_TYPE)

        assert mask_event_object_values(event, denied) is event

    @pytest.mark.parametrize('event', [_event(), _event(after_type=GONE_TYPE)], ids=['no-type', 'gone-type'])
    def test_an_event_of_no_listed_type_is_shown_while_types_are_listed(self, event: dict[str, Any]) -> None:
        """Only the listed Types are denied - a gone Type or none is not among them"""
        assert mask_event_object_values(event, DENIED) is event

    @pytest.mark.parametrize('event', [
        _event(), _event(after_type=GONE_TYPE), _event(before_type=DENIED_TYPE),
    ], ids=['no-type', 'gone-type', 'not-admitted'])
    def test_every_type_restricted_masks_what_is_not_admitted(self, event: dict[str, Any]) -> None:
        """An every-Type role admits the granted Types only - a gone Type, or none, is masked like a denied one"""
        masked = mask_event_object_values(event, EVERY_TYPE_BUT_ALLOWED)

        assert [masked[key.value] for key in OBJECT_VALUE_KEYS] == [None] * len(OBJECT_VALUE_KEYS)


class TestBuildEventMaskingStage:
    """The same rule, as the first stage of the list pipeline"""

    def test_no_stage_when_nothing_is_denied(self) -> None:
        """Most installations activate no ACL, and pay nothing"""
        assert build_event_masking_stage(DeniedTypes()) is None

    def test_a_set_stage_blanks_each_value_key_when_the_type_is_denied(self) -> None:
        """One $cond per value key, all on the same type expression"""
        stage = build_event_masking_stage(DeniedTypes(ids=frozenset({OTHER_DENIED_TYPE, DENIED_TYPE})))

        assert list(stage) == ['$set']
        assert set(stage['$set']) == {key.value for key in OBJECT_VALUE_KEYS}

        for key in OBJECT_VALUE_KEYS:
            condition, masked, kept = stage['$set'][key.value]['$cond']
            assert condition == {'$in': [
                {'$ifNull': ['$object_after.type_id', '$object_before.type_id']}, [DENIED_TYPE, OTHER_DENIED_TYPE],
            ]}
            assert masked is None
            assert kept == f'${key.value}'

    def test_every_type_restricted_masks_what_is_not_admitted(self) -> None:
        """The complement: masked unless the type is admitted - a null or gone type is not"""
        stage = build_event_masking_stage(DeniedTypes(admitted=frozenset({OTHER_DENIED_TYPE, ALLOWED_TYPE})))

        for key in OBJECT_VALUE_KEYS:
            condition, masked, kept = stage['$set'][key.value]['$cond']
            assert condition == {'$not': [{'$in': [
                {'$ifNull': ['$object_after.type_id', '$object_before.type_id']}, [ALLOWED_TYPE, OTHER_DENIED_TYPE],
            ]}]}
            assert masked is None
            assert kept == f'${key.value}'


def test_the_denial_is_the_callers_for_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The access engine's denial of READ, as it holds it"""
    resolve = MagicMock(return_value=DENIED)
    monkeypatch.setattr(webhook_event_access, 'resolve_denied_types', resolve)
    request_user = MagicMock()

    assert denied_object_types(request_user) is DENIED
    resolve.assert_called_once_with(request_user, AccessControlPermission.READ)


def test_the_key_enum_spells_the_stored_keys() -> None:
    """Every key the model serialises, and nothing else"""
    event = CmdbWebhookEvent.from_data({key.value: None for key in WebhookEventKey} | {'public_id': 1})

    assert set(CmdbWebhookEvent.to_json(event)) == {key.value for key in WebhookEventKey}
