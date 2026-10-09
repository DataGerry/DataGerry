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
Integration tests for the date settings section against MongoDB

The write's path - the body validated against DateSettingsDAO.SCHEMA the way ``@validate`` does it, built by
``build_date_settings`` and written through SettingsManager - stores exactly the declared document. The read's
path over a section stored without the schema - by an older version or by hand - answers each missing or
unusable value as its default
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.database import MongoDatabaseManager
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.settings.date_settings import DateSettingsDAO
from cmdb.settings.date_settings_constants import DATE_SETTINGS_SECTION
from cmdb.interface.rest_api.routes.settings_routes.date_helper import build_date_settings
# -------------------------------------------------------------------------------------------------------------------- #

DATE_FORMAT: str = 'DD.MM.YYYY'
TIMEZONE: str = 'Europe/Berlin'


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(database_manager: MongoDatabaseManager, database_name: str):
    """A SettingsManager on the test database; the date section is removed before and after"""
    collection = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    collection.delete_many({'_id': DATE_SETTINGS_SECTION})

    yield SettingsManager(database_manager)

    collection.delete_many({'_id': DATE_SETTINGS_SECTION})


def _read(settings_manager: SettingsManager) -> dict[str, Any]:
    """What GET /date/ answers: the stored section (or the defaults), built per key"""
    return build_date_settings(
        settings_manager.get_all_values_from_section(DATE_SETTINGS_SECTION, DateSettingsDAO.__DEFAULT_SETTINGS__)
    ).to_json()


def test_a_validated_body_is_stored_as_the_declared_document(
        settings_manager: SettingsManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """An echoed _id and an extra key never reach the stored section"""
    validator = Validator(DateSettingsDAO.SCHEMA, purge_unknown=True)
    assert validator.validate({'_id': 'other', 'date_format': DATE_FORMAT, 'timezone': TIMEZONE, 'extra': 1})

    settings_manager.write(_id=DATE_SETTINGS_SECTION, data=build_date_settings(validator.document).to_json())

    stored = database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
        .find_one({'_id': DATE_SETTINGS_SECTION})
    assert stored == {'_id': DATE_SETTINGS_SECTION, 'date_format': DATE_FORMAT, 'timezone': TIMEZONE}
    assert _read(settings_manager) == stored


def test_nothing_stored_reads_as_the_defaults(settings_manager: SettingsManager) -> None:
    """No section at all"""
    assert _read(settings_manager) == {'_id': DATE_SETTINGS_SECTION, **DateSettingsDAO.__DEFAULT_SETTINGS__}


@pytest.mark.parametrize('stored', [
    {'date_format': DATE_FORMAT},
    {'date_format': DATE_FORMAT, 'timezone': None},
    {'date_format': DATE_FORMAT, 'timezone': 7},
], ids=['missing', 'null', 'number'])
def test_a_stored_section_without_a_usable_timezone_reads_its_default(
        settings_manager: SettingsManager, database_manager: MongoDatabaseManager, database_name: str,
        stored: dict[str, Any]) -> None:
    """The usable key is kept, the other one answered as its default"""
    database_manager.get_collection(SettingsManager.COLLECTION, database_name)\
        .insert_one({'_id': DATE_SETTINGS_SECTION, **stored})

    assert _read(settings_manager) == {
        '_id': DATE_SETTINGS_SECTION,
        'date_format': DATE_FORMAT,
        'timezone': DateSettingsDAO.__DEFAULT_SETTINGS__['timezone'],
    }
