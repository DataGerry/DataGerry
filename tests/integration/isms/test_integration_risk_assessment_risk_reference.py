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
Integration tests for RiskAssessmentManager.get_missing_risk_ids against a real MongoDB

The read the three RiskAssessment writes refuse an unknown Risk by: one projected ``$in`` over the Risk collection,
answering exactly the named ids no Risk carries - a stored Risk never, an absent one always, nothing for no ids. And
the route helper on top of it answers the 400 naming the absent ones.
"""
import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.isms_model import IsmsRisk
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import UNKNOWN_RISKS_MSG
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import abort_on_unknown_risks
# -------------------------------------------------------------------------------------------------------------------- #

STORED_RISK_ID: int = 99711
SECOND_STORED_RISK_ID: int = 99712
ABSENT_RISK_ID: int = 99719
HTTP_BAD_REQUEST: int = 400


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str):
    """Two stored Risks; removed again"""
    risks = database_manager.get_collection(IsmsRisk.COLLECTION, database_name)
    stored_ids: list[int] = [STORED_RISK_ID, SECOND_STORED_RISK_ID]
    risks.delete_many({'public_id': {'$in': stored_ids}})
    risks.insert_many([{'public_id': risk_id, 'name': f'reference-{risk_id}'} for risk_id in stored_ids])

    yield RiskAssessmentManager(database_manager)

    risks.delete_many({'public_id': {'$in': stored_ids}})


def test_only_the_absent_ids_are_missing(manager: RiskAssessmentManager) -> None:
    """Stored ones never, the absent one always"""
    assert manager.get_missing_risk_ids({STORED_RISK_ID, SECOND_STORED_RISK_ID, ABSENT_RISK_ID}) == {ABSENT_RISK_ID}


def test_every_stored_risk_answers_none(manager: RiskAssessmentManager) -> None:
    """The ordinary write"""
    assert manager.get_missing_risk_ids({STORED_RISK_ID}) == set()


def test_no_ids_answer_none(manager: RiskAssessmentManager) -> None:
    """Nothing named"""
    assert manager.get_missing_risk_ids(set()) == set()


def test_the_helper_refuses_the_absent_one(manager: RiskAssessmentManager) -> None:
    """Named in the 400"""
    with pytest.raises(HTTPException) as exc_info:
        abort_on_unknown_risks(manager, {STORED_RISK_ID, ABSENT_RISK_ID})

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert exc_info.value.description == UNKNOWN_RISKS_MSG.format(unknown=[ABSENT_RISK_ID])
