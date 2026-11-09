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
Functional tests for the id lists of an ISMS write, over HTTP

Pinned:

  - a Risk's ``threats`` / ``vulnerabilities`` / ``protection_goals`` item that is no id (a string, a dict, ``true``,
    0) is a 400 naming the field - each used to be stored as sent; an unknown id is a 400 naming every one with its
    field; a repeated id is a 400; on create and update; nothing is written
  - an ImpactCategory description naming ``true``, an unknown Impact or one Impact twice is a 400 - on create, update
    and every item of the bulk reorder (named by its category); nothing is written
  - a ControlMeasureAssignment's ControlMeasure / RiskAssessment of ``true`` or 0 is the schema's 400, not an
    "unknown" one after a read
  - a failed lookup is its own 400; stored ids pass (the controls)
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsThreat,
    IsmsVulnerability,
    RiskType,
)
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    REFERENCE_LOOKUP_FAILED_MSG,
    REPEATED_REFERENCED_IDS_MSG,
    UNKNOWN_REFERENCED_IDS_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

RISKS_URL: str = '/isms/risks'
CATEGORIES_URL: str = '/isms/impact_categories'
ASSIGNMENTS_URL: str = '/isms/control_measure_assignments'
MESSAGE_KEY: str = 'message'

THREAT: int = 98901
VULNERABILITY: int = 98902
GOAL: int = 98903
IMPACT: int = 98904
MISSING: int = 98909
STORED_RISK: int = 98911
STORED_CATEGORY: int = 98921
OTHER_CATEGORY: int = 98922
RISK_NAME: str = 'Id references risk'
CATEGORY_NAME: str = 'Id references category'
NOT_AN_ID: list[Any] = [0, True, 'x', {'a': 1}]
NOT_AN_ID_NAMES: list[str] = ['zero', 'true', 'string', 'dict']

SEEDED: dict[str, list[int]] = {
    IsmsThreat.COLLECTION: [THREAT],
    IsmsVulnerability.COLLECTION: [VULNERABILITY],
    IsmsProtectionGoal.COLLECTION: [GOAL],
    IsmsImpact.COLLECTION: [IMPACT],
}


def _risk(**overrides: Any) -> dict[str, Any]:
    """A THREAT_X_VULNERABILITY Risk naming the stored Threat, Vulnerability and ProtectionGoal"""
    return {'name': RISK_NAME, 'risk_type': RiskType.THREAT_X_VULNERABILITY.value, 'category_id': None,
            'threats': [THREAT], 'vulnerabilities': [VULNERABILITY], 'protection_goals': [GOAL], **overrides}


