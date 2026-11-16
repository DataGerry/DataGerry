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
  - **an id must be an object of the marker its ref_type names**, so a group object sent as a PERSON is refused - the
    mismatch the delete clean-up would otherwise never clean - and the writer must READ it (403, after every 400)
  - the lookup is grouped: at most one query per marker, none for an empty selection
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
from cmdb.errors.manager import BaseManagerGetError
from cmdb.interface.rest_api.routes.isms_routes import isms_person_reference_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_person_reference_helper import (
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
PERSON_TYPE: int = 3
GROUP_TYPE: int = 4

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


def _objects(stored: dict[int, tuple[str | None, int]]) -> MagicMock:
    """An objects manager whose find answers the stored objects of the asked marker among the asked ids"""
    manager: MagicMock = MagicMock()

    def _find(criteria: dict[str, Any], projection: Any = None) -> list[dict[str, Any]]:
        del projection
        return [{'public_id': object_id, 'type_id': type_id} for object_id, (marker, type_id) in stored.items()
                if object_id in criteria['public_id']['$in'] and marker == criteria['special_type']]

    manager.find.side_effect = _find

    return manager


def _hidden(*type_ids: int) -> Any:
    """The writer's denied Types, as the lazy call the check takes"""
    return lambda: frozenset(type_ids)


def _markers_asked(manager: MagicMock) -> list[str]:
    """The marker of every read, in order"""
    return [entry.args[0]['special_type'] for entry in manager.find.call_args_list]


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
    """Each id must be an object of the marker its reference type names, readable by the writer"""

    def test_passes_when_every_reference_resolves(self, flask_app: Flask) -> None:
        """Persons among the person objects, groups among the group objects - one read per marker"""
        manager = _objects({OWNER_ID: (PERSON, PERSON_TYPE), RESPONSIBLE_ID: (PERSON_GROUP, GROUP_TYPE)})
        references = [
            PersonReference(OWNER_KEY, OWNER_ID, PERSON),
            PersonReference(RESPONSIBLE_KEY, RESPONSIBLE_ID, PERSON_GROUP),
        ]

        with flask_app.app_context():
            abort_on_unknown_person_references(references, manager, _hidden())

        assert _markers_asked(manager) == [PERSON, PERSON_GROUP]

    def test_an_unknown_person_is_refused_and_named(self, flask_app: Flask) -> None:
        """The message names the id and what it was supposed to be"""
        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, UNKNOWN_ID, PERSON)], _objects({}), _hidden(),
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert f'{PERSON_LABEL} ID(s)' in caught.value.description
        assert str(UNKNOWN_ID) in caught.value.description

    def test_an_unknown_group_is_refused_and_named(self, flask_app: Flask) -> None:
        """The group half answers with the group label"""
        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(RESPONSIBLE_KEY, UNKNOWN_ID, PERSON_GROUP)], _objects({}), _hidden(),
            )

        assert f'{PERSON_GROUP_LABEL} ID(s)' in caught.value.description

    def test_a_group_object_sent_as_a_person_is_refused(self, flask_app: Flask) -> None:
        """The mismatched pair: the object exists, but does not carry the marker the ref_type names"""
        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, SHARED_ID, PERSON)], _objects({SHARED_ID: (PERSON_GROUP, GROUP_TYPE)}),
                _hidden(),
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST

    def test_an_ordinary_object_is_no_person(self, flask_app: Flask) -> None:
        """An object of a Type without the marker is refused like a missing one"""
        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, SHARED_ID, PERSON)], _objects({SHARED_ID: (None, 3)}), _hidden(),
            )

        assert caught.value.code == HTTPStatus.BAD_REQUEST

    def test_a_person_the_writer_may_not_read_is_forbidden(self, flask_app: Flask) -> None:
        """403 naming the id - only after every reference resolved"""
        manager = _objects({OWNER_ID: (PERSON, PERSON_TYPE)})

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(
                [PersonReference(OWNER_KEY, OWNER_ID, PERSON)], manager, _hidden(PERSON_TYPE),
            )

        assert caught.value.code == HTTPStatus.FORBIDDEN
        assert str(OWNER_ID) in caught.value.description

    def test_an_unknown_id_is_refused_before_an_unreadable_one(self, flask_app: Flask) -> None:
        """A 403 never tells an existing id from a missing one: the 400 comes first"""
        manager = _objects({OWNER_ID: (PERSON, PERSON_TYPE)})
        references = [PersonReference(OWNER_KEY, OWNER_ID, PERSON),
                      PersonReference(RESPONSIBLE_KEY, UNKNOWN_ID, PERSON_GROUP)]

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references(references, manager, _hidden(PERSON_TYPE))

        assert caught.value.code == HTTPStatus.BAD_REQUEST

    @pytest.mark.parametrize('reference_type', [UNKNOWN_REFERENCE_TYPE, None, [PERSON]])
    def test_an_unknown_reference_type_is_refused_before_any_lookup(
            self, flask_app: Flask, reference_type: Any) -> None:
        """A ref_type naming neither marker could never be cleaned by a delete"""
        manager = _objects({OWNER_ID: (PERSON, PERSON_TYPE)})

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references([PersonReference(OWNER_KEY, OWNER_ID, reference_type)], manager,
                                               _hidden())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert OWNER_KEY in caught.value.description
        manager.find.assert_not_called()

    @pytest.mark.parametrize('public_id', [NOT_A_PUBLIC_ID, True, {'id': OWNER_ID}, 1.5])
    def test_a_value_that_is_not_a_public_id_is_refused(self, flask_app: Flask, public_id: Any) -> None:
        """Strings, bools, dicts and floats are never sent to the lookup"""
        manager = _objects({OWNER_ID: (PERSON, PERSON_TYPE)})

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            abort_on_unknown_person_references([PersonReference(OWNER_KEY, public_id, PERSON)], manager, _hidden())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
        assert OWNER_KEY in caught.value.description
        manager.find.assert_not_called()

    def test_one_query_per_marker_however_many_keys(self, flask_app: Flask) -> None:
        """Every person key is resolved in the same query"""
        manager = _objects({object_id: (PERSON, PERSON_TYPE) for object_id in (OWNER_ID, AUDITOR_ID, ASSESSOR_ID)})
        references = [
            PersonReference(OWNER_KEY, OWNER_ID, PERSON),
            PersonReference(AUDITOR_KEY, AUDITOR_ID, PERSON),
            PersonReference(ASSESSOR_KEY, ASSESSOR_ID, PERSON),
        ]

        with flask_app.app_context():
            abort_on_unknown_person_references(references, manager, _hidden())

        assert _markers_asked(manager) == [PERSON]

    def test_nothing_is_queried_for_no_references(self, flask_app: Flask) -> None:
        """A document referencing nobody costs no query"""
        manager = _objects({})

        with flask_app.app_context():
            abort_on_unknown_person_references([], manager, _hidden())

        manager.find.assert_not_called()


