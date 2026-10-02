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
Unit tests for cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper

Pure tests: no Mongo, the managers are stubs. Pinned here is what the ISMS write routes rely on:

  - every reference key of both collections is read, a polymorphic one WITH its '_ref_type' sibling, a person-only
    one as a CmdbPerson whatever the payload says - and a null or empty key references nothing
  - an update judges only the references it introduces: a changed id, a changed ref_type, an added list entry
  - **an id is resolved in the collection its ref_type names**, so a group's id sent as a PERSON is refused even
    though a group with that id exists - the mismatch the delete cascade would otherwise never clean
  - the lookup is grouped: at most one query per collection, none for an empty selection
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.person_reference_helper import (
    CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
    RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
    ref_type_key,
)
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.isms_model.isms_control_measure_assignment_constants import ControlMeasureAssignmentKey
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.errors.manager.persons_manager import PersonsManagerGetError
from cmdb.errors.manager.person_groups_manager import PersonGroupsManagerGetError
from cmdb.interface.rest_api.routes.isms_routes import isms_person_reference_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
    PERSON_REFERENCE_LOOKUP_ERRORS,
    PersonReference,
    abort_on_unknown_person_references,
    check_person_references,
    collect_person_references,
    new_person_references,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_constants import PERSON_GROUP_LABEL, PERSON_LABEL
# -------------------------------------------------------------------------------------------------------------------- #

PERSON: str = PersonReferenceType.PERSON.value
PERSON_GROUP: str = PersonReferenceType.PERSON_GROUP.value

OWNER_KEY: str = RiskAssessmentKey.RISK_OWNER_ID.value
RESPONSIBLE_KEY: str = RiskAssessmentKey.RESPONSIBLE_PERSONS_ID.value
AUDITOR_KEY: str = RiskAssessmentKey.AUDITOR_ID.value
ASSESSOR_KEY: str = RiskAssessmentKey.RISK_ASSESSOR_ID.value
INTERVIEWED_KEY: str = RiskAssessmentKey.INTERVIEWED_PERSONS.value
IMPLEMENTER_KEY: str = ControlMeasureAssignmentKey.RESPONSIBLE_FOR_IMPLEMENTATION_ID.value

OWNER_ID: int = 11
RESPONSIBLE_ID: int = 12
AUDITOR_ID: int = 13
ASSESSOR_ID: int = 14
INTERVIEWED_IDS: list[int] = [15, 16]
IMPLEMENTER_ID: int = 17
UNKNOWN_ID: int = 99
SHARED_ID: int = 21

