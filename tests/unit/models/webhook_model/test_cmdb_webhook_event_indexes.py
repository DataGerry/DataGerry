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
Unit tests for the CmdbWebhookEvent index declarations

``framework.webhookEvents`` is append-only and unbounded: one document per object write per matching
active webhook, with no retention policy. It is also never read by public_id from the UI - the log
table sorts by ``webhook_id`` (its default) and searches ``webhook_id`` and ``event_time``. Until
2026-08-27 the model declared no INDEX_KEYS at all, so every page view of that table was a collection
scan plus an in-memory sort over a collection that only grows. These tests pin the two declarations so
they cannot be dropped unnoticed - and dropping one would not even show up in the database, because
index reconciliation is purely additive.
"""
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.webhook_model.cmdb_webhook_event import CmdbWebhookEvent
# -------------------------------------------------------------------------------------------------------------------- #

WEBHOOK_ID_INDEX: str = 'webhook_id'
EVENT_TIME_INDEX: str = 'event_time'

PUBLIC_ID_INDEX: str = 'public_id'


def _index_by_name(name: str) -> dict:
    """Returns the INDEX_KEYS declaration with the given name (fails the test when absent)."""
    matches = [entry for entry in CmdbWebhookEvent.INDEX_KEYS if entry.get('name') == name]

    assert len(matches) == 1, f"expected exactly one '{name}' index declaration"

    return matches[0]


def test_webhook_id_index_serves_the_log_tables_default_sort() -> None:
    """The frontend's log table sorts by webhook_id by default, so that key is indexed ascending."""
    declaration = _index_by_name(WEBHOOK_ID_INDEX)

    assert declaration['keys'] == [('webhook_id', CmdbDAO.DAO_ASCENDING)]


def test_event_time_index_is_descending() -> None:
    """
    event_time is indexed newest-first

    A delivery log is read from the recent end, and the same index still serves an ascending sort, so
    descending is the direction that matches how the collection is actually queried.
    """
    declaration = _index_by_name(EVENT_TIME_INDEX)

    assert declaration['keys'] == [('event_time', CmdbDAO.DAO_DESCENDING)]


def test_neither_index_is_unique() -> None:
    """Many deliveries share a webhook_id, and two can share a timestamp - uniqueness would reject them."""
    for name in (WEBHOOK_ID_INDEX, EVENT_TIME_INDEX):
        assert _index_by_name(name).get('unique', False) is False


def test_get_index_keys_materialises_every_declaration() -> None:
    """get_index_keys builds one IndexModel per INDEX_KEYS + SUPER_INDEX_KEYS entry."""
    models = CmdbWebhookEvent.get_index_keys()

    assert len(models) == len(CmdbWebhookEvent.INDEX_KEYS) + len(CmdbWebhookEvent.SUPER_INDEX_KEYS)

    names = {model.document['name'] for model in models}

    assert {WEBHOOK_ID_INDEX, EVENT_TIME_INDEX, PUBLIC_ID_INDEX} <= names


def test_the_unique_public_id_index_is_retained() -> None:
    """The inherited unique public_id index must survive the added declarations."""
    public_id_models = [
        model for model in CmdbWebhookEvent.get_index_keys() if model.document['name'] == PUBLIC_ID_INDEX
    ]

    assert len(public_id_models) == 1
    assert public_id_models[0].document['unique'] is True
