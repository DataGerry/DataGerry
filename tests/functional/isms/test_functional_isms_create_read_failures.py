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
Functional tests for the ISMS create-time reads and the ProtectionGoal name rule

- a failed cap count on the RiskClass / Impact / Likelihood create is the CAP_CHECK 400, nothing inserted
- a failed name read on the ProtectionGoal create and update is the NAME_CHECK 400, nothing written
- a name taken between the pre-check and the write (the pre-check made to miss) is refused by the unique index
  with the pre-check's own 400, on the create and on a rename; the goal keeps its name
- a goal may still keep its own name on an update, and another spelling is another name (exact compare)
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.isms_manager.protection_goal_manager import ProtectionGoalManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsImpact, IsmsLikelihood, IsmsProtectionGoal, IsmsRiskClass
from cmdb.models.isms_model.isms_protection_goal_constants import ProtectionGoalKey
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ISMS_IMPACTS_LABEL,
    ISMS_LIKELIHOODS_LABEL,
    ISMS_RISK_CLASSES_LABEL,
    PROTECTION_GOAL_LABEL,
    PROTECTION_GOAL_NAME_TAKEN_MSG,
    IsmsManagerErrorMessage,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import manager_error_message
# -------------------------------------------------------------------------------------------------------------------- #

ISMS_PREFIX: str = '/isms'
GOALS_URL: str = f'{ISMS_PREFIX}/protection_goals'
MESSAGE_KEY: str = 'message'
PROBE_NAME: str = 'T416 probe'
GOAL_ID: int = 99681
OTHER_GOAL_ID: int = 99682
TAKEN_NAME: str = 'T416 taken'
OWN_NAME: str = 'T416 own'
OTHER_SPELLING: str = 't416 TAKEN'
ALL_GOAL_IDS: list[int] = [GOAL_ID, OTHER_GOAL_ID]
ALL_GOAL_NAMES: list[str] = [PROBE_NAME, TAKEN_NAME, OWN_NAME, OTHER_SPELLING]
UNUSED_BASIS: float = 9.5

# One valid create body per capped collection, with the entity's plural label and collection
CAPPED_CREATES: list[tuple[str, dict[str, Any], str, str]] = [
    ('risk_classes', {'name': PROBE_NAME, 'description': '', 'color': '#ffffff', 'sort': 1},
     ISMS_RISK_CLASSES_LABEL, IsmsRiskClass.COLLECTION),
    ('impacts', {'name': PROBE_NAME, 'calculation_basis': UNUSED_BASIS}, ISMS_IMPACTS_LABEL, IsmsImpact.COLLECTION),
    ('likelihoods', {'name': PROBE_NAME, 'calculation_basis': UNUSED_BASIS},
     ISMS_LIKELIHOODS_LABEL, IsmsLikelihood.COLLECTION),
]


def _raise_get_error(*_args: Any, **_kwargs: Any) -> Any:
    """A failed database read"""
    raise BaseManagerGetError('read failed')


def _goal(public_id: int, name: str) -> dict[str, Any]:
    """A stored, non-predefined goal"""
    return {'public_id': public_id, 'name': name, 'predefined': False}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='goals')
