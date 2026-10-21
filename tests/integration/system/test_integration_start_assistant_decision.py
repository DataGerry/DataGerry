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
Integration tests: the start assistant's decision on a real settings collection

What the routes rely on: ``SettingsManager.write`` stores the section, a second write replaces its values in the same
one document (a later decision wins), ``read_decision`` answers the stored values, and ``delete_section`` - the
configuration reset's step - leaves the answer for "not run yet"
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import (
    build_decision_document,
    read_decision,
)
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_DECIDER: int = 88761
SECOND_DECIDER: int = 88762
FIRST_TIME: datetime = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
SECOND_TIME: datetime = datetime(2026, 2, 2, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(name='settings_manager')
def fixture_settings_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The tenant's settings manager, the decision section removed before and after"""
    manager = SettingsManager(database_manager, database_name)
    manager.delete_section(START_ASSISTANT_SETTINGS_SECTION)
    yield manager
    manager.delete_section(START_ASSISTANT_SETTINGS_SECTION)


def _decide(manager: SettingsManager, decider: int, at: datetime) -> None:
    """Records the empty-data-model decision as ``decider`` at ``at``"""
    user = SimpleNamespace(get_public_id=lambda: decider)
    manager.write(START_ASSISTANT_SETTINGS_SECTION,
                  build_decision_document(StartAssistantDecision.EMPTY_DATA_MODEL, user, at))


def _naive(value: datetime) -> datetime:
    """MongoDB answers dates without a timezone"""
    return value.replace(tzinfo=None)


def test_a_recorded_decision_reads_back(settings_manager: SettingsManager) -> None:
    """The three values, as stored"""
    _decide(settings_manager, FIRST_DECIDER, FIRST_TIME)

    answer = read_decision(settings_manager)

    assert answer[StartAssistantKey.DECISION.value] == StartAssistantDecision.EMPTY_DATA_MODEL.value
    assert answer[StartAssistantKey.DECIDED_BY.value] == FIRST_DECIDER
    assert _naive(answer[StartAssistantKey.DECIDED_AT.value]) == _naive(FIRST_TIME)


def test_a_second_decision_replaces_the_first_in_one_section(
        settings_manager: SettingsManager, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """The later caller and time win; still one document"""
    _decide(settings_manager, FIRST_DECIDER, FIRST_TIME)
    _decide(settings_manager, SECOND_DECIDER, SECOND_TIME)

    answer = read_decision(settings_manager)

    assert answer[StartAssistantKey.DECIDED_BY.value] == SECOND_DECIDER
    assert _naive(answer[StartAssistantKey.DECIDED_AT.value]) == _naive(SECOND_TIME)
    assert database_manager.get_collection(SettingsManager.COLLECTION, database_name).count_documents(
        {'_id': START_ASSISTANT_SETTINGS_SECTION}) == 1


def test_deleting_the_section_answers_not_run(settings_manager: SettingsManager) -> None:
    """The reset's step: afterwards every key is None"""
    _decide(settings_manager, FIRST_DECIDER, FIRST_TIME)

    assert settings_manager.delete_section(START_ASSISTANT_SETTINGS_SECTION) is True
    assert read_decision(settings_manager) == {key.value: None for key in StartAssistantKey}
