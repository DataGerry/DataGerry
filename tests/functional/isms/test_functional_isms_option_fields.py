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
Functional tests: every ISMS field holding an option id names an option of its own list, or nothing

The Threat and Vulnerability ``source`` (THREAT_VULNERABILITY), the ControlMeasure ``source`` (CONTROL_MEASURE) and the
Risk's ``category_id`` (RISK), each on create and update. Pinned: an option of another list and an unknown id are a 400
naming the field's label and list - each used to be stored (201); ``true`` / 0 are the schema's 400; null and an
option of the field's own list pass; a failed option read is its own 400; a refused write stores nothing
"""
from http import HTTPStatus
from typing import Any, Iterator, NamedTuple

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager.extendable_options_manager import ExtendableOptionsManagerGetError
from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRisk, IsmsThreat, IsmsVulnerability, RiskType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    CONTROL_MEASURE_SOURCE_OPTION,
    OPTION_LOOKUP_FAILED_MSG,
    RISK_CATEGORY_OPTION,
    THREAT_VULNERABILITY_SOURCE_OPTION,
    UNKNOWN_OPTIONS_MSG,
    IsmsOptionField,
)
from tests.utils.isms_reference_seed import (
    CONTROL_MEASURE_SOURCE_ID,
    IMPLEMENTATION_STATE_ID,
    MISSING_OPTION_ID,
    RISK_CATEGORY_OPTION_ID,
    THREAT_VULNERABILITY_SOURCE_ID,
)
# -------------------------------------------------------------------------------------------------------------------- #

MESSAGE_KEY: str = 'message'
MARKER: str = 'Option field probe'
STORED_ID: int = 98951


class OptionCase(NamedTuple):
    """One field under test: its route, a valid body, the field, its own option and its check"""
    url: str
    model: Any
    body: dict[str, Any]
    key: str
    own_option: int
    option_field: IsmsOptionField


CASES: list[OptionCase] = [
    OptionCase('/isms/threats', IsmsThreat, {'name': MARKER, 'source': None}, 'source',
               THREAT_VULNERABILITY_SOURCE_ID, THREAT_VULNERABILITY_SOURCE_OPTION),
    OptionCase('/isms/vulnerabilities', IsmsVulnerability, {'name': MARKER, 'source': None}, 'source',
               THREAT_VULNERABILITY_SOURCE_ID, THREAT_VULNERABILITY_SOURCE_OPTION),
    OptionCase('/isms/control_measures', IsmsControlMeasure, {
        'title': MARKER, 'control_measure_type': 'CONTROL', 'source': None, 'implementation_state': None,
        'identifier': None, 'chapter': None, 'description': None, 'is_applicable': True, 'reason': None,
    }, 'source', CONTROL_MEASURE_SOURCE_ID, CONTROL_MEASURE_SOURCE_OPTION),
    OptionCase('/isms/risks', IsmsRisk, {
        'name': MARKER, 'risk_type': RiskType.EVENT.value, 'category_id': None, 'consequences': 'c', 'description': 'd',
    }, 'category_id', RISK_CATEGORY_OPTION_ID, RISK_CATEGORY_OPTION),
]
CASE_IDS: list[str] = ['threat-source', 'vulnerability-source', 'control-measure-source', 'risk-category']


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='collection')
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str, case: OptionCase) -> Iterator[Any]:
    """The case's collection with one stored document; everything the test writes removed again"""
    collection = database_manager.get_collection(case.model.COLLECTION, database_name)
    marker_query: dict[str, Any] = {'$or': [{'public_id': STORED_ID}, {'name': MARKER}, {'title': MARKER}]}
    collection.delete_many(marker_query)
    collection.insert_one({**case.body, 'public_id': STORED_ID})
    yield collection
    collection.delete_many(marker_query)


def _written(collection: Any) -> int:
    """How many documents the test wrote"""
    return collection.count_documents({'$or': [{'name': MARKER}, {'title': MARKER}], 'public_id': {'$ne': STORED_ID}})


def _unknown(case: OptionCase, option_id: int) -> str:
    """The field's refusal"""
    return UNKNOWN_OPTIONS_MSG.format(label=case.option_field.label, unknown=[option_id],
                                      option_type=case.option_field.option_type.value)


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
class TestCreate:
    """POST on each route"""

    @pytest.mark.parametrize('value_name', ['null', 'own-option'])
    def test_null_or_an_option_of_its_list_passes(self, rest_api, collection: Any, case: OptionCase,
                                                  value_name: str) -> None:
        """The controls"""
        value: int | None = None if value_name == 'null' else case.own_option

        assert rest_api.post(f'{case.url}/', json={**case.body, case.key: value}).status_code == HTTPStatus.CREATED
        assert _written(collection) == 1

    @pytest.mark.parametrize('option_id', [IMPLEMENTATION_STATE_ID, MISSING_OPTION_ID], ids=['other-list', 'missing'])
    def test_an_option_not_of_its_list_is_a_400(self, rest_api, collection: Any, case: OptionCase,
                                                option_id: int) -> None:
        """Each used to be stored"""
        response = rest_api.post(f'{case.url}/', json={**case.body, case.key: option_id})

        assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (
            HTTPStatus.BAD_REQUEST, _unknown(case, option_id),
        )
        assert _written(collection) == 0

    @pytest.mark.parametrize('value', [True, 0], ids=['true', 'zero'])
    def test_no_id_is_the_schemas_400(self, rest_api, collection: Any, case: OptionCase, value: Any) -> None:
        """Before any read"""
        response = rest_api.post(f'{case.url}/', json={**case.body, case.key: value})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert case.key in response.get_json()[MESSAGE_KEY]
        assert _written(collection) == 0

    def test_a_failed_option_read_is_its_own_400(self, rest_api, collection: Any, case: OptionCase,
                                                 monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise ExtendableOptionsManagerGetError('options unreadable')

        monkeypatch.setattr(ExtendableOptionsManager, 'get_missing_option_ids', _failing)

        response = rest_api.post(f'{case.url}/', json={**case.body, case.key: case.own_option})

        assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (
            HTTPStatus.BAD_REQUEST, OPTION_LOOKUP_FAILED_MSG.format(label=case.option_field.label),
        )
        assert _written(collection) == 0


@pytest.mark.parametrize('case', CASES, ids=CASE_IDS)
class TestUpdate:
    """PUT on each route"""

    def test_an_option_of_another_list_is_a_400_and_nothing_changes(self, rest_api, collection: Any,
                                                                    case: OptionCase) -> None:
        """The stored value is kept"""
        before: dict[str, Any] = collection.find_one({'public_id': STORED_ID})

        response = rest_api.put(f'{case.url}/{STORED_ID}', json={**case.body, case.key: IMPLEMENTATION_STATE_ID})

        assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (
            HTTPStatus.BAD_REQUEST, _unknown(case, IMPLEMENTATION_STATE_ID),
        )
        assert collection.find_one({'public_id': STORED_ID}) == before

    def test_an_option_of_its_list_passes(self, rest_api, collection: Any, case: OptionCase) -> None:
        """The control"""
        response = rest_api.put(f'{case.url}/{STORED_ID}', json={**case.body, case.key: case.own_option})

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collection.find_one({'public_id': STORED_ID})[case.key] == case.own_option
