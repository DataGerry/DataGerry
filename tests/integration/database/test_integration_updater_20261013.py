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
Integration tests for cmdb.database.updater.versions.updater_20261013 against a real MongoDB

Seeds a type and a section template each with a field pattern the rule refuses and one it accepts, runs the
migration, and asserts the refused ones are reported by document and nothing is written - a second run reports the same
"""
import logging
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261013 import Update20261013
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model import CmdbType
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 98951
TEMPLATE_ID: int = 98952
TYPE_NAME: str = 'pattern-report-type'
TEMPLATE_NAME: str = 'pattern-report-template'
REFUSED: str = r'\p{L}+'
PORTABLE: str = '[a-z]+'


def _fields() -> list[dict[str, Any]]:
    """A refused and a portable pattern."""
    return [{'type': 'text', 'name': 'bad', 'label': 'Bad', 'regex': REFUSED},
            {'type': 'text', 'name': 'good', 'label': 'Good', 'regex': PORTABLE}]


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The type and the template - removed after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    templates = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)
    types.delete_many({'public_id': TYPE_ID})
    templates.delete_many({'public_id': TEMPLATE_ID})
    types.insert_one(make_type_doc(TYPE_ID, TYPE_NAME, fields=_fields()))
    templates.insert_one({'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'T', 'type': 'section',
                          'predefined': False, 'is_global': False, 'fields': _fields()})
    yield types, templates
    types.delete_many({'public_id': TYPE_ID})
    templates.delete_many({'public_id': TEMPLATE_ID})


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The update's own report lines"""
    return [record.getMessage() for record in caplog.records if 'Update20261013' in record.getMessage()]


def test_the_refused_patterns_are_reported_by_document(database_manager, database_name,
                                                       caplog: pytest.LogCaptureFixture) -> None:
    """One line each; the portable pattern is not mentioned"""
    caplog.set_level(logging.WARNING)

    Update20261013(database_manager, database_name).start_update()

    lines = [line for line in _messages(caplog) if TYPE_NAME in line or TEMPLATE_NAME in line]
    assert len(lines) == 2
    assert all("'bad'" in line and "'good'" not in line for line in lines)


def test_nothing_is_written_and_a_rerun_reports_the_same(seeded, database_manager, database_name,
                                                          caplog: pytest.LogCaptureFixture) -> None:
    """A report only"""
    types, templates = seeded
    before = (types.find_one({'public_id': TYPE_ID}, {'_id': 0}), templates.find_one({'public_id': TEMPLATE_ID},
                                                                                       {'_id': 0}))
    caplog.set_level(logging.WARNING)

    Update20261013(database_manager, database_name).start_update()
    first = _messages(caplog)
    caplog.clear()
    Update20261013(database_manager, database_name).start_update()

    assert _messages(caplog) == first
    assert (types.find_one({'public_id': TYPE_ID}, {'_id': 0}),
            templates.find_one({'public_id': TEMPLATE_ID}, {'_id': 0})) == before
