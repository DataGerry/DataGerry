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
Unit tests for cmdb.interface.rest_api.routes.isms_routes.assignment_entries_helper

The ControlMeasureAssignments a RiskAssessment write embeds are held to the assignment write schema:

  - the container: a list on create, a ``{created, updated, deleted}`` object of lists on update; None is nothing
  - each entry: an object passing the schema (required keys, types, enum values), unknown keys and ``public_id``
    purged, ``risk_assessment_id`` not taken from the body
  - an updated entry keeps its integer ``public_id``; a deleted entry is an integer id
  - one ControlMeasure per assessment, judged on what the assessment holds once the diff is applied

Pure tests: an app context for ``abort``, no Mongo
"""
from http import HTTPStatus
from typing import Any

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.assignment_entries_helper import (
    AssignmentDiff,
    abort_on_duplicate_control_measures,
    assignments_after_update,
    validated_create_payload,
    validated_update_payload,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ASSIGNMENTS_NOT_A_LIST_MSG,
    AssignmentDiffKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

MEASURE_ID: int = 21
SECOND_MEASURE_ID: int = 22
THIRD_MEASURE_ID: int = 23
STORED_ID: int = 31
SECOND_STORED_ID: int = 32
CLIENT_ID: int = 99
PERSON_ID: int = 41
FOREIGN_ASSESSMENT_ID: int = 51
UNKNOWN_KEY: str = 'not_a_field'
UNKNOWN_PRIORITY: int = max(priority.value for priority in Priority) + 1

CREATED: str = AssignmentDiffKey.CREATED.value
UPDATED: str = AssignmentDiffKey.UPDATED.value
DELETED: str = AssignmentDiffKey.DELETED.value


def _entry(control_measure_id: int = MEASURE_ID, **overrides: Any) -> dict[str, Any]:
    """A complete entry as the frontend's assignment form sends it"""
    entry: dict[str, Any] = {
        'control_measure_id': control_measure_id,
        'planned_implementation_date': None,
        'implementation_status': 1,
        'finished_implementation_date': None,
        'priority': Priority.MEDIUM.value,
        'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON.value,
        'responsible_for_implementation_id': PERSON_ID,
    }
    entry.update(overrides)

    return entry


@pytest.fixture(name='flask_context', autouse=True)
def fixture_flask_context():
    """abort() needs an application context"""
    with Flask(__name__).app_context():
        yield