def fixture_goals(database_manager: MongoDatabaseManager, database_name: str):
    """Two stored goals and the unique name index, all removed again"""
    collection = database_manager.get_collection(IsmsProtectionGoal.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({'$or': [{'public_id': {'$in': ALL_GOAL_IDS}}, {'name': {'$in': ALL_GOAL_NAMES}}]})

    _purge()
    collection.insert_many([_goal(GOAL_ID, OWN_NAME), _goal(OTHER_GOAL_ID, TAKEN_NAME)])
    database_manager.create_indexes(IsmsProtectionGoal.COLLECTION, database_name, IsmsProtectionGoal.get_index_keys())

    yield collection

    database_manager.drop_index(IsmsProtectionGoal.COLLECTION, database_name, ProtectionGoalKey.NAME.value)
    _purge()


@pytest.mark.parametrize('route, body, label, collection', CAPPED_CREATES, ids=[entry[0] for entry in CAPPED_CREATES])
def test_a_failed_cap_count_is_the_cap_check_400(rest_api, monkeypatch, database_manager: MongoDatabaseManager,
                                                 database_name: str, route: str, body: dict[str, Any], label: str,
                                                 collection: str) -> None:
    """Not the route's 500 - and nothing is inserted"""
    monkeypatch.setattr(BaseManager, 'count_documents', _raise_get_error)

    response = rest_api.post(f'{ISMS_PREFIX}/{route}/', json=body)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()[MESSAGE_KEY] == IsmsManagerErrorMessage.CAP_CHECK.value.format(entities=label)
    assert database_manager.get_collection(collection, database_name).count_documents({'name': PROBE_NAME}) == 0


@pytest.mark.usefixtures('goals')
class TestTheNameRead:
    """A failed name read is the NAME_CHECK 400 on both writes"""

    def _failing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The name read fails"""
        monkeypatch.setattr(ProtectionGoalManager, 'get_one_by', _raise_get_error)

    def test_on_the_create(self, rest_api, monkeypatch, goals) -> None:
        """Nothing inserted"""
        self._failing(monkeypatch)

        response = rest_api.post(f'{GOALS_URL}/', json={'name': PROBE_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == manager_error_message(
            PROTECTION_GOAL_LABEL, IsmsManagerErrorMessage.NAME_CHECK,
        )
        assert goals.count_documents({'name': PROBE_NAME}) == 0

    def test_on_the_update(self, rest_api, monkeypatch, goals) -> None:
        """The goal keeps its name"""
        self._failing(monkeypatch)

        response = rest_api.put(f'{GOALS_URL}/{GOAL_ID}', json={'name': PROBE_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == manager_error_message(
            PROTECTION_GOAL_LABEL, IsmsManagerErrorMessage.NAME_CHECK,
        )
        assert goals.find_one({'public_id': GOAL_ID})['name'] == OWN_NAME


@pytest.mark.usefixtures('goals')
class TestTheNameIndex:
    """The unique index holds when the pre-check is made to miss, as in a lost race"""

    def _missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pre-check sees no holder"""
        monkeypatch.setattr(ProtectionGoalManager, 'find_name_holder', lambda *_args: None)

    def test_a_create_of_a_taken_name_is_the_pre_checks_400(self, rest_api, monkeypatch, goals) -> None:
        """One goal keeps the name"""
        self._missing(monkeypatch)

        response = rest_api.post(f'{GOALS_URL}/', json={'name': TAKEN_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=TAKEN_NAME)
        assert goals.count_documents({'name': TAKEN_NAME}) == 1

    def test_a_rename_onto_a_taken_name_is_the_pre_checks_400(self, rest_api, monkeypatch, goals) -> None:
        """The renamed goal keeps its own name"""
        self._missing(monkeypatch)

        response = rest_api.put(f'{GOALS_URL}/{GOAL_ID}', json={'name': TAKEN_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=TAKEN_NAME)
        assert goals.find_one({'public_id': GOAL_ID})['name'] == OWN_NAME

    def test_the_pre_check_answers_the_ordinary_case(self, rest_api, goals) -> None:
        """Without the race the read refuses first, with the same message"""
        response = rest_api.post(f'{GOALS_URL}/', json={'name': TAKEN_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()[MESSAGE_KEY] == PROTECTION_GOAL_NAME_TAKEN_MSG.format(name=TAKEN_NAME)
        assert goals.count_documents({'name': TAKEN_NAME}) == 1

    def test_a_goal_keeps_its_own_name(self, rest_api, goals) -> None:
        """An update that does not rename"""
        response = rest_api.put(f'{GOALS_URL}/{GOAL_ID}', json={'name': OWN_NAME, 'predefined': False})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert goals.find_one({'public_id': GOAL_ID})['name'] == OWN_NAME

    def test_another_spelling_is_another_name(self, rest_api, goals) -> None:
        """Names compare exactly"""
        response = rest_api.post(f'{GOALS_URL}/', json={'name': OTHER_SPELLING, 'predefined': False})

        assert response.status_code == HTTPStatus.CREATED
        assert goals.count_documents({'name': OTHER_SPELLING}) == 1
