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
Integration tests: the risk-owner count that refuses a person / group delete, against a real MongoDB

``risk_owner_reference_criteria`` is what ``abort_if_risk_owner`` counts with. Pinned on stored assessments: it counts
the assessments a person owns, not those a group sharing its public_id owns (and the other way round), and not those
where it is only responsible or auditor
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.person_reference_helper import risk_owner_reference_criteria
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.person_group_model import PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

SHARED_ID: int = 96911                                 # a person and a group share it
PERSON_OWNED_IDS: list[int] = [96921, 96922, 96923]    # owned by the person
GROUP_OWNED_IDS: list[int] = [96931]                   # owned by the group
RESPONSIBLE_ONLY_ID: int = 96941                       # the person is only responsible here
ALL_IDS: list[int] = [*PERSON_OWNED_IDS, *GROUP_OWNED_IDS, RESPONSIBLE_ONLY_ID]
OTHER_OWNER_ID: int = 96999


def _assessment(public_id: int, owner: int, owner_type: PersonReferenceType, **extra: Any) -> dict[str, Any]:
    """A stored assessment with the given owner."""
    return {'public_id': public_id, 'risk_owner_id': owner, 'risk_owner_id_ref_type': owner_type.value, **extra}


@pytest.fixture(name='risk_assessment_manager')
def fixture_risk_assessment_manager(database_manager: MongoDatabaseManager, database_name: str):
    """The five assessments seeded directly, removed afterwards"""
    collection = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)
    collection.delete_many({'public_id': {'$in': ALL_IDS}})
    collection.insert_many([
        *(_assessment(public_id, SHARED_ID, PersonReferenceType.PERSON) for public_id in PERSON_OWNED_IDS),
        *(_assessment(public_id, SHARED_ID, PersonReferenceType.PERSON_GROUP) for public_id in GROUP_OWNED_IDS),
        _assessment(RESPONSIBLE_ONLY_ID, OTHER_OWNER_ID, PersonReferenceType.PERSON,
                    responsible_persons_id=SHARED_ID,
                    responsible_persons_id_ref_type=PersonReferenceType.PERSON.value),
    ])
    yield RiskAssessmentManager(database_manager)
    collection.delete_many({'public_id': {'$in': ALL_IDS}})


@pytest.mark.parametrize('reference_type,expected', [
    pytest.param(PersonReferenceType.PERSON, len(PERSON_OWNED_IDS), id='person'),
    pytest.param(PersonReferenceType.PERSON_GROUP, len(GROUP_OWNED_IDS), id='person group'),
])
def test_counts_only_what_this_kind_owns(
    risk_assessment_manager: RiskAssessmentManager, reference_type: PersonReferenceType, expected: int,
) -> None:
    """Same public_id, different ref_type: each counts its own; a responsible-only reference counts for nobody"""
    assert risk_assessment_manager.count_documents(
        risk_owner_reference_criteria(SHARED_ID, reference_type)
    ) == expected


def test_an_entity_that_owns_nothing_counts_zero(risk_assessment_manager: RiskAssessmentManager) -> None:
    """The responsible-only person of the seed is not an owner anywhere"""
    assert risk_assessment_manager.count_documents(
        risk_owner_reference_criteria(OTHER_OWNER_ID + 1, PersonReferenceType.PERSON)
    ) == 0
