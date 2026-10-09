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
Functional tests: every person / person-group write is all-or-nothing

A person names their groups and a group names its members, and both lists are stored, so each write route writes
two collections - three more on a delete, which clears the ISMS references. MongoDB runs standalone, so the routes
record their writes in a WriteLedger and undo them when a later write fails. These tests break each later write in
turn, on both route files, and compare every collection with the snapshot taken before the request.

The seed: person P1 in group G1 (both sides agree), person P2 and group G2 in nothing, an assessment whose assessor
and owner are P1 and whose auditor is G1, and an assignment G1 is responsible for.
"""
from http import HTTPStatus
from typing import Any, Callable, NamedTuple

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import PersonGroupsManager, PersonsManager, RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.isms_model.isms_control_measure_assignment import IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_risk_assessment import IsmsRiskAssessment
from cmdb.models.person_group_model import CmdbPersonGroup, PersonGroupKey
from cmdb.models.person_model import CmdbPerson, PersonKey
from cmdb.interface.rest_api.routes.user_management_routes import person_membership_helper
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import (
    PERSON_GROUP_WRITE_RESIDUE,
    PERSON_WRITE_RESIDUE,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSON_1: int = 97101
PERSON_2: int = 97102
GROUP_1: int = 97201
GROUP_2: int = 97202
ASSESSMENT_ID: int = 97301
ASSIGNMENT_ID: int = 97401

ALL_PERSON_IDS: list[int] = [PERSON_1, PERSON_2]
ALL_GROUP_IDS: list[int] = [GROUP_1, GROUP_2]

PERSON_REF: str = 'PERSON'
GROUP_REF: str = 'PERSON_GROUP'


class _Side(NamedTuple):
    """One of the two mirrored route files"""
    url: str
    collection: str
    counterpart_collection: str
    member_key: str
    counterpart_key: str
    entity: int
    other_entity: int
    counterpart: int
    other_counterpart: int
    manager_class: type
    counterpart_pull: str
    residue_message: str
    payload: Callable[[int, list[int]], dict[str, Any]]


def _person_payload(public_id: int, groups: list[int]) -> dict[str, Any]:
    """A CmdbPerson body"""
    return {'public_id': public_id, 'display_name': f'Person {public_id}', 'first_name': 'First',
            'last_name': 'Last', 'phone_number': '', 'email': '', 'groups': groups}


def _group_payload(public_id: int, members: list[int]) -> dict[str, Any]:
    """A CmdbPersonGroup body"""
    return {'public_id': public_id, 'name': f'Group {public_id}', 'email': '', 'group_members': members}


PERSON_SIDE = _Side('/persons', CmdbPerson.COLLECTION, CmdbPersonGroup.COLLECTION, PersonKey.GROUPS.value,
                    PersonGroupKey.GROUP_MEMBERS.value, PERSON_1, PERSON_2, GROUP_1, GROUP_2, PersonsManager,
                    'remove_person_from_person_groups', PERSON_WRITE_RESIDUE, _person_payload)
GROUP_SIDE = _Side('/person_groups', CmdbPersonGroup.COLLECTION, CmdbPerson.COLLECTION,
                   PersonGroupKey.GROUP_MEMBERS.value, PersonKey.GROUPS.value, GROUP_1, GROUP_2, PERSON_1, PERSON_2,
                   PersonGroupsManager, 'remove_person_group_from_persons', PERSON_GROUP_WRITE_RESIDUE,
                   _group_payload)
SIDES: list[_Side] = [PERSON_SIDE, GROUP_SIDE]
SIDE_IDS: list[str] = ['persons', 'person_groups']


@pytest.fixture(autouse=True)
def _enable_isms_feature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stubs the license check so the ISMS-gated routes are reachable."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the four collections, and removes every test document (including created ones) around each test."""
    by_name = {name: database_manager.get_collection(name, database_name) for name in (
        CmdbPerson.COLLECTION, CmdbPersonGroup.COLLECTION, IsmsRiskAssessment.COLLECTION,
        IsmsControlMeasureAssignment.COLLECTION)}

    def _purge() -> None:
        by_name[CmdbPerson.COLLECTION].delete_many({'display_name': {'$regex': '^Person '}})
        by_name[CmdbPersonGroup.COLLECTION].delete_many({'name': {'$regex': '^Group '}})
        by_name[IsmsRiskAssessment.COLLECTION].delete_many({'public_id': ASSESSMENT_ID})
        by_name[IsmsControlMeasureAssignment.COLLECTION].delete_many({'public_id': ASSIGNMENT_ID})

    _purge()
    by_name[CmdbPerson.COLLECTION].insert_many([_person_payload(PERSON_1, [GROUP_1]), _person_payload(PERSON_2, [])])
    by_name[CmdbPersonGroup.COLLECTION].insert_many([_group_payload(GROUP_1, [PERSON_1]),
                                                     _group_payload(GROUP_2, [])])
    by_name[IsmsRiskAssessment.COLLECTION].insert_one({
        'public_id': ASSESSMENT_ID,
        'risk_assessor_id': PERSON_1,
        'interviewed_persons': [PERSON_1, PERSON_2],
        'risk_owner_id': PERSON_1, 'risk_owner_id_ref_type': PERSON_REF,
        'auditor_id': GROUP_1, 'auditor_id_ref_type': GROUP_REF,
    })
    by_name[IsmsControlMeasureAssignment.COLLECTION].insert_one({
        'public_id': ASSIGNMENT_ID,
        'responsible_for_implementation_id': GROUP_1,
        'responsible_for_implementation_id_ref_type': GROUP_REF,
    })
    yield by_name
    _purge()


