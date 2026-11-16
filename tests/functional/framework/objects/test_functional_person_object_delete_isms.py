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
Functional tests of deleting a person or group object that ISMS documents name, through the real REST app

Persons and groups are objects of the test person Types. Pinned, on the single and the bulk delete:

  - a person or group owning a risk assessment is not deleted (400 naming it and the count), nothing changes
  - deleting a person clears it from every other reference - responsible, auditor, assessor, interviewed, an
    assignment's implementer - matched with its ref_type; deleting a group clears the group references only
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.framework.person_types.person_types_constants import RISK_OWNER_OBJECT_DELETE_MESSAGE
from tests.utils.person_objects import purge_person_objects, seed_person_objects
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects'

OWNER: int = 96701
STAFF: int = 96702
OTHER: int = 96703
TEAM: int = 96704
PERSON_IDS: list[int] = [OWNER, STAFF, OTHER, TEAM]
RA_ID: int = 96710
CMA_ID: int = 96711


def _assessment() -> dict[str, Any]:
    """An assessment owned by OWNER, STAFF in every other person key, TEAM never as a person"""
    return {
        'public_id': RA_ID, 'risk_owner_id': OWNER, 'risk_owner_id_ref_type': 'PERSON',
        'responsible_persons_id': STAFF, 'responsible_persons_id_ref_type': 'PERSON',
        'auditor_id': TEAM, 'auditor_id_ref_type': 'PERSON_GROUP',
        'risk_assessor_id': STAFF, 'interviewed_persons': [STAFF, OTHER],
    }


@pytest.fixture(name='isms', autouse=True)
def fixture_isms(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[dict[str, Any]]:
    """The persons, the group, an assessment and an assignment; purged before and after"""
    collections: dict[str, Any] = {
        'assessments': database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name),
        'assignments': database_manager.get_collection(IsmsControlMeasureAssignment.COLLECTION, database_name),
        'objects': database_manager.get_collection(CmdbObject.COLLECTION, database_name),
    }

    def _purge() -> None:
        collections['assessments'].delete_many({'public_id': RA_ID})
        collections['assignments'].delete_many({'public_id': CMA_ID})
        purge_person_objects(database_manager, database_name, PERSON_IDS)

    _purge()
    seed_person_objects(database_manager, database_name, persons={OWNER: 'Owner', STAFF: 'Staff', OTHER: 'Other'},
                        groups={TEAM: 'Team'})
    collections['assessments'].insert_one(_assessment())
    collections['assignments'].insert_one({
        'public_id': CMA_ID, 'risk_assessment_id': RA_ID, 'responsible_for_implementation_id': STAFF,
        'responsible_for_implementation_id_ref_type': 'PERSON',
    })
    yield collections
    _purge()


def _single(rest_api, object_id: int) -> Any:
    """The single delete"""
    return rest_api.delete(f'{OBJECTS_URL}/{object_id}')


def _bulk(rest_api, object_id: int) -> Any:
    """The bulk delete of one target"""
    return rest_api.delete(f'{OBJECTS_URL}/delete/{object_id}')


DELETES = pytest.mark.parametrize('delete', [_single, _bulk], ids=['single', 'bulk'])


@DELETES
def test_the_risk_owner_is_not_deleted(rest_api, isms, delete) -> None:
    """400 naming it and the count; the object and the assessment unchanged"""
    response = delete(rest_api, OWNER)

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == RISK_OWNER_OBJECT_DELETE_MESSAGE.format(ids=[OWNER], count=1)
    assert isms['objects'].count_documents({'public_id': OWNER}) == 1
    assert isms['assessments'].find_one({'public_id': RA_ID}, {'_id': 0}) == _assessment()


@DELETES
def test_a_deleted_person_leaves_every_other_reference(rest_api, isms, delete) -> None:
    """Responsible, assessor, interviewed and the implementer cleared; the group auditor untouched"""
    response = delete(rest_api, STAFF)

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assessment = isms['assessments'].find_one({'public_id': RA_ID})
    assert (assessment['responsible_persons_id'], assessment['risk_assessor_id'], assessment['auditor_id'],
            assessment['interviewed_persons']) == (None, None, TEAM, [OTHER])
    assert isms['assignments'].find_one({'public_id': CMA_ID})['responsible_for_implementation_id'] is None


@DELETES
def test_a_deleted_group_leaves_its_group_references(rest_api, isms, delete) -> None:
    """The group auditor cleared, the persons untouched"""
    response = delete(rest_api, TEAM)

    assert response.status_code == HTTPStatus.OK, response.get_json()
    assessment = isms['assessments'].find_one({'public_id': RA_ID})
    assert (assessment['auditor_id'], assessment['responsible_persons_id'], assessment['interviewed_persons']) == (
        None, STAFF, [STAFF, OTHER])
