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
Functional tests: a person or person group that owns a RiskAssessment cannot be deleted

The delete cascade clears the ISMS references to a deleted person / group, but ``risk_owner_id`` is a required
assessment field - clearing it left assessments every later save refused. Pinned on both routes
(``DELETE /persons/<id>``, ``DELETE /person_groups/<id>``):

  - an owner is refused with a 400 naming how many assessments it owns; the entity and the assessment are unchanged
  - an entity that is only responsible / auditor is deleted, and the cascade clears those optional references
  - the owner is matched by id AND ref_type: a person sharing its public_id with an owning group is deleted
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.person_model import CmdbPerson
from cmdb.models.person_group_model import CmdbPersonGroup, PersonReferenceType
# -------------------------------------------------------------------------------------------------------------------- #

PERSONS_URL: str = '/persons'
GROUPS_URL: str = '/person_groups'
# A person and a group SHARING a public_id - the ref_type is what tells them apart
SHARED_ID: int = 96811
OTHER_PERSON_ID: int = 96812
ASSESSMENT_IDS: list[int] = [96821, 96822]
# Assessments seeded per test, keyed by what the deleted entity is in them
OWNER_KEY: str = 'risk_owner_id'
RESPONSIBLE_KEY: str = 'responsible_persons_id'
AUDITOR_KEY: str = 'auditor_id'


def _ref_type(key: str) -> str:
    """The '<key>_ref_type' sibling of a polymorphic reference."""
    return f'{key}_ref_type'


def _assessment(public_id: int, **references: tuple[int, PersonReferenceType]) -> dict[str, Any]:
    """A stored assessment naming the given polymorphic references; the owner defaults to OTHER_PERSON_ID."""
    document: dict[str, Any] = {'public_id': public_id, OWNER_KEY: OTHER_PERSON_ID,
                                _ref_type(OWNER_KEY): PersonReferenceType.PERSON.value}
    for key, (referenced_id, reference_type) in references.items():
        document[key] = referenced_id
        document[_ref_type(key)] = reference_type.value

    return document


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch):
    """The /persons and /person_groups routes are ISMS-gated"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """A person and a group sharing SHARED_ID, the other person; the assessments are seeded by each test"""
    persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
    groups = database_manager.get_collection(CmdbPersonGroup.COLLECTION, database_name)
    assessments = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)

    def _purge() -> None:
        persons.delete_many({'public_id': {'$in': [SHARED_ID, OTHER_PERSON_ID]}})
        groups.delete_many({'public_id': SHARED_ID})
        assessments.delete_many({'public_id': {'$in': ASSESSMENT_IDS}})

    _purge()
    for public_id in (SHARED_ID, OTHER_PERSON_ID):
        persons.insert_one({'public_id': public_id, 'display_name': f'Person {public_id}', 'first_name': 'F',
                            'last_name': 'L', 'groups': []})
    groups.insert_one({'public_id': SHARED_ID, 'name': f'Group {SHARED_ID}', 'email': '', 'group_members': []})
    yield {'persons': persons, 'groups': groups, 'assessments': assessments}
    _purge()


SIDES: list[Any] = [
    pytest.param(PERSONS_URL, 'persons', PersonReferenceType.PERSON, id='person'),
    pytest.param(GROUPS_URL, 'groups', PersonReferenceType.PERSON_GROUP, id='person group'),
]


@pytest.mark.parametrize('url,collection,reference_type', SIDES)
def test_an_owner_is_refused_and_nothing_changes(
    rest_api, collections, url: str, collection: str, reference_type: PersonReferenceType,
) -> None:
    """400 naming the number of owned assessments; the entity is kept and the owner too"""
    owned = {OWNER_KEY: (SHARED_ID, reference_type)}
    collections['assessments'].insert_many([_assessment(public_id, **owned) for public_id in ASSESSMENT_IDS])

    response = rest_api.delete(f'{url}/{SHARED_ID}')

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert f'{len(ASSESSMENT_IDS)} RiskAssessment(s)' in response.get_json()['message']
    assert collections[collection].find_one({'public_id': SHARED_ID}) is not None
    stored = collections['assessments'].find_one({'public_id': ASSESSMENT_IDS[0]})
    assert (stored[OWNER_KEY], stored[_ref_type(OWNER_KEY)]) == (SHARED_ID, reference_type.value)


@pytest.mark.parametrize('url,collection,reference_type', SIDES)
def test_an_optional_reference_does_not_block_and_is_cleared(
    rest_api, collections, url: str, collection: str, reference_type: PersonReferenceType,
) -> None:
    """Responsible and auditor are optional: the delete goes through and the cascade clears both"""
    collections['assessments'].insert_one(_assessment(
        ASSESSMENT_IDS[0], **{RESPONSIBLE_KEY: (SHARED_ID, reference_type), AUDITOR_KEY: (SHARED_ID, reference_type)},
    ))

    response = rest_api.delete(f'{url}/{SHARED_ID}')

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert collections[collection].find_one({'public_id': SHARED_ID}) is None
    stored = collections['assessments'].find_one({'public_id': ASSESSMENT_IDS[0]})
    assert (stored[RESPONSIBLE_KEY], stored[AUDITOR_KEY], stored[OWNER_KEY]) == (None, None, OTHER_PERSON_ID)


def test_a_person_sharing_the_id_of_an_owning_group_is_deleted(rest_api, collections) -> None:
    """The group owns the assessment, not the person with the same public_id - the ref_type decides"""
    collections['assessments'].insert_one(
        _assessment(ASSESSMENT_IDS[0], **{OWNER_KEY: (SHARED_ID, PersonReferenceType.PERSON_GROUP)}),
    )

    response = rest_api.delete(f'{PERSONS_URL}/{SHARED_ID}')

    assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
    assert collections['persons'].find_one({'public_id': SHARED_ID}) is None
    assert collections['assessments'].find_one({'public_id': ASSESSMENT_IDS[0]})[OWNER_KEY] == SHARED_ID
