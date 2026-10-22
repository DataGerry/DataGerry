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
Unit tests for start_assistant_helper: reading the decision (stored or not), holding a POST body to its one key and
the known decisions, and stamping who decided when

DB-free: the managers are stand-ins
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import BadRequest

from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_PAYLOAD_INVALID_MESSAGE,
    START_ASSISTANT_SETTINGS_SECTION,
    UNKNOWN_DECISION_MESSAGE,
    START_ASSISTANT_RIGHTS,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import (
    build_decision_document,
    build_offer,
    holds_start_assistant_rights,
    read_decision,
    read_decision_payload,
)
# -------------------------------------------------------------------------------------------------------------------- #

DECIDER_ID: int = 42
DECIDED_AT: datetime = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)
EMPTY: str = StartAssistantDecision.EMPTY_DATA_MODEL.value
BEST_PRACTICE: str = StartAssistantDecision.BEST_PRACTICE_MODEL.value
MODEL_ID: str = 'it_infrastructure'
HELPER_PATH: str = 'cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper'


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    read_decision                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def _settings(section: dict[str, Any] | None) -> MagicMock:
    """A settings manager answering ``section`` for the start assistant's section"""
    manager = MagicMock()
    manager.get_section.return_value = section

    return manager


def test_nothing_recorded_answers_every_key_as_none() -> None:
    """No section: the assistant has not run"""
    manager = _settings(None)

    assert read_decision(manager) == {key.value: None for key in StartAssistantKey}
    manager.get_section.assert_called_once_with(START_ASSISTANT_SETTINGS_SECTION)


def test_a_recorded_decision_answers_its_values_and_not_the_section_id() -> None:
    """Each key from its own place; the section's _id stays out"""
    stored: dict[str, Any] = {'_id': START_ASSISTANT_SETTINGS_SECTION, 'decision': BEST_PRACTICE,
                              'decided_by': DECIDER_ID, 'decided_at': DECIDED_AT, 'model': MODEL_ID}

    assert read_decision(_settings(stored)) == {'decision': BEST_PRACTICE, 'decided_by': DECIDER_ID,
                                                'decided_at': DECIDED_AT, 'model': MODEL_ID}


def test_a_decision_stored_before_the_model_key_reads_it_as_none() -> None:
    """An earlier empty_data_model carries no 'model'"""
    stored: dict[str, Any] = {'_id': START_ASSISTANT_SETTINGS_SECTION, 'decision': EMPTY, 'decided_by': DECIDER_ID,
                              'decided_at': DECIDED_AT}

    assert read_decision(_settings(stored))['model'] is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 read_decision_payload                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_a_known_decision_is_read() -> None:
    """The one key, a known value"""
    assert read_decision_payload({'decision': EMPTY}) is StartAssistantDecision.EMPTY_DATA_MODEL


@pytest.mark.parametrize('body', [
    None,                                       # no body, or not JSON
    [{'decision': EMPTY}],                      # not an object
    {},                                         # no key
    {'decision': EMPTY, 'decided_by': 1},       # a server-owned key beside it
    {'choice': EMPTY},                          # another key
])
def test_a_body_that_is_not_the_one_key_is_a_400(body: Any) -> None:
    """Exactly {'decision': ...}"""
    with pytest.raises(BadRequest) as refused:
        read_decision_payload(body)

    assert refused.value.description == DECISION_PAYLOAD_INVALID_MESSAGE


@pytest.mark.parametrize('value', ['import', 'EMPTY_DATA_MODEL', '', None, 1, ['empty_data_model'], BEST_PRACTICE])
def test_an_unknown_decision_is_a_400_naming_it_and_the_allowed_ones(value: Any) -> None:
    """Only the recordable decisions, spelled as stored - a best-practice model is recorded by applying it"""
    with pytest.raises(BadRequest) as refused:
        read_decision_payload({'decision': value})

    assert refused.value.description == UNKNOWN_DECISION_MESSAGE.format(decision=value, allowed=EMPTY)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                build_decision_document                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_document_names_the_decision_the_user_and_the_time() -> None:
    """decision, decided_by from the user, decided_at as given"""
    user = SimpleNamespace(get_public_id=lambda: DECIDER_ID)

    assert build_decision_document(StartAssistantDecision.EMPTY_DATA_MODEL, user, DECIDED_AT) == {
        'decision': EMPTY, 'decided_by': DECIDER_ID, 'decided_at': DECIDED_AT, 'model': None,
    }


def test_an_applied_model_is_named_in_the_document() -> None:
    """The model id beside the decision"""
    user = SimpleNamespace(get_public_id=lambda: DECIDER_ID)

    document = build_decision_document(StartAssistantDecision.BEST_PRACTICE_MODEL, user, DECIDED_AT, MODEL_ID)

    assert (document['decision'], document['model']) == (BEST_PRACTICE, MODEL_ID)


def test_without_a_time_the_document_is_stamped_now_in_utc() -> None:
    """decided_at defaults to now, timezone-aware"""
    before: datetime = datetime.now(timezone.utc)

    document = build_decision_document(StartAssistantDecision.EMPTY_DATA_MODEL,
                                       SimpleNamespace(get_public_id=lambda: DECIDER_ID))

    assert before <= document['decided_at'] <= datetime.now(timezone.utc)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        holds_start_assistant_rights / build_offer                                    #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('held, expected', [
    (set(START_ASSISTANT_RIGHTS), True),
    ({START_ASSISTANT_RIGHTS[0]}, False),
    ({START_ASSISTANT_RIGHTS[1]}, False),
    (set(), False),
])
def test_both_rights_are_needed_to_run_it(held: set[str], expected: bool) -> None:
    """type.add and category.add, each asked"""
    user = SimpleNamespace(get_public_id=lambda: DECIDER_ID)

    with patch(f'{HELPER_PATH}.user_has_right', side_effect=lambda right, _user: right in held):
        assert holds_start_assistant_rights(user) is expected


@pytest.mark.parametrize('holds_rights, blocked, decision, administrator, expected', [
    (True, False, None, False, (True, True, False, False)),     # never run, empty: open it - no import offered
    (True, False, None, True, (True, True, False, True)),       # ... and for the administrator account the import too
    (True, False, EMPTY, False, (False, True, False, False)),   # empty data model chosen, still empty: no longer opens
    (True, False, EMPTY, True, (False, True, False, True)),
    (True, True, None, True, (False, False, True, False)),      # something blocks an import: reset first, no import
    (True, True, EMPTY, False, (False, False, True, False)),
    (False, False, None, True, (False, False, False, False)),   # no rights: nothing, whoever asks
    (False, True, EMPTY, False, (False, False, False, False)),
])
def test_the_offer_follows_rights_blockers_decision_and_the_account(
        holds_rights: bool, blocked: bool, decision: str | None, administrator: bool,
        expected: tuple[bool, bool, bool, bool]) -> None:
    """(show, available, reset_required, can_import) for each combination"""
    show, available, reset_required, can_import = expected

    assert build_offer(holds_rights, blocked, decision, administrator) == {
        'show': show, 'available': available, 'reset_required': reset_required, 'can_import': can_import,
    }