UNKNOWN_REFERENCE_TYPE: str = 'NOBODY'
NOT_A_PUBLIC_ID: str = 'eleven'


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app, since abort() needs an application context"""
    return Flask(__name__)


def _risk_assessment(**overrides: Any) -> dict[str, Any]:
    """A RiskAssessment payload referencing a person in every key, with distinct ids per key"""
    document: dict[str, Any] = {
        OWNER_KEY: OWNER_ID, ref_type_key(OWNER_KEY): PERSON,
        RESPONSIBLE_KEY: RESPONSIBLE_ID, ref_type_key(RESPONSIBLE_KEY): PERSON_GROUP,
        AUDITOR_KEY: AUDITOR_ID, ref_type_key(AUDITOR_KEY): PERSON,
        ASSESSOR_KEY: ASSESSOR_ID,
        INTERVIEWED_KEY: list(INTERVIEWED_IDS),
    }
    document.update(overrides)

    return document


def _managers(existing_persons: set[int], existing_groups: set[int]) -> tuple[MagicMock, MagicMock]:
    """A persons and a person-groups manager stub, each reporting the given public_ids as existing"""
    persons_manager = MagicMock()
    persons_manager.find_existing_public_ids.side_effect = lambda ids: set(ids) & existing_persons
    person_groups_manager = MagicMock()
    person_groups_manager.find_existing_public_ids.side_effect = lambda ids: set(ids) & existing_groups

    return persons_manager, person_groups_manager


class TestCollectPersonReferences:
    """Every reference a document carries, each with the collection it names"""

    def test_reads_every_risk_assessment_key_with_its_own_value(self) -> None:
        """Distinct ids per key, so a key read into another key's slot would show"""
        references = collect_person_references(_risk_assessment(), RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)

        assert references == [
            PersonReference(OWNER_KEY, OWNER_ID, PERSON),
            PersonReference(RESPONSIBLE_KEY, RESPONSIBLE_ID, PERSON_GROUP),
            PersonReference(AUDITOR_KEY, AUDITOR_ID, PERSON),
            PersonReference(ASSESSOR_KEY, ASSESSOR_ID, PERSON),
            *[PersonReference(INTERVIEWED_KEY, public_id, PERSON) for public_id in INTERVIEWED_IDS],
        ]

    def test_reads_the_assignment_key(self) -> None:
        """The one polymorphic key of an IsmsControlMeasureAssignment"""
        assignment = {IMPLEMENTER_KEY: IMPLEMENTER_ID, ref_type_key(IMPLEMENTER_KEY): PERSON_GROUP}

        assert collect_person_references(assignment, CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS) == [
            PersonReference(IMPLEMENTER_KEY, IMPLEMENTER_ID, PERSON_GROUP),
        ]

    def test_a_null_or_empty_key_references_nothing(self) -> None:
        """None in a polymorphic key, None or [] in a person-only one - whatever the ref_type says"""
        document = _risk_assessment(
            **{OWNER_KEY: None, RESPONSIBLE_KEY: None, AUDITOR_KEY: None, ASSESSOR_KEY: None, INTERVIEWED_KEY: []},
        )

        assert not collect_person_references(document, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)

    def test_a_missing_key_references_nothing(self) -> None:
        """An embedded assignment may omit the key entirely"""
        assert not collect_person_references({}, CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS)

    def test_a_person_only_key_is_always_a_person(self) -> None:
        """The assessor and the interviewed persons carry no ref_type: they can only ever be persons"""
        references = collect_person_references(
            {ASSESSOR_KEY: ASSESSOR_ID, INTERVIEWED_KEY: None},
            RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
        )

        assert references == [PersonReference(ASSESSOR_KEY, ASSESSOR_ID, PERSON)]

    def test_a_polymorphic_id_without_its_ref_type_keeps_none(self) -> None:
        """The missing half is carried as sent, for the check to refuse - never guessed"""
        references = collect_person_references({OWNER_KEY: OWNER_ID}, RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)

        assert references == [PersonReference(OWNER_KEY, OWNER_ID, None)]

    def test_an_unhashable_value_does_not_crash(self) -> None:
        """Embedded assignments are not schema-checked, so a value may be anything"""
        references = collect_person_references(
            {IMPLEMENTER_KEY: {'id': 1}, ref_type_key(IMPLEMENTER_KEY): [PERSON]},
            CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS,
        )

        assert references == [PersonReference(IMPLEMENTER_KEY, {'id': 1}, [PERSON])]