def _snapshot(collections: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Every test document of the four collections, without Mongo's _id."""
    return {
        name: sorted(({k: v for k, v in doc.items() if k != '_id'} for doc in collection.find(
            {'public_id': {'$in': ALL_PERSON_IDS + ALL_GROUP_IDS + [ASSESSMENT_ID, ASSIGNMENT_ID]}})),
            key=lambda doc: doc['public_id'])
        for name, collection in collections.items()
    } | {'counts': [collections[CmdbPerson.COLLECTION].count_documents({}),
                    collections[CmdbPersonGroup.COLLECTION].count_documents({})]}


def _raiser(error: Exception) -> Callable[..., Any]:
    """A replacement that always raises the given error."""
    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise error

    return _raise


def _applied_then_raising(real: Callable[..., Any]) -> Callable[..., Any]:
    """A write that lands and then reports a failure: a partly applied bulk write, or a lost acknowledgement."""
    def _write(*args: Any, **kwargs: Any) -> None:
        real(*args, **kwargs)
        raise RuntimeError('acknowledgement lost')

    return _write


def _failing_once(real: Callable[..., Any]) -> Callable[..., Any]:
    """A write whose first call fails before changing anything; the undo's own calls go through."""
    calls: dict[str, int] = {'count': 0}

    def _write(*args: Any, **kwargs: Any) -> None:
        calls['count'] += 1
        if calls['count'] == 1:
            raise RuntimeError('down')
        real(*args, **kwargs)

    return _write


def _listing(collections: dict[str, Any], collection: str, public_id: int, key: str) -> list[int]:
    """The stored membership array of one document."""
    return collections[collection].find_one({'public_id': public_id})[key]


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestCreateIsAllOrNothing:
    """POST with a selection: the new entity and the counterparts' membership go in together or not at all."""

    def test_a_failed_reciprocal_add_removes_the_created_entity(self, rest_api, monkeypatch, collections,
                                                                side: _Side) -> None:
        """No entity listing counterparts that do not list it back - and nothing a retry would duplicate."""
        before = _snapshot(collections)
        monkeypatch.setattr(person_membership_helper, 'add_member_to_documents', _raiser(RuntimeError('down')))

        response = rest_api.post(f'{side.url}/', json=side.payload(0, [side.counterpart]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_applied_add_that_reported_failure_is_pulled_again(self, rest_api, monkeypatch, collections,
                                                                  side: _Side) -> None:
        """The counterparts did take the new id: the recorded inverse pulls it out of them."""
        before = _snapshot(collections)
        real_add = person_membership_helper.add_member_to_documents
        monkeypatch.setattr(person_membership_helper, 'add_member_to_documents', _applied_then_raising(real_add))

        response = rest_api.post(f'{side.url}/', json=side.payload(0, [side.counterpart, side.other_counterpart]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_the_ordinary_create_writes_both_sides(self, rest_api, collections, side: _Side) -> None:
        """The baseline the failures are measured against."""
        response = rest_api.post(f'{side.url}/', json=side.payload(0, [side.other_counterpart]))
        new_id = response.get_json()['result_id']

        assert response.status_code == HTTPStatus.CREATED
        assert _listing(collections, side.counterpart_collection, side.other_counterpart,
                        side.counterpart_key) == [new_id]


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestUpdateIsAllOrNothing:
    """PUT moving the entity from one counterpart to the other: the add and the pull are both undone."""

    def test_a_failed_pull_undoes_the_add_and_the_entity(self, rest_api, monkeypatch, collections,
                                                         side: _Side) -> None:
        """The add to the new counterpart had landed; the pull from the old one failed."""
        before = _snapshot(collections)
        real_pull = person_membership_helper.remove_member_from_documents
        monkeypatch.setattr(person_membership_helper, 'remove_member_from_documents', _failing_once(real_pull))

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.other_counterpart]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_an_applied_pull_that_reported_failure_is_re_added(self, rest_api, monkeypatch, collections,
                                                               side: _Side) -> None:
        """The pull did land: the recorded inverse puts the entity back into the old counterpart."""
        before = _snapshot(collections)
        real_pull = person_membership_helper.remove_member_from_documents
        monkeypatch.setattr(person_membership_helper, 'remove_member_from_documents',
                            _applied_then_raising(real_pull))

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.other_counterpart]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_failed_add_restores_the_entity(self, rest_api, monkeypatch, collections, side: _Side) -> None:
        """The entity was already written when the add failed: it is back to its snapshot."""
        before = _snapshot(collections)
        monkeypatch.setattr(person_membership_helper, 'add_member_to_documents', _raiser(RuntimeError('down')))

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.other_counterpart]))

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert _snapshot(collections) == before

    def test_a_pull_whose_inverse_also_fails_is_named(self, rest_api, monkeypatch, collections,
                                                      side: _Side) -> None:
        """
        The pull landed and failed; adding the entity back fails too. The add to the new counterpart IS taken
        back - its own step - and the 500 names the pull, the one write left in effect
        """
        real_pull = person_membership_helper.remove_member_from_documents
        real_add = person_membership_helper.add_member_to_documents
        calls: dict[str, int] = {'count': 0}

        def _add_once(*args: Any, **kwargs: Any) -> None:
            calls['count'] += 1
            if calls['count'] > 1:
                raise RuntimeError('re-add failed')
            real_add(*args, **kwargs)

        monkeypatch.setattr(person_membership_helper, 'remove_member_from_documents',
                            _applied_then_raising(real_pull))
        monkeypatch.setattr(person_membership_helper, 'add_member_to_documents', _add_once)

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.other_counterpart]))
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert f'pulled from the {side.counterpart_key!r} of [{side.counterpart}]' in message
        assert 'added to' not in message
        assert not _listing(collections, side.counterpart_collection, side.other_counterpart, side.counterpart_key)

    def test_an_undo_that_cannot_finish_names_what_is_left(self, rest_api, monkeypatch, collections,
                                                           side: _Side) -> None:
        """The add fails and the entity cannot be restored: the 500 names the entity's collection and id."""
        monkeypatch.setattr(person_membership_helper, 'add_member_to_documents', _raiser(RuntimeError('down')))
        monkeypatch.setattr(side.manager_class, 'replace', _raiser(RuntimeError('restore failed')))

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.other_counterpart]))
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(side.residue_message.split('{', maxsplit=1)[0])
        assert side.collection in message
        assert f"'public_id': {side.entity}" in message


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestUpdateRepairsAOneSidedMembership:
    """The reciprocal write compares with what the other side stores, so a save repairs an earlier drift."""

    def test_a_counterpart_listing_an_unselected_entity_is_pulled(self, rest_api, collections,
                                                                  side: _Side) -> None:
        """The other counterpart lists the other entity, whose own list is empty; saving it empty pulls it."""
        collections[side.counterpart_collection].update_one({'public_id': side.other_counterpart},
                                                            {'$set': {side.counterpart_key: [side.other_entity]}})

        response = rest_api.put(f'{side.url}/{side.other_entity}', json=side.payload(side.other_entity, []))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert not _listing(collections, side.counterpart_collection, side.other_counterpart, side.counterpart_key)

    def test_a_selected_counterpart_missing_the_entity_gets_it(self, rest_api, collections, side: _Side) -> None:
        """The entity lists the counterpart, the counterpart lost it; saving the same selection re-adds it."""
        collections[side.counterpart_collection].update_one({'public_id': side.counterpart},
                                                            {'$set': {side.counterpart_key: []}})

        response = rest_api.put(f'{side.url}/{side.entity}', json=side.payload(side.entity, [side.counterpart]))

        assert response.status_code == HTTPStatus.ACCEPTED
        assert _listing(collections, side.counterpart_collection, side.counterpart,
                        side.counterpart_key) == [side.entity]


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestDeleteIsAllOrNothing:
    """The cascade clears ISMS references and the membership before the document goes: all of it comes back."""

    def test_a_failed_membership_pull_restores_the_isms_references(self, rest_api, monkeypatch, collections,
                                                                   side: _Side) -> None:
        """The references were already cleared when the pull failed: the entity still exists, and so do they."""
        before = _snapshot(collections)
        monkeypatch.setattr(side.manager_class, side.counterpart_pull, _raiser(RuntimeError('down')))

        response = rest_api.delete(f'{side.url}/{side.entity}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(collections) == before

    def test_a_failed_document_delete_restores_everything(self, rest_api, monkeypatch, collections,
                                                          side: _Side) -> None:
        """Every cascade step had run: references, membership and the entity are as before."""
        before = _snapshot(collections)
        monkeypatch.setattr(side.manager_class, 'delete_item', _raiser(RuntimeError('down')))

        response = rest_api.delete(f'{side.url}/{side.entity}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(collections) == before

    def test_an_applied_delete_that_reported_failure_is_re_inserted(self, rest_api, monkeypatch, collections,
                                                                    side: _Side) -> None:
        """The document did go: the undo re-inserts it under its old id."""
        before = _snapshot(collections)
        real_delete = side.manager_class.delete_item
        monkeypatch.setattr(side.manager_class, 'delete_item', _applied_then_raising(real_delete))

        response = rest_api.delete(f'{side.url}/{side.entity}')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _snapshot(collections) == before

    def test_the_ordinary_delete_still_clears_everything(self, rest_api, collections, side: _Side) -> None:
        """The baseline: the entity is gone and nothing still lists it."""
        response = rest_api.delete(f'{side.url}/{side.entity}')

        assert response.status_code == HTTPStatus.ACCEPTED
        assert collections[side.collection].find_one({'public_id': side.entity}) is None
        assert not _listing(collections, side.counterpart_collection, side.counterpart, side.counterpart_key)

    def test_an_undo_that_cannot_finish_names_the_assessment(self, rest_api, monkeypatch, collections,
                                                             side: _Side) -> None:
        """The delete fails and the assessment cannot be restored: the 500 names it."""
        monkeypatch.setattr(side.manager_class, 'delete_item', _raiser(RuntimeError('down')))
        monkeypatch.setattr(RiskAssessmentManager, 'replace', _raiser(RuntimeError('restore failed')))

        response = rest_api.delete(f'{side.url}/{side.entity}')
        message: str = response.get_json()['message']

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert message.startswith(side.residue_message.split('{', maxsplit=1)[0])
        assert IsmsRiskAssessment.COLLECTION in message
        assert f"'public_id': {ASSESSMENT_ID}" in message
