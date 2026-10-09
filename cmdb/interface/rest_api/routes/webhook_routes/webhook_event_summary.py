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
The shape of a row of the webhook delivery-log LIST

A CmdbWebhookEvent stores the complete payload a webhook was sent - including one or two full object snapshots and
the field-level diff. The list answers only the scalar keys (``WEBHOOK_EVENT_SUMMARY_KEYS``): the frontend's table
shows nothing else, and a page of snapshots costs whole documents per row. ``GET /webhook_events/<id>`` still
answers the whole event, so a caller that needs what was sent reads it there.

The trim happens in the database: ``build_event_list_criteria`` appends a ``$project`` stage AFTER the object-ACL
masking stage and the caller's ``?filter=`` stages, so a filter still sees every field it saw before and MongoDB
sends only the summary. Sorting and paging run on summary keys, after it
"""
from typing import Any

from cmdb.models.webhook_model.webhook_event_constants import WEBHOOK_EVENT_SUMMARY_KEYS
from cmdb.utils import Builder
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_event_list_criteria',
    'build_event_summary_stage',
    'summarize_webhook_event',
]

#: MongoDB's document id, which a row of the list never carries
MONGO_ID_KEY: str = '_id'


def build_event_summary_stage() -> dict[str, Any]:
    """
    Builds the ``$project`` stage that keeps exactly the summary keys of an event

    Returns:
        dict[str, Any]: A ``$project`` keeping every ``WEBHOOK_EVENT_SUMMARY_KEYS`` key and dropping ``_id``
    """
    return Builder.project_({MONGO_ID_KEY: 0, **{key.value: 1 for key in WEBHOOK_EVENT_SUMMARY_KEYS}})


def build_event_list_criteria(
        masking_stage: dict[str, Any] | None,
        caller_criteria: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
    """
    Orders the list's pipeline stages: the object-ACL mask first, the caller's filter, the summary last

    Args:
        masking_stage (dict[str, Any] | None): The object-ACL mask (``build_event_masking_stage``), None when
            nothing is denied
        caller_criteria (list[dict[str, Any]]): The caller's ``?filter=`` and search stages, as given

    Returns:
        list[dict[str, Any]]: The criteria the list iterates with
    """
    return [*([masking_stage] if masking_stage else []), *caller_criteria, build_event_summary_stage()]


def summarize_webhook_event(document: dict[str, Any]) -> dict[str, Any]:
    """
    Answers one list row: every summary key, None for one the stored event does not carry

    An event written before a key existed lacks it; the row still carries it, so every row has the same keys

    Args:
        document (dict[str, Any]): The projected event document

    Returns:
        dict[str, Any]: The summary keys, in ``WEBHOOK_EVENT_SUMMARY_KEYS`` order
    """
    return {key.value: document.get(key.value) for key in WEBHOOK_EVENT_SUMMARY_KEYS}