class TestNewPersonReferences:
    """An update judges the references it introduces, never the ones already stored"""

    def test_an_unchanged_document_introduces_nothing(self) -> None:
        """The frontend sends the whole document back"""
        assert not new_person_references(_risk_assessment(), _risk_assessment(), RISK_ASSESSMENT_PERSON_REFERENCE_KEYS)

    def test_a_changed_id_is_new(self) -> None:
        """Only the changed key is judged"""
        references = new_person_references(
            _risk_assessment(**{OWNER_KEY: UNKNOWN_ID}), _risk_assessment(), RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
        )

        assert references == [PersonReference(OWNER_KEY, UNKNOWN_ID, PERSON)]

    def test_a_changed_ref_type_is_new(self) -> None:
        """Same id, other collection: a different reference"""
        references = new_person_references(
            _risk_assessment(**{ref_type_key(OWNER_KEY): PERSON_GROUP}),
            _risk_assessment(),
            RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
        )

        assert references == [PersonReference(OWNER_KEY, OWNER_ID, PERSON_GROUP)]

    def test_an_added_list_entry_is_new_and_the_kept_ones_are_not(self) -> None:
        """Per entry, so one stale interviewed person does not block adding another"""
        references = new_person_references(
            _risk_assessment(**{INTERVIEWED_KEY: [*INTERVIEWED_IDS, UNKNOWN_ID]}),
            _risk_assessment(),
            RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
        )

        assert references == [PersonReference(INTERVIEWED_KEY, UNKNOWN_ID, PERSON)]

    def test_a_removed_reference_is_not_judged(self) -> None:
        """Dropping a reference needs nothing to exist"""
        assert not new_person_references(
            _risk_assessment(**{OWNER_KEY: None}), _risk_assessment(), RISK_ASSESSMENT_PERSON_REFERENCE_KEYS,
        )

    def test_against_an_empty_stored_document_everything_is_new(self) -> None:
        """A stored document missing the keys holds no reference"""
        assignment = {IMPLEMENTER_KEY: IMPLEMENTER_ID, ref_type_key(IMPLEMENTER_KEY): PERSON}

        assert new_person_references(assignment, {}, CONTROL_MEASURE_ASSIGNMENT_PERSON_REFERENCE_KEYS) == [
            PersonReference(IMPLEMENTER_KEY, IMPLEMENTER_ID, PERSON),
        ]


class TestAbortOnUnknownPersonReferences:
    """Each id is resolved in the collection its reference type names"""

    def test_passes_when_every_reference_resolves(self, flask_app: Flask) -> None:
        """Persons in the persons collection, groups in the groups collection"""
        persons_manager, person_groups_manager = _managers({OWNER_ID}, {RESPONSIBLE_ID})
        references = [
            PersonReference(OWNER_KEY, OWNER_ID, PERSON),
            PersonReference(RESPONSIBLE_KEY, RESPONSIBLE_ID, PERSON_GROUP),
        ]

        with flask_app.app_context():
            abort_on_unknown_person_references(references, persons_manager, person_groups_manager)

        persons_manager.find_existing_public_ids.assert_called_once_with([OWNER_ID])
        person_groups_manager.find_existing_public_ids.assert_called_once_with([RESPONSIBLE_ID])

    def test_an_unknown_person_is_refused_and_named(self, flask_app: Flask) -> None:
        """The message names the id and what it was supposed to be"""
        persons_manager, person_groups_manager = _managers(set(), set())

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, UNKNOWN_ID, PERSON)], persons_manager, person_groups_manager,
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert f'{PERSON_LABEL} ID(s)' in caught.value.description
        assert str(UNKNOWN_ID) in caught.value.description

    def test_an_unknown_group_is_refused_and_named(self, flask_app: Flask) -> None:
        """The group half answers with the group label"""
        persons_manager, person_groups_manager = _managers(set(), set())

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(RESPONSIBLE_KEY, UNKNOWN_ID, PERSON_GROUP)], persons_manager, person_groups_manager,
            )

        assert f'{PERSON_GROUP_LABEL} ID(s)' in caught.value.description

    def test_a_group_id_sent_as_a_person_is_refused(self, flask_app: Flask) -> None:
        """The mismatched pair: the id exists, but not in the collection the ref_type names"""
        persons_manager, person_groups_manager = _managers(set(), {SHARED_ID})

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, SHARED_ID, PERSON)], persons_manager, person_groups_manager,
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        person_groups_manager.find_existing_public_ids.assert_not_called()

    def test_a_person_id_sent_as_a_group_is_refused(self, flask_app: Flask) -> None:
        """The other direction of the mismatch"""
        persons_manager, person_groups_manager = _managers({SHARED_ID}, set())

        with flask_app.app_context(), pytest.raises(HTTPException):
            abort_on_unknown_person_references(
                [PersonReference(RESPONSIBLE_KEY, SHARED_ID, PERSON_GROUP)], persons_manager, person_groups_manager,
            )

    @pytest.mark.parametrize('reference_type', [UNKNOWN_REFERENCE_TYPE, None, [PERSON]])
    def test_an_unknown_reference_type_is_refused_before_any_lookup(
            self, flask_app: Flask, reference_type: Any) -> None:
        """A ref_type naming neither collection could never be cleaned by a delete"""
        persons_manager, person_groups_manager = _managers({OWNER_ID}, {OWNER_ID})

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, OWNER_ID, reference_type)], persons_manager, person_groups_manager,
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert OWNER_KEY in caught.value.description
        persons_manager.find_existing_public_ids.assert_not_called()

    @pytest.mark.parametrize('public_id', [NOT_A_PUBLIC_ID, True, {'id': OWNER_ID}, 1.5])
    def test_a_value_that_is_not_a_public_id_is_refused(self, flask_app: Flask, public_id: Any) -> None:
        """Strings, bools, dicts and floats are never sent to the lookup"""
        persons_manager, person_groups_manager = _managers({OWNER_ID}, set())

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, public_id, PERSON)], persons_manager, person_groups_manager,
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert OWNER_KEY in caught.value.description
        persons_manager.find_existing_public_ids.assert_not_called()

    def test_one_query_per_collection_however_many_keys(self, flask_app: Flask) -> None:
        """Every person key is resolved in the same query"""
        persons_manager, person_groups_manager = _managers({OWNER_ID, AUDITOR_ID, ASSESSOR_ID}, set())
        references = [
            PersonReference(OWNER_KEY, OWNER_ID, PERSON),
            PersonReference(AUDITOR_KEY, AUDITOR_ID, PERSON),
            PersonReference(ASSESSOR_KEY, ASSESSOR_ID, PERSON),
        ]

        with flask_app.app_context():
            abort_on_unknown_person_references(references, persons_manager, person_groups_manager)

        persons_manager.find_existing_public_ids.assert_called_once_with([OWNER_ID, AUDITOR_ID, ASSESSOR_ID])
        person_groups_manager.find_existing_public_ids.assert_not_called()

    def test_nothing_is_queried_for_no_references(self, flask_app: Flask) -> None:
        """A document referencing nobody costs no query"""
        persons_manager, person_groups_manager = _managers(set(), set())

        with flask_app.app_context():
            abort_on_unknown_person_references([], persons_manager, person_groups_manager)

        persons_manager.find_existing_public_ids.assert_not_called()
        person_groups_manager.find_existing_public_ids.assert_not_called()


