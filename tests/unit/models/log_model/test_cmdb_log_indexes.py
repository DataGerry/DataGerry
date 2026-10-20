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
Unit tests for the CmdbMetaLog index declarations

`framework.logs` only grows - one document per object create / edit / delete, each carrying a rendered
snapshot - and is read on every object's log tab, so the two query shapes the /logs routes issue must be
index-served. These tests pin the declarations (and their key ORDER, which is what decides whether the
index can serve the sort as well as the match) so they cannot be dropped unnoticed.
"""
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID_LOG_TIME_INDEX: str = 'object_id_log_time'
LOG_TYPE_ACTION_INDEX: str = 'log_type_action'

PUBLIC_ID_INDEX: str = 'public_id'


def _index_by_name(name: str) -> dict:
    """Returns the INDEX_KEYS declaration with the given name (fails the test when absent)."""
    matches = [entry for entry in CmdbMetaLog.INDEX_KEYS if entry.get('name') == name]

    assert len(matches) == 1, f"expected exactly one '{name}' index declaration"

    return matches[0]


def test_object_log_list_index_matches_then_sorts() -> None:
    """`GET /logs/object/<id>` matches object_id and sorts by log_time, so the order is (id, time)."""
    declaration = _index_by_name(OBJECT_ID_LOG_TIME_INDEX)

    assert declaration['keys'] == [
        ('object_id', CmdbDAO.DAO_ASCENDING),
        ('log_time', CmdbDAO.DAO_DESCENDING),
    ]
    assert declaration['unique'] is False


def test_log_type_action_index_serves_the_type_filtered_lists() -> None:
    """The delete-log list and the exists / notexists split both match log_type plus an action."""
    declaration = _index_by_name(LOG_TYPE_ACTION_INDEX)

    assert declaration['keys'] == [
        ('log_type', CmdbDAO.DAO_ASCENDING),
        ('action', CmdbDAO.DAO_ASCENDING),
    ]
    assert declaration['unique'] is False


def test_get_index_keys_materialises_every_declaration() -> None:
    """get_index_keys builds one IndexModel per INDEX_KEYS + SUPER_INDEX_KEYS entry."""
    models = CmdbMetaLog.get_index_keys()

    assert len(models) == len(CmdbMetaLog.INDEX_KEYS) + len(CmdbMetaLog.SUPER_INDEX_KEYS)

    names = {model.document['name'] for model in models}

    assert {OBJECT_ID_LOG_TIME_INDEX, LOG_TYPE_ACTION_INDEX, PUBLIC_ID_INDEX} <= names


def test_the_unique_public_id_index_is_retained() -> None:
    """The inherited unique public_id index must survive the added declarations."""
    public_id_models = [
        model for model in CmdbMetaLog.get_index_keys() if model.document['name'] == PUBLIC_ID_INDEX
    ]

    assert len(public_id_models) == 1
    assert public_id_models[0].document['unique'] is True
