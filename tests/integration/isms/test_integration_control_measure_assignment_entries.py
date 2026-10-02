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
Integration tests for the embedded ControlMeasureAssignment entries, against the real collection

  - an entry ``validated_create_payload`` answers is a complete assignment: stored through the real manager it
    gets a server id and reads back as the model, with every schema key the entry carried
  - ``ControlMeasureAssignmentManager.is_control_measure_assigned`` - the standalone routes' duplicate check -
    answers per assessment, and leaves out the assignment being updated; a failed count is the manager's get error
"""
from typing import Any

import pytest
from flask import Flask

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_assignment_manager import ControlMeasureAssignmentManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.priority_enum import Priority
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.interface.rest_api.routes.isms_routes.assignment_entries_helper import validated_create_payload
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.control_measure_assignment_manager import ControlMeasureAssignmentManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

RA_ID: int = 97901
OTHER_RA_ID: int = 97902
MEASURE_ID: int = 97911
OTHER_MEASURE_ID: int = 97912
STORED_ID: int = 97921
CLIENT_ID: int = 97929
PERSON_ID: int = 97931

RISK_ASSESSMENT_KEY: str = ControlMeasureAssignmentKey.RISK_ASSESSMENT_ID.value
CONTROL_MEASURE_KEY: str = ControlMeasureAssignmentKey.CONTROL_MEASURE_ID.value
PUBLIC_ID_KEY: str = ControlMeasureAssignmentKey.PUBLIC_ID.value


def _entry(measure_id: int = MEASURE_ID) -> dict[str, Any]:
    """An entry as the frontend's assignment form sends it"""
    return {
        CONTROL_MEASURE_KEY: measure_id,
        'planned_implementation_date': None,
        'implementation_status': 2,
        'finished_implementation_date': None,
        'priority': Priority.VERY_HIGH.value,
        'responsible_for_implementation_id_ref_type': PersonReferenceType.PERSON.value,
        'responsible_for_implementation_id': PERSON_ID,
    }


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager) -> ControlMeasureAssignmentManager:
    """The real assignment manager"""
    return ControlMeasureAssignmentManager(database_manager)


@pytest.fixture(name='assignments', autouse=True)
def fixture_assignments(database_manager: MongoDatabaseManager, database_name: str):
    """The assignment collection, purged of the test assessments' rows before and after"""
    collection = database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({RISK_ASSESSMENT_KEY: {'$in': [RA_ID, OTHER_RA_ID]}})

    _purge()
    yield collection
    _purge()


class TestAValidatedEntryIsAStorableAssignment:
    """What the RiskAssessment create route stores, read back"""

    def test_stored_under_a_server_id_and_read_back_as_the_model(self, manager, assignments) -> None:
        """The sent id is gone before the write; the read-back model carries every key the entry did"""
        with Flask(__name__).app_context():
            cleaned: list[dict[str, Any]] = validated_create_payload([
                {**_entry(), PUBLIC_ID_KEY: CLIENT_ID}, _entry(OTHER_MEASURE_ID),
            ])

        for entry in cleaned:
            entry[RISK_ASSESSMENT_KEY] = RA_ID

        created_ids: list[int] = manager.insert_many_items(cleaned)

        assert CLIENT_ID not in created_ids
        assert assignments.count_documents({PUBLIC_ID_KEY: CLIENT_ID}) == 0

        for created_id, measure_id in zip(created_ids, (MEASURE_ID, OTHER_MEASURE_ID)):
            model = IsmsControlMeasureAssignment.from_data(manager.get_item(created_id, as_dict=True))
            stored: dict[str, Any] = IsmsControlMeasureAssignment.to_json(model)

            assert {key: stored[key] for key in _entry()} == _entry(measure_id)
            assert stored[RISK_ASSESSMENT_KEY] == RA_ID


class TestIsControlMeasureAssigned:
    """One existence check per assessment and measure"""

    @pytest.fixture(autouse=True)
    def _stored(self, assignments) -> None:
        """RA_ID holds MEASURE_ID under STORED_ID"""
        assignments.insert_one({**_entry(), PUBLIC_ID_KEY: STORED_ID, RISK_ASSESSMENT_KEY: RA_ID})

    def test_the_held_measure_is_assigned(self, manager) -> None:
        """The create's question"""
        assert manager.is_control_measure_assigned(RA_ID, MEASURE_ID) is True

    def test_another_measure_is_not(self, manager) -> None:
        """Per measure"""
        assert manager.is_control_measure_assigned(RA_ID, OTHER_MEASURE_ID) is False

    def test_another_assessment_does_not_hold_it(self, manager) -> None:
        """Per assessment"""
        assert manager.is_control_measure_assigned(OTHER_RA_ID, MEASURE_ID) is False

    def test_the_holder_itself_is_left_out(self, manager) -> None:
        """The update's question: another assignment, not this one"""
        assert manager.is_control_measure_assigned(RA_ID, MEASURE_ID, exclude_public_id=STORED_ID) is False

    def test_a_second_holder_is_still_found_when_one_is_left_out(self, manager, assignments) -> None:
        """A stored duplicate is not hidden by leaving one row out"""
        assignments.insert_one({**_entry(), PUBLIC_ID_KEY: STORED_ID + 1, RISK_ASSESSMENT_KEY: RA_ID})

        assert manager.is_control_measure_assigned(RA_ID, MEASURE_ID, exclude_public_id=STORED_ID) is True

    def test_a_failed_count_is_the_managers_get_error(self, manager, monkeypatch: pytest.MonkeyPatch) -> None:
        """The routes map that one to their 400; the cause is kept"""
        failure = BaseManagerGetError('count failed')

        def _raise(*_args: Any, **_kwargs: Any) -> int:
            raise failure

        monkeypatch.setattr(manager, 'count_documents', _raise)

        with pytest.raises(ControlMeasureAssignmentManagerGetError) as caught:
            manager.is_control_measure_assigned(RA_ID, MEASURE_ID)

        assert caught.value.__cause__ is failure
