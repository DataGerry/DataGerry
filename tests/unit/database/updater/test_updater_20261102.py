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
Unit tests for cmdb.database.updater.versions.updater_20261102

The migration rewrites the start assistant's stored decision from ``model`` to ``models``. Its run against a real
database is its own integration test; this module owns the frozen literals, the write it sends, the version bump and
the failure tail
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261102 as module
from cmdb.database.updater.versions.updater_20261102 import Update20261102
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY, SettingsManager
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantKey,
)
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261102
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'settings gone'


def _updater(modified_count: int) -> tuple[Update20261102, MagicMock]:
    """The migration over a mocked database manager whose update changes `modified_count` documents"""
    dbm = MagicMock()
    dbm.update_many_raw.return_value = MagicMock(modified_count=modified_count)
    updater = Update20261102(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.SETTINGS_COLLECTION, SettingsManager.COLLECTION),
    (module.SECTION_ID_FIELD, SETTINGS_SECTION_ID_KEY),
    (module.START_ASSISTANT_SECTION, START_ASSISTANT_SETTINGS_SECTION),
    (module.NEW_MODELS_FIELD, StartAssistantKey.MODELS.value),
], ids=['collection', 'section-key', 'section', 'models-key'])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The literals were frozen from the code's own"""
    assert frozen == live


def test_only_a_section_still_holding_model_is_matched() -> None:
    """What makes a second run match nothing"""
    assert module.OLD_DECISION_CRITERIA == {'_id': 'start_assistant', 'model': {'$exists': True}}


def test_the_rewrite_lists_a_model_id_and_removes_the_old_key() -> None:
    """A string becomes a list of itself, anything else null; then `model` goes"""
    assert module.OLD_DECISION_REWRITE == [
        {'$set': {'models': {'$cond': [{'$eq': [{'$type': '$model'}, 'string']}, ['$model'], None]}}},
        {'$unset': 'model'},
    ]


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater(0)

    assert updater.creation_date() == CREATION_DATE
    assert 'start assistant' in updater.description()


@pytest.mark.parametrize('modified_count', [1, 0], ids=['old-shape', 'nothing-to-do'])
def test_rewrites_the_decision_and_bumps_the_version(modified_count: int) -> None:
    """One pipeline update on the settings; the version moves whether or not there was something to rewrite"""
    updater, dbm = _updater(modified_count)

    updater.start_update()

    dbm.update_many_raw.assert_called_once_with(module.SETTINGS_COLLECTION, DATABASE_NAME,
                                                module.OLD_DECISION_CRITERIA, module.OLD_DECISION_REWRITE)
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_update_is_the_updater_exception_carrying_it() -> None:
    """The failure tail wraps the exception itself, and the version does not move"""
    updater, dbm = _updater(0)
    failure = RuntimeError(DB_FAILURE)
    dbm.update_many_raw.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