class TestCheckPersonReferences:
    """The check bound to the request user's tenant"""

    def test_builds_no_manager_for_no_references(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing to resolve, nothing constructed"""
        get_manager = MagicMock()
        monkeypatch.setattr(isms_person_reference_helper.ManagerProvider, 'get_manager', get_manager)

        check_person_references([], MagicMock())

        get_manager.assert_not_called()

    def test_resolves_with_the_tenant_managers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The persons and person-groups managers of the request user are handed to the check"""
        persons_manager, person_groups_manager = _managers({OWNER_ID}, set())
        by_type = {ManagerType.PERSON: persons_manager, ManagerType.PERSON_GROUP: person_groups_manager}
        request_user = MagicMock()
        monkeypatch.setattr(isms_person_reference_helper.ManagerProvider, 'get_manager',
                            lambda manager_type, user: by_type[manager_type] if user is request_user else None)
        resolved = MagicMock()
        monkeypatch.setattr(isms_person_reference_helper, 'abort_on_unknown_person_references', resolved)
        references = [PersonReference(OWNER_KEY, OWNER_ID, PERSON)]

        check_person_references(references, request_user)

        resolved.assert_called_once_with(references, persons_manager, person_groups_manager)


def test_the_lookup_errors_are_mapped_per_collection() -> None:
    """A failed lookup of either collection is answered with a message naming that collection"""
    assert set(PERSON_REFERENCE_LOOKUP_ERRORS) == {PersonsManagerGetError, PersonGroupsManagerGetError}
    assert PERSON_LABEL in PERSON_REFERENCE_LOOKUP_ERRORS[PersonsManagerGetError]
    assert PERSON_GROUP_LABEL in PERSON_REFERENCE_LOOKUP_ERRORS[PersonGroupsManagerGetError]
