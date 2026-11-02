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
Integration tests for updater_20261102 against a real MongoDB

A stored decision naming one ``model`` names it as a list under ``models`` afterwards; a decision without a model (an
empty data model) keeps null; a decision already in the new shape, and a second run, are left alone
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261102 import Update20261102
from cmdb.manager.system_manager.settings_manager import SettingsManager
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODEL_ID: str = 'it_infrastructure'
DECIDED: dict[str, Any] = {'decision': 'best_practice_model', 'decided_by': 1}
NEIGHBOUR_SECTION: str = 'updater-20261102-neighbour'


@pytest.fixture(name='settings')
def fixture_settings(database_manager: MongoDatabaseManager, database_name: str):
    """The settings with a neighbouring section; the decision and the neighbour removed again afterwards"""
    settings = SettingsManager(database_manager, database_name)
    settings.write(NEIGHBOUR_SECTION, {'model': MODEL_ID})

    yield settings

    settings.delete_section(START_ASSISTANT_SETTINGS_SECTION)
    settings.delete_section(NEIGHBOUR_SECTION)


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The real migration"""
    Update20261102(database_manager, database_name).start_update()


def _decision(settings: SettingsManager) -> dict[str, Any]:
    """The stored decision without its id"""
    return {key: value for key, value in settings.get_section(START_ASSISTANT_SETTINGS_SECTION).items()
            if key != '_id'}


@pytest.mark.parametrize('stored, expected', [
    ({**DECIDED, 'model': MODEL_ID}, {**DECIDED, 'models': [MODEL_ID]}),
    ({**DECIDED, 'model': None}, {**DECIDED, 'models': None}),
    ({**DECIDED, 'models': [MODEL_ID]}, {**DECIDED, 'models': [MODEL_ID]}),
], ids=['one-model', 'no-model', 'already-new'])
def test_the_decision_is_rewritten(settings: SettingsManager, database_manager: MongoDatabaseManager,
                                   database_name: str, stored: dict[str, Any], expected: dict[str, Any]) -> None:
    """`model` becomes `models` - the rest of the decision as it was"""
    settings.write(START_ASSISTANT_SETTINGS_SECTION, stored)

    _run(database_manager, database_name)

    assert _decision(settings) == expected


def test_a_second_run_changes_nothing(settings: SettingsManager, database_manager: MongoDatabaseManager,
                                      database_name: str) -> None:
    """Re-run safe: the first run removed what the second would match"""
    settings.write(START_ASSISTANT_SETTINGS_SECTION, {**DECIDED, 'model': MODEL_ID})

    _run(database_manager, database_name)
    _run(database_manager, database_name)

    assert _decision(settings) == {**DECIDED, 'models': [MODEL_ID]}


def test_no_decision_and_other_sections_are_left_alone(settings: SettingsManager,
                                                       database_manager: MongoDatabaseManager,
                                                       database_name: str) -> None:
    """Nothing to rewrite; a neighbour holding a `model` key of its own is not the decision"""
    settings.delete_section(START_ASSISTANT_SETTINGS_SECTION)

    _run(database_manager, database_name)

    assert settings.get_section(START_ASSISTANT_SETTINGS_SECTION) is None
    assert settings.get_section(NEIGHBOUR_SECTION)['model'] == MODEL_ID