class TestCheckPersonReferences:
    """The check bound to the request user's tenant and READ ACL"""

    def test_builds_no_manager_for_no_references(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing to resolve, nothing constructed"""
        get_manager = MagicMock()
        monkeypatch.setattr(isms_person_reference_helper.ManagerProvider, 'get_manager', get_manager)

        check_person_references([], MagicMock())

        get_manager.assert_not_called()

    def test_resolves_with_the_tenant_objects_and_the_writers_hidden_types(
            self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The objects manager of the request user and its denied Types are handed to the check"""
        manager = _objects({})
        request_user = MagicMock()
        hidden = _hidden()
        monkeypatch.setattr(isms_person_reference_helper.ManagerProvider, 'get_manager',
                            lambda manager_type, user: manager if (manager_type, user) == (
                                ManagerType.OBJECTS, request_user) else None)
        monkeypatch.setattr(isms_person_reference_helper, 'hidden_types_of',
                            lambda user: hidden if user is request_user else None)
        resolved = MagicMock()
        monkeypatch.setattr(isms_person_reference_helper, 'abort_on_unknown_person_references', resolved)
        references = [PersonReference(OWNER_KEY, OWNER_ID, PERSON)]

        check_person_references(references, request_user)

        resolved.assert_called_once_with(references, manager, hidden)

    def test_a_failed_lookup_is_a_400(self, flask_app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
        """Logged, answered with the lookup message"""
        monkeypatch.setattr(isms_person_reference_helper.ManagerProvider, 'get_manager', lambda *_args: MagicMock())
        monkeypatch.setattr(isms_person_reference_helper, 'hidden_types_of', lambda _user: _hidden())
        monkeypatch.setattr(isms_person_reference_helper, 'abort_on_unknown_person_references',
                            MagicMock(side_effect=BaseManagerGetError('down')))

        with flask_app.app_context(), pytest.raises(HTTPException) as caught:
            check_person_references([PersonReference(OWNER_KEY, OWNER_ID, PERSON)], MagicMock())

        assert caught.value.code == HTTPStatus.BAD_REQUEST