def _category(*impact_ids: Any, public_id: int | None = None) -> dict[str, Any]:
    """An ImpactCategory describing the given Impacts"""
    body: dict[str, Any] = {'name': CATEGORY_NAME, 'sort': 1, 'impact_descriptions': [
        {'impact_id': impact_id, 'value': f'level {index}'} for index, impact_id in enumerate(impact_ids)
    ]}

    if public_id is not None:
        body['public_id'] = public_id

    return body


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='stored', autouse=True)
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The referenced documents, a stored Risk and two stored categories; everything the tests write removed again"""
    def _collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        for name, public_ids in SEEDED.items():
            _collection(name).delete_many({'public_id': {'$in': public_ids}})
        _collection(IsmsRisk.COLLECTION).delete_many({'$or': [{'public_id': STORED_RISK}, {'name': RISK_NAME}]})
        _collection(IsmsImpactCategory.COLLECTION).delete_many(
            {'$or': [{'public_id': {'$in': [STORED_CATEGORY, OTHER_CATEGORY]}}, {'name': CATEGORY_NAME}]})

    _purge()
    _collection(IsmsThreat.COLLECTION).insert_one({'public_id': THREAT, 'name': 'Id references threat'})
    _collection(IsmsVulnerability.COLLECTION).insert_one({'public_id': VULNERABILITY, 'name': 'Id references vuln'})
    _collection(IsmsProtectionGoal.COLLECTION).insert_one({'public_id': GOAL, 'name': 'Id references goal'})
    _collection(IsmsImpact.COLLECTION).insert_one({'public_id': IMPACT, 'name': 'Id references impact',
                                                   'calculation_basis': 77.5})
    _collection(IsmsRisk.COLLECTION).insert_one({**_risk(), 'public_id': STORED_RISK, 'name': 'stored risk'})
    _collection(IsmsImpactCategory.COLLECTION).insert_many([
        {**_category(IMPACT), 'public_id': STORED_CATEGORY, 'name': 'stored category'},
        {**_category(), 'public_id': OTHER_CATEGORY, 'name': 'other category'},
    ])
    yield _collection
    _purge()


def _refused(response: Any, message: str | None = None) -> str:
    """A 400 - with exactly this message when given; answers the message"""
    assert response.status_code == HTTPStatus.BAD_REQUEST, response.get_json()

    if message is not None:
        assert response.get_json()[MESSAGE_KEY] == message

    return response.get_json()[MESSAGE_KEY]


def _risks_written(stored: Any) -> int:
    """How many Risks the tests wrote"""
    return stored(IsmsRisk.COLLECTION).count_documents({'name': RISK_NAME})


class TestRiskCreate:
    """POST /isms/risks/"""

    def test_stored_ids_pass(self, rest_api, stored: Any) -> None:
        """The control"""
        assert rest_api.post(f'{RISKS_URL}/', json=_risk()).status_code == HTTPStatus.CREATED
        assert _risks_written(stored) == 1

    @pytest.mark.parametrize('field', ['threats', 'vulnerabilities', 'protection_goals'])
    @pytest.mark.parametrize('item', NOT_AN_ID, ids=NOT_AN_ID_NAMES)
    def test_an_item_that_is_no_id_is_a_400_naming_the_field(self, rest_api, stored: Any, field: str,
                                                            item: Any) -> None:
        """Each used to be stored as sent"""
        message: str = _refused(rest_api.post(f'{RISKS_URL}/', json=_risk(**{field: [item]})))

        assert field in message
        assert _risks_written(stored) == 0

    def test_every_unknown_id_is_named_with_its_field(self, rest_api, stored: Any) -> None:
        """One 400"""
        _refused(rest_api.post(f'{RISKS_URL}/', json=_risk(threats=[THREAT, MISSING], protection_goals=[MISSING])),
                 UNKNOWN_REFERENCED_IDS_MSG.format(
                     entity='Risk', reasons=f'threats: [{MISSING}]; protection_goals: [{MISSING}]'))
        assert _risks_written(stored) == 0

    def test_a_repeated_id_is_a_400(self, rest_api, stored: Any) -> None:
        """Named once"""
        _refused(rest_api.post(f'{RISKS_URL}/', json=_risk(vulnerabilities=[VULNERABILITY, VULNERABILITY])),
                 REPEATED_REFERENCED_IDS_MSG.format(entity='Risk', reasons=f'vulnerabilities: [{VULNERABILITY}]'))

    def test_a_failed_lookup_is_its_own_400(self, rest_api, stored: Any, monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('threats unreadable')

        monkeypatch.setattr(BaseManager, 'get_many_from_other_collection', _failing)

        _refused(rest_api.post(f'{RISKS_URL}/', json=_risk()), REFERENCE_LOOKUP_FAILED_MSG.format(label='Threat'))
        assert _risks_written(stored) == 0


class TestRiskUpdate:
    """PUT /isms/risks/<id>"""

    def test_an_unknown_threat_is_a_400_and_nothing_changes(self, rest_api, stored: Any) -> None:
        """The stored lists are kept"""
        before: dict[str, Any] = stored(IsmsRisk.COLLECTION).find_one({'public_id': STORED_RISK})

        _refused(rest_api.put(f'{RISKS_URL}/{STORED_RISK}', json=_risk(threats=[MISSING])),
                 UNKNOWN_REFERENCED_IDS_MSG.format(entity='Risk', reasons=f'threats: [{MISSING}]'))
        assert stored(IsmsRisk.COLLECTION).find_one({'public_id': STORED_RISK}) == before

    def test_stored_ids_pass(self, rest_api, stored: Any) -> None:
        """The control"""
        assert rest_api.put(f'{RISKS_URL}/{STORED_RISK}', json=_risk()).status_code == HTTPStatus.ACCEPTED


class TestImpactCategoryWrites:
    """POST / PUT /isms/impact_categories"""

    def test_create_with_a_stored_impact_passes(self, rest_api) -> None:
        """The control"""
        assert rest_api.post(f'{CATEGORIES_URL}/', json=_category(IMPACT)).status_code == HTTPStatus.CREATED

    @pytest.mark.parametrize('impact_id', [True, 0], ids=['true', 'zero'])
    def test_an_impact_id_that_is_no_id_is_a_400(self, rest_api, stored: Any, impact_id: Any) -> None:
        """``true`` used to be stored"""
        assert 'impact_id' in _refused(rest_api.post(f'{CATEGORIES_URL}/', json=_category(impact_id)))
        assert stored(IsmsImpactCategory.COLLECTION).count_documents({'name': CATEGORY_NAME}) == 0

    def test_create_with_an_unknown_impact_is_a_400(self, rest_api, stored: Any) -> None:
        """Named with the field"""
        _refused(rest_api.post(f'{CATEGORIES_URL}/', json=_category(IMPACT, MISSING)),
                 UNKNOWN_REFERENCED_IDS_MSG.format(
                     entity='ImpactCategory', reasons=f'impact_descriptions.impact_id: [{MISSING}]'))
        assert stored(IsmsImpactCategory.COLLECTION).count_documents({'name': CATEGORY_NAME}) == 0

    def test_update_describing_one_impact_twice_is_a_400(self, rest_api, stored: Any) -> None:
        """The stored category is kept"""
        before: dict[str, Any] = stored(IsmsImpactCategory.COLLECTION).find_one({'public_id': STORED_CATEGORY})

        _refused(rest_api.put(f'{CATEGORIES_URL}/{STORED_CATEGORY}', json=_category(IMPACT, IMPACT)),
                 REPEATED_REFERENCED_IDS_MSG.format(
                     entity='ImpactCategory', reasons=f'impact_descriptions.impact_id: [{IMPACT}]'))
        assert stored(IsmsImpactCategory.COLLECTION).find_one({'public_id': STORED_CATEGORY}) == before

    def test_the_bulk_reorder_names_the_category_and_writes_nothing(self, rest_api, stored: Any) -> None:
        """All or nothing"""
        before: list[dict[str, Any]] = list(stored(IsmsImpactCategory.COLLECTION).find(
            {'public_id': {'$in': [STORED_CATEGORY, OTHER_CATEGORY]}}, {'_id': 0}))
        items: list[dict[str, Any]] = [
            {**_category(IMPACT, public_id=STORED_CATEGORY), 'sort': 2},
            {**_category(MISSING, public_id=OTHER_CATEGORY), 'sort': 1},
        ]

        _refused(rest_api.put(f'{CATEGORIES_URL}/multiple', json=items), UNKNOWN_REFERENCED_IDS_MSG.format(
            entity=f'ImpactCategory {OTHER_CATEGORY}', reasons=f'impact_descriptions.impact_id: [{MISSING}]'))
        assert list(stored(IsmsImpactCategory.COLLECTION).find(
            {'public_id': {'$in': [STORED_CATEGORY, OTHER_CATEGORY]}}, {'_id': 0})) == before

    def test_the_bulk_reorder_with_stored_impacts_passes(self, rest_api) -> None:
        """The control"""
        items: list[dict[str, Any]] = [{**_category(IMPACT, public_id=STORED_CATEGORY), 'sort': 2},
                                       {**_category(public_id=OTHER_CATEGORY), 'sort': 1}]

        assert rest_api.put(f'{CATEGORIES_URL}/multiple', json=items).status_code == HTTPStatus.OK


class TestAssignmentIds:
    """POST /isms/control_measure_assignments/ - the schema answers before any read"""

    @pytest.mark.parametrize('key', ['control_measure_id', 'risk_assessment_id'])
    @pytest.mark.parametrize('value', [True, 0, -1], ids=['true', 'zero', 'negative'])
    def test_an_id_that_is_no_id_is_the_schemas_400(self, rest_api, key: str, value: Any) -> None:
        """Not 'Unknown ControlMeasure(s) referenced: [True]'"""
        body: dict[str, Any] = {
            'control_measure_id': THREAT, 'risk_assessment_id': THREAT, 'planned_implementation_date': None,
            'implementation_status': THREAT, 'finished_implementation_date': None, 'priority': None,
            'responsible_for_implementation_id_ref_type': None, 'responsible_for_implementation_id': None,
            key: value,
        }

        message: str = _refused(rest_api.post(f'{ASSIGNMENTS_URL}/', json=body))

        assert key in message
        assert 'Unknown' not in message and 'do not exist' not in message