def _refusal(function: Any, value: Any) -> str:
    """The 400 a helper answers for the value, as its description"""
    with pytest.raises(HTTPException) as caught:
        function(value)

    assert caught.value.code == HTTPStatus.BAD_REQUEST

    return caught.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       CREATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidatedCreatePayload:
    """POST /isms/risk_assessments/ - a list of entries"""

    @pytest.mark.parametrize('value', [None, []])
    def test_nothing_is_no_assignments(self, value: Any) -> None:
        """The key left out, sent as null or as an empty list"""
        assert validated_create_payload(value) == []

    @pytest.mark.parametrize('value', [{'created': []}, 'x', 5, True])
    def test_anything_but_a_list_is_refused(self, value: Any) -> None:
        """The update's diff object included - it is not what a create takes"""
        assert _refusal(validated_create_payload, value) == ASSIGNMENTS_NOT_A_LIST_MSG

    def test_a_valid_entry_is_kept_as_sent(self) -> None:
        """Every schema key survives with its value"""
        assert validated_create_payload([_entry()]) == [_entry()]

    def test_the_server_owned_keys_and_unknown_keys_are_dropped(self) -> None:
        """public_id is the server's to assign, risk_assessment_id the route's to stamp"""
        sent: dict[str, Any] = _entry(public_id=CLIENT_ID, risk_assessment_id=FOREIGN_ASSESSMENT_ID,
                                      **{UNKNOWN_KEY: 'x'})

        assert validated_create_payload([sent]) == [_entry()]

    @pytest.mark.parametrize('entry', [5, 'x', None, [_entry()]])
    def test_an_entry_that_is_no_object_is_refused_by_position(self, entry: Any) -> None:
        """Named by its 1-based position in the list"""
        description: str = _refusal(validated_create_payload, [_entry(), entry])

        assert f'{CREATED} #2' in description

    @pytest.mark.parametrize('broken, key', [
        ({'control_measure_id': None}, 'control_measure_id'),
        ({'control_measure_id': '21'}, 'control_measure_id'),
        ({'priority': UNKNOWN_PRIORITY}, 'priority'),
        ({'responsible_for_implementation_id_ref_type': 'NOBODY'}, 'responsible_for_implementation_id_ref_type'),
        ({'implementation_status': 'done'}, 'implementation_status'),
    ], ids=['measure-null', 'measure-string', 'priority-unknown', 'ref-type-unknown', 'status-string'])
    def test_an_entry_failing_the_schema_names_the_key(self, broken: dict[str, Any], key: str) -> None:
        """The position and the schema's own error for the key"""
        description: str = _refusal(validated_create_payload, [_entry(**broken)])

        assert f'{CREATED} #1' in description
        assert key in description

    def test_a_missing_required_key_is_refused(self) -> None:
        """The schema's required keys are required here too"""
        entry: dict[str, Any] = _entry()
        entry.pop('implementation_status')

        assert 'implementation_status' in _refusal(validated_create_payload, [entry])


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       UPDATE                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestValidatedUpdatePayload:
    """PUT /isms/risk_assessments/<id> - the {created, updated, deleted} diff"""

    @pytest.mark.parametrize('value', [None, {}, {CREATED: None, UPDATED: None, DELETED: None}])
    def test_nothing_is_no_change(self, value: Any) -> None:
        """The key left out, null, an empty object or null lists"""
        assert validated_update_payload(value) == AssignmentDiff([], [], [])

    @pytest.mark.parametrize('value', [
        [_entry()], 'x', {CREATED: _entry()}, {DELETED: STORED_ID}, {'removed': [STORED_ID]},
    ], ids=['a-list', 'a-string', 'created-no-list', 'deleted-no-list', 'unknown-key'])
    def test_anything_but_the_diff_object_is_refused(self, value: Any) -> None:
        """The refusal names the three keys"""
        description: str = _refusal(validated_update_payload, value)

        assert all(key in description for key in (CREATED, UPDATED, DELETED))

    def test_a_full_diff_is_answered_cleaned(self) -> None:
        """Created lose their id, updated keep theirs, deleted stay ids"""
        diff: AssignmentDiff = validated_update_payload({
            CREATED: [_entry(SECOND_MEASURE_ID, public_id=CLIENT_ID)],
            UPDATED: [_entry(public_id=STORED_ID, risk_assessment_id=FOREIGN_ASSESSMENT_ID, **{UNKNOWN_KEY: 1})],
            DELETED: [SECOND_STORED_ID],
        })

        assert diff == AssignmentDiff(
            [_entry(SECOND_MEASURE_ID)], [{**_entry(), 'public_id': STORED_ID}], [SECOND_STORED_ID],
        )

    @pytest.mark.parametrize('public_id', [None, '31', 31.0, True])
    def test_an_updated_entry_needs_an_integer_id(self, public_id: Any) -> None:
        """Without it the entry names no stored assignment"""
        entry: dict[str, Any] = _entry() if public_id is None else _entry(public_id=public_id)

        description: str = _refusal(validated_update_payload, {UPDATED: [entry]})

        assert f'{UPDATED} #1' in description
        assert repr(public_id) in description

    def test_an_updated_entry_is_held_to_the_schema(self) -> None:
        """The same rule as a created one"""
        description: str = _refusal(
            validated_update_payload, {UPDATED: [_entry(public_id=STORED_ID, priority=UNKNOWN_PRIORITY)]},
        )

        assert f'{UPDATED} #1' in description
        assert 'priority' in description

    def test_a_created_entry_is_held_to_the_schema(self) -> None:
        """Named in the created list"""
        assert f'{CREATED} #1' in _refusal(validated_update_payload, {CREATED: [_entry(control_measure_id=None)]})

    @pytest.mark.parametrize('deleted', ['31', None, {'public_id': STORED_ID}, False])
    def test_a_deleted_entry_must_be_an_integer_id(self, deleted: Any) -> None:
        """Named by its position"""
        description: str = _refusal(validated_update_payload, {DELETED: [STORED_ID, deleted]})

        assert f'{DELETED} #2' in description


# -------------------------------------------------------------------------------------------------------------------- #
#                                                     DUPLICATES                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestAssignmentsAfterUpdate:
    """What an assessment holds once the diff is applied"""

    def test_kept_updated_deleted_and_created(self) -> None:
        """A stored one deleted, a stored one replaced by its update, a created one added"""
        stored: dict[int, dict[str, Any]] = {
            STORED_ID: {'public_id': STORED_ID, 'control_measure_id': MEASURE_ID},
            SECOND_STORED_ID: {'public_id': SECOND_STORED_ID, 'control_measure_id': SECOND_MEASURE_ID},
        }
        updated: dict[str, Any] = {'public_id': STORED_ID, 'control_measure_id': THIRD_MEASURE_ID}
        created: dict[str, Any] = {'control_measure_id': SECOND_MEASURE_ID}

        after = assignments_after_update(stored, AssignmentDiff([created], [updated], [SECOND_STORED_ID]))

        assert after == [updated, created]

    def test_no_diff_is_the_stored_set(self) -> None:
        """Nothing changes"""
        stored: dict[int, dict[str, Any]] = {STORED_ID: {'control_measure_id': MEASURE_ID}}

        assert assignments_after_update(stored, AssignmentDiff([], [], [])) == [stored[STORED_ID]]


class TestAbortOnDuplicateControlMeasures:
    """One ControlMeasure per assessment"""

    def test_distinct_measures_pass(self) -> None:
        """Nothing raised"""
        abort_on_duplicate_control_measures([_entry(MEASURE_ID), _entry(SECOND_MEASURE_ID)])

    def test_nothing_passes(self) -> None:
        """An assessment without assignments"""
        abort_on_duplicate_control_measures([])

    def test_every_repeated_measure_is_named_sorted(self) -> None:
        """Both repeated ids, once each, the single one not"""
        description: str = _refusal(abort_on_duplicate_control_measures, [
            _entry(SECOND_MEASURE_ID), _entry(MEASURE_ID), _entry(SECOND_MEASURE_ID),
            _entry(THIRD_MEASURE_ID), _entry(MEASURE_ID),
        ])

        assert f'[{MEASURE_ID}, {SECOND_MEASURE_ID}]' in description
        assert str(THIRD_MEASURE_ID) not in description
