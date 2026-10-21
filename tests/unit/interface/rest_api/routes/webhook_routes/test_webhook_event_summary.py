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
Unit tests for webhook_event_summary - what a row of the delivery-log list is

The projection keeps exactly the summary keys, the pipeline runs the object-ACL mask first, the caller's stages next
and the projection last, and a row always carries every summary key
"""
from typing import Any

from cmdb.models.webhook_model.webhook_event_constants import WEBHOOK_EVENT_SUMMARY_KEYS, WebhookEventKey
from cmdb.interface.rest_api.routes.webhook_routes.webhook_event_summary import (
    MONGO_ID_KEY,
    build_event_list_criteria,
    build_event_summary_stage,
    summarize_webhook_event,
)
# -------------------------------------------------------------------------------------------------------------------- #

MASKING_STAGE: dict[str, Any] = {'$set': {'object_after': None}}
CALLER_STAGES: list[dict[str, Any]] = [{'$addFields': {'webhook_id_str': {'$toString': '$webhook_id'}}},
                                       {'$match': {'webhook_id_str': {'$regex': '7'}}}]
SUMMARY_VALUES: dict[str, Any] = {
    WebhookEventKey.PUBLIC_ID.value: 1, WebhookEventKey.WEBHOOK_ID.value: 7, WebhookEventKey.OPERATION.value: 'CREATE',
    WebhookEventKey.EVENT_TIME.value: 'then', WebhookEventKey.STATUS.value: True,
    WebhookEventKey.RESPONSE_CODE.value: 200,
}


def test_the_summary_keys_are_the_scalars_and_none_of_the_object_values() -> None:
    """Exactly the six scalar keys - no snapshot, no diff"""
    assert {key.value for key in WEBHOOK_EVENT_SUMMARY_KEYS} == set(SUMMARY_VALUES)
    assert not {WebhookEventKey.OBJECT_BEFORE, WebhookEventKey.OBJECT_AFTER, WebhookEventKey.CHANGES} & set(
        WEBHOOK_EVENT_SUMMARY_KEYS,
    )


def test_the_projection_keeps_the_summary_and_drops_the_id() -> None:
    """One $project: every summary key included, MongoDB's _id excluded, nothing else named"""
    stage = build_event_summary_stage()

    assert stage == {'$project': {MONGO_ID_KEY: 0, **{key: 1 for key in SUMMARY_VALUES}}}


def test_the_mask_runs_first_the_caller_next_the_projection_last() -> None:
    """The caller's filter sees every field, after the mask and before the trim"""
    criteria = build_event_list_criteria(MASKING_STAGE, list(CALLER_STAGES))

    assert criteria == [MASKING_STAGE, *CALLER_STAGES, build_event_summary_stage()]


def test_without_a_mask_the_caller_runs_first() -> None:
    """Nothing denied, no mask stage - the projection still closes the pipeline"""
    assert build_event_list_criteria(None, list(CALLER_STAGES)) == [*CALLER_STAGES, build_event_summary_stage()]
    assert build_event_list_criteria(None, []) == [build_event_summary_stage()]


def test_a_row_carries_every_summary_key_and_nothing_else() -> None:
    """A key the stored event lacks is None; a key outside the summary is dropped"""
    document = {**SUMMARY_VALUES, WebhookEventKey.OBJECT_AFTER.value: {'fields': []}}
    del document[WebhookEventKey.OPERATION.value]

    row = summarize_webhook_event(document)

    assert list(row) == [key.value for key in WEBHOOK_EVENT_SUMMARY_KEYS]
    assert row[WebhookEventKey.OPERATION.value] is None
    assert row[WebhookEventKey.RESPONSE_CODE.value] == SUMMARY_VALUES[WebhookEventKey.RESPONSE_CODE.value]
