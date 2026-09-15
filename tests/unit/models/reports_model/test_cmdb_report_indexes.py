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
Unit tests for the CmdbReport index declarations

`framework.reports` is only ever *counted* by two foreign keys, and both counts sit in a user-facing
guard: deleting a CmdbReportCategory is refused while a report references it (`report_category_id`),
and the report count of a CmdbType is asked for by the type flow (`type_id`). Without these
declarations both are collection scans. These tests pin them so they cannot be dropped unnoticed.
"""
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.reports_model.cmdb_report import CmdbReport
# -------------------------------------------------------------------------------------------------------------------- #

REPORT_CATEGORY_ID_INDEX: str = 'report_category_id'
TYPE_ID_INDEX: str = 'type_id'

PUBLIC_ID_INDEX: str = 'public_id'


def _index_by_name(name: str) -> dict:
    """Returns the INDEX_KEYS declaration with the given name (fails the test when absent)."""
    matches = [entry for entry in CmdbReport.INDEX_KEYS if entry.get('name') == name]

    assert len(matches) == 1, f"expected exactly one '{name}' index declaration"

    return matches[0]


def test_report_category_id_index_serves_the_category_delete_guard() -> None:
    """The category delete guard counts reports by report_category_id, so that key is indexed."""
    declaration = _index_by_name(REPORT_CATEGORY_ID_INDEX)

    assert declaration['keys'] == [('report_category_id', CmdbDAO.DAO_ASCENDING)]
    assert declaration['unique'] is False


def test_type_id_index_serves_the_report_count_of_a_type() -> None:
    """`GET /reports/<id>/count_reports_of_type` counts reports by type_id, so that key is indexed."""
    declaration = _index_by_name(TYPE_ID_INDEX)

    assert declaration['keys'] == [('type_id', CmdbDAO.DAO_ASCENDING)]
    assert declaration['unique'] is False


def test_get_index_keys_materialises_every_declaration() -> None:
    """get_index_keys builds one IndexModel per INDEX_KEYS + SUPER_INDEX_KEYS entry."""
    models = CmdbReport.get_index_keys()

    assert len(models) == len(CmdbReport.INDEX_KEYS) + len(CmdbReport.SUPER_INDEX_KEYS)

    names = {model.document['name'] for model in models}

    assert {REPORT_CATEGORY_ID_INDEX, TYPE_ID_INDEX, PUBLIC_ID_INDEX} <= names


def test_the_unique_public_id_index_is_retained() -> None:
    """The inherited unique public_id index must survive the added declarations."""
    public_id_models = [
        model for model in CmdbReport.get_index_keys() if model.document['name'] == PUBLIC_ID_INDEX
    ]

    assert len(public_id_models) == 1
    assert public_id_models[0].document['unique'] is True
