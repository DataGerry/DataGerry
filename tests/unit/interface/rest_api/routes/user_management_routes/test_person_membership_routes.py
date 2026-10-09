# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the CmdbPerson and CmdbPersonGroup routes

Each handler is unwrapped past its auth / validation decorators and driven inside a Flask
test_request_context, with the two managers it resolves through ManagerProvider returned as separate
mocks so a test can say which side was written. No Mongo, no blueprint registration.

**One module for the two route files on purpose**: they are mirror images of one another, and the
rules being pinned are the ones that must hold on both sides.

  - **the membership diff is null-safe.** ``set(document.get(key, []))`` returns None for a stored
    null, and ``set(None)`` raises inside the route's try block - reported as a 500 that named
    nothing. A database that has not run updater_20260909 can still carry that null
  - **an unknown reference is refused before anything is written**, rather than stored and then
    mirrored into no document
  - **the reciprocal write is ``sync_membership``, under the request's ledger**, with the full selection -
    not the diff against the entity's own list - so a later save repairs a one-sided membership
  - **the delete route makes exactly one cascade call**, after recording every write of it
    (``record_delete_cascade``). The reciprocal cleanup lives in the manager's cascade, so the route must not
    repeat it - and must not be the only place it happens
  - **a failure part-way is undone**: the entity write is recorded, so the undo removes a created entity and
    restores an updated one; an undo that cannot finish answers 500
  - the error tails: which manager error becomes a 400, and that anything else becomes a 500
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable, Iterator, NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.person_model import PersonKey
from cmdb.models.person_group_model import PersonGroupKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.framework.write_ledger import WriteLedger

from cmdb.errors.manager.persons_manager import (
    PersonsManagerDeleteError,
    PersonsManagerGetError,
    PersonsManagerInsertError,
    PersonsManagerIterationError,
    PersonsManagerUpdateError,
)
from cmdb.errors.manager.person_groups_manager import (
    PersonGroupsManagerDeleteError,
    PersonGroupsManagerGetError,
    PersonGroupsManagerInsertError,
    PersonGroupsManagerIterationError,
    PersonGroupsManagerUpdateError,
)
from cmdb.interface.rest_api.routes.user_management_routes.persons_routes import (
    delete_cmdb_person,
    get_cmdb_person,
    get_cmdb_persons,
    insert_cmdb_person,
    update_cmdb_person,
)
from cmdb.interface.rest_api.routes.user_management_routes.person_groups_routes import (
    delete_cmdb_person_group,
    get_cmdb_person_group,
    get_cmdb_person_groups,
    insert_cmdb_person_group,
    update_cmdb_person_group,
)
# -------------------------------------------------------------------------------------------------------------------- #

PERSONS_ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.persons_routes'
PERSON_GROUPS_ROUTE_PATH: str = (
    'cmdb.interface.rest_api.routes.user_management_routes.person_groups_routes'
)

PUBLIC_ID: int = 3
NEW_ID: int = 9

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500


class _Side(NamedTuple):
    """One of the two mirrored route files, and everything a shared test needs to address it"""
    route_path: str
    insert: Callable[..., Any]
    get_many: Callable[..., Any]
    get_one: Callable[..., Any]
    update: Callable[..., Any]
    delete: Callable[..., Any]
    own_manager_type: ManagerType
    counterpart_manager_type: ManagerType
    membership_key: str
    counterpart_key: str
    reference_type: PersonReferenceType
    payload: dict[str, Any]
    get_error: type[Exception]
    insert_error: type[Exception]
    update_error: type[Exception]
    delete_error: type[Exception]
    iteration_error: type[Exception]


PERSON_SIDE = _Side(
    PERSONS_ROUTE_PATH,
    insert_cmdb_person,
    get_cmdb_persons,
    get_cmdb_person,
    update_cmdb_person,
    delete_cmdb_person,
    ManagerType.PERSON,
    ManagerType.PERSON_GROUP,
    PersonKey.GROUPS.value,
    PersonGroupKey.GROUP_MEMBERS.value,
    PersonReferenceType.PERSON,
    {
        PersonKey.DISPLAY_NAME.value: 'Ada Lovelace',
        PersonKey.FIRST_NAME.value: 'Ada',
        PersonKey.LAST_NAME.value: 'Lovelace',
    },
    PersonsManagerGetError,
    PersonsManagerInsertError,
    PersonsManagerUpdateError,
    PersonsManagerDeleteError,
    PersonsManagerIterationError,
)

PERSON_GROUP_SIDE = _Side(
    PERSON_GROUPS_ROUTE_PATH,
    insert_cmdb_person_group,
    get_cmdb_person_groups,
    get_cmdb_person_group,
    update_cmdb_person_group,
    delete_cmdb_person_group,
    ManagerType.PERSON_GROUP,
    ManagerType.PERSON,
    PersonGroupKey.GROUP_MEMBERS.value,
    PersonKey.GROUPS.value,
    PersonReferenceType.PERSON_GROUP,
    {PersonGroupKey.NAME.value: 'Security officers', PersonGroupKey.EMAIL.value: ''},
    PersonGroupsManagerGetError,
    PersonGroupsManagerInsertError,
    PersonGroupsManagerUpdateError,
    PersonGroupsManagerDeleteError,
    PersonGroupsManagerIterationError,
)

SIDES: list[_Side] = [PERSON_SIDE, PERSON_GROUP_SIDE]
SIDE_IDS: list[str] = ['persons_routes', 'person_groups_routes']


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / validate / protect / verify / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


class _Managers(NamedTuple):
    """The managers a route resolves and the two ledger helpers it calls, kept apart per role"""
    own: MagicMock
    counterpart: MagicMock
    risk_assessments: MagicMock
    assignments: MagicMock
    sync: MagicMock
    cascade: MagicMock


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


def _patched_managers(side: _Side) -> tuple[Any, _Managers]:
    """
    Patches ManagerProvider.get_manager so each ManagerType returns its own mock, and the two ledger helpers

    ``sync_membership`` and ``record_delete_cascade`` have their own unit tests; here they are mocks, so a test
    says what the route hands them. The entity's own ``get_one_by`` answers what ``get_item`` answers, so the
    undo of a recorded update verifies clean unless a test says otherwise

    Args:
        side (_Side): The route file under test

    Returns:
        tuple[Any, _Managers]: A context manager applying the patches, and the mocks it installs
    """
    managers = _Managers(MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock())
    managers.own.get_one_by.side_effect = lambda _criteria: managers.own.get_item.return_value
    by_type: dict[ManagerType, MagicMock] = {
        side.own_manager_type: managers.own,
        side.counterpart_manager_type: managers.counterpart,
        ManagerType.RISK_ASSESSMENT: managers.risk_assessments,
        ManagerType.CONTROL_MEASURE_ASSIGNMENT: managers.assignments,
    }

    @contextmanager
    def patcher() -> Iterator[None]:
        with patch(f'{side.route_path}.ManagerProvider.get_manager',
                   side_effect=lambda manager_type, _user: by_type[manager_type]), \
                patch(f'{side.route_path}.sync_membership', managers.sync), \
                patch(f'{side.route_path}.record_delete_cascade', managers.cascade):
            yield

    return patcher(), managers


def _payload(side: _Side, **overrides: Any) -> dict[str, Any]:
    """Builds a valid write payload for the side, with the given keys replaced"""
    return {**side.payload, **overrides}


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestUnknownReferencesAreRefused:
    """The guard that keeps the two sides of a membership from disagreeing."""

    def test_insert_refuses_a_membership_naming_something_that_does_not_exist(
        self, side: _Side, flask_app: Flask,
    ) -> None:
        """
        400 before the write, rather than a stored id nothing mirrors

        The reciprocal '$addToSet' silently matches no document for an unknown id, so the two sides
        would disagree from that moment with nothing in the response to say so.
        """
        patcher, managers = _patched_managers(side)
        managers.counterpart.find_existing_public_ids.return_value = set()

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(
                    data=_payload(side, **{side.membership_key: [404]}),
                    request_user=SimpleNamespace(public_id=1),
                )

        assert caught.value.code == HTTP_BAD_REQUEST
        managers.own.insert_item.assert_not_called()

    def test_insert_accepts_a_membership_that_exists(self, side: _Side, flask_app: Flask) -> None:
        """The happy path still mirrors the membership into the counterpart collection."""
        patcher, managers = _patched_managers(side)
        managers.counterpart.find_existing_public_ids.return_value = {5}
        managers.own.insert_item.return_value = NEW_ID
        managers.own.get_item.return_value = {'public_id': NEW_ID}

        with patcher, flask_app.test_request_context('/', method='POST'):
            _unwrap(side.insert)(
                data=_payload(side, **{side.membership_key: [5]}),
                request_user=SimpleNamespace(public_id=1),
            )

        ledger, counterpart, key, member_id, selected = managers.sync.call_args.args

        assert isinstance(ledger, WriteLedger)
        assert (counterpart, key, member_id, selected) == (managers.counterpart, side.counterpart_key, NEW_ID, [5])

    def test_update_only_checks_the_memberships_being_added(
        self, side: _Side, flask_app: Flask,
    ) -> None:
        """
        Removing a membership must keep working even if its target is already gone

        Checking the whole list instead would make a group deleted behind the client's back
        un-removable from the person still listing it.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: [1, 2]}
        managers.counterpart.find_existing_public_ids.return_value = {3}

        with patcher, flask_app.test_request_context('/', method='PUT'):
            _unwrap(side.update)(
                public_id=PUBLIC_ID,
                data=_payload(side, **{side.membership_key: [1, 3]}),
                request_user=SimpleNamespace(public_id=1),
            )

        assert set(managers.counterpart.find_existing_public_ids.call_args.args[0]) == {3}


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestMembershipDiff:
    """What the update route computes, including from a document that stores a null membership."""

    def test_a_stored_null_membership_is_read_as_empty(self, side: _Side, flask_app: Flask) -> None:
        """
        A stored null is not a 500: set(None) would raise inside the route's try block

        A database that has not run updater_20260909 can still carry the null, so the route stays
        defensive rather than trusting the migration alone.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: None}
        managers.counterpart.find_existing_public_ids.return_value = {4}

        with patcher, flask_app.test_request_context('/', method='PUT'):
            _unwrap(side.update)(
                public_id=PUBLIC_ID,
                data=_payload(side, **{side.membership_key: [4]}),
                request_user=SimpleNamespace(public_id=1),
            )

        assert managers.sync.call_args.args[1:] == (managers.counterpart, side.counterpart_key, PUBLIC_ID, {4})

    def test_a_null_in_the_payload_is_read_as_empty(self, side: _Side, flask_app: Flask) -> None:
        """The schemas accept null for the membership key, so the route has to as well."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: [1]}

        with patcher, flask_app.test_request_context('/', method='PUT'):
            _unwrap(side.update)(
                public_id=PUBLIC_ID,
                data=_payload(side, **{side.membership_key: None}),
                request_user=SimpleNamespace(public_id=1),
            )

        assert managers.sync.call_args.args[1:] == (managers.counterpart, side.counterpart_key, PUBLIC_ID, set())

    def test_the_whole_selection_is_synced_not_the_diff(self, side: _Side, flask_app: Flask) -> None:
        """
        A counterpart the entity already listed is handed over too

        The sync compares against what the other side stores, so a membership an earlier failure left
        one-sided is repaired by the next save - which needs the full selection, not the diff against the
        entity's own list.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: [1, 2]}
        managers.counterpart.find_existing_public_ids.return_value = {3}

        with patcher, flask_app.test_request_context('/', method='PUT'):
            _unwrap(side.update)(
                public_id=PUBLIC_ID,
                data=_payload(side, **{side.membership_key: [1, 3]}),
                request_user=SimpleNamespace(public_id=1),
            )

        assert managers.sync.call_args.args[4] == {1, 3}

    def test_the_public_id_of_the_url_wins_over_the_body(self, side: _Side, flask_app: Flask) -> None:
        """A forged body public_id must not be able to rewrite another document's identity."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: []}

        with patcher, flask_app.test_request_context('/', method='PUT'):
            _unwrap(side.update)(
                public_id=PUBLIC_ID,
                data=_payload(side, public_id=9999),
                request_user=SimpleNamespace(public_id=1),
            )

        written = managers.own.update_item.call_args.args[1]

        assert written.get_public_id() == PUBLIC_ID

    def test_the_membership_is_synced_only_after_the_document_is_written(
        self, side: _Side, flask_app: Flask,
    ) -> None:
        """A failed write must not leave the counterpart collection carrying the new membership."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: []}
        managers.own.update_item.side_effect = side.update_error('nope')

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException):
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side, **{side.membership_key: []}),
                    request_user=SimpleNamespace(public_id=1),
                )

        managers.sync.assert_not_called()


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestDeleteIsOneManagerCall:
    """The cascade belongs to the manager, and the route must not own half of it."""

    def test_delegates_the_whole_cascade(self, side: _Side, flask_app: Flask) -> None:
        """
        delete_with_follow_up removes the entity from the counterpart collection itself

        Were that second call made by the route, deleting through any other path would leave the
        membership behind.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID}

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        managers.own.delete_with_follow_up.assert_called_once_with(PUBLIC_ID)

    def test_the_cascade_is_recorded_before_it_runs(self, side: _Side, flask_app: Flask) -> None:
        """
        record_delete_cascade gets the snapshot and every manager the cascade writes through, first

        Recorded after the cascade, a failure part-way would leave nothing in the ledger to undo.
        """
        patcher, managers = _patched_managers(side)
        snapshot = {'public_id': PUBLIC_ID}
        managers.own.get_item.return_value = snapshot
        order = MagicMock()
        order.attach_mock(managers.cascade, 'cascade')
        order.attach_mock(managers.own.delete_with_follow_up, 'delete')

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert [call[0] for call in order.mock_calls] == ['cascade', 'delete']
        assert managers.cascade.call_args.args[1:] == (
            managers.own,
            managers.counterpart,
            side.counterpart_key,
            snapshot,
            side.reference_type,
            (managers.risk_assessments, managers.assignments),
        )

    def test_does_not_repeat_the_reciprocal_cleanup(self, side: _Side, flask_app: Flask) -> None:
        """Doing it twice is harmless but hides where the responsibility lives."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID}

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        managers.counterpart.assert_not_called()
        assert not managers.counterpart.method_calls

    def test_a_missing_entity_is_a_404(self, side: _Side, flask_app: Flask) -> None:
        """Nothing is deleted and nothing is cascaded for an id that does not exist."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = None

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND
        managers.own.delete_with_follow_up.assert_not_called()


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestErrorMapping:
    """Which failure becomes which status, on both sides."""

    def test_an_insert_failure_is_a_400(self, side: _Side, flask_app: Flask) -> None:
        """A rejected write is the client's problem to fix, not an internal error."""
        patcher, managers = _patched_managers(side)
        managers.own.insert_item.side_effect = side.insert_error('nope')

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(data=_payload(side), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unreadable_created_document_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """
        The write landed but the read back found nothing: the server failing to see its own write

        Not a 404 - the client asked for no id, so there is no missing resource of theirs to report.
        """
        patcher, managers = _patched_managers(side)
        managers.own.insert_item.return_value = NEW_ID
        managers.own.get_item.return_value = None

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(data=_payload(side), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_an_unexpected_insert_error_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """Anything the route does not map is an internal error, and is logged as one."""
        patcher, managers = _patched_managers(side)
        managers.own.insert_item.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(data=_payload(side), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_a_failing_list_read_is_a_400(self, side: _Side, flask_app: Flask) -> None:
        """The iteration error is the one the collection route maps."""
        patcher, managers = _patched_managers(side)
        managers.own.iterate_items.side_effect = side.iteration_error('nope')

        with patcher, flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.get_many)(params=MagicMock(), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_list_error_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """The generic tail of the collection route."""
        patcher, managers = _patched_managers(side)
        managers.own.iterate_items.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.get_many)(params=MagicMock(), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_a_missing_single_document_is_a_404(self, side: _Side, flask_app: Flask) -> None:
        """The read route's own abort, which must not be swallowed by its except arms."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = None

        with patcher, flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.get_one)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND

    def test_a_failing_single_read_is_a_400(self, side: _Side, flask_app: Flask) -> None:
        """A get error names the id it could not read."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.side_effect = side.get_error('nope')

        with patcher, flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.get_one)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_single_read_error_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """The generic tail of the single-read route."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.get_one)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_a_failing_update_read_is_a_400(self, side: _Side, flask_app: Flask) -> None:
        """The update route reads before it writes, and maps that read's failure separately."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.side_effect = side.get_error('nope')

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side),
                    request_user=SimpleNamespace(public_id=1),
                )

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_a_missing_document_on_update_is_a_404(self, side: _Side, flask_app: Flask) -> None:
        """Updating something that does not exist is not a create."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = None

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side),
                    request_user=SimpleNamespace(public_id=1),
                )

        assert caught.value.code == HTTP_NOT_FOUND

    def test_an_unexpected_update_error_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """The generic tail of the update route."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: []}
        managers.own.update_item.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side),
                    request_user=SimpleNamespace(public_id=1),
                )

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_a_failing_delete_is_a_400(self, side: _Side, flask_app: Flask) -> None:
        """
        The cascade's own error, which reaches the route only because the manager wraps it

        Unwrapped, a raw pymongo error would make the route answer 500 for a failure its ObjectGroup
        twin reports as a 400.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID}
        managers.own.delete_with_follow_up.side_effect = side.delete_error('nope')

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_delete_error_is_a_500(self, side: _Side, flask_app: Flask) -> None:
        """The generic tail of the delete route."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID}
        managers.own.delete_with_follow_up.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestAFailurePartWayIsUndone:
    """The entity write is recorded in the ledger, so a failing reciprocal write takes it back."""

    def test_a_failed_sync_removes_the_created_entity(self, side: _Side, flask_app: Flask) -> None:
        """The insert is undone, and the request fails with the error it hit."""
        patcher, managers = _patched_managers(side)
        managers.own.insert_item.return_value = NEW_ID
        managers.own.find.return_value = []
        managers.sync.side_effect = side.update_error('nope')

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(data=_payload(side), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR
        managers.own.delete_many.assert_called_once_with({'public_id': {'$in': [NEW_ID]}})

    def test_a_failed_sync_restores_the_updated_entity(self, side: _Side, flask_app: Flask) -> None:
        """The update is undone from the snapshot read before it."""
        patcher, managers = _patched_managers(side)
        snapshot = {'public_id': PUBLIC_ID, side.membership_key: []}
        managers.own.get_item.return_value = snapshot
        managers.sync.side_effect = RuntimeError('boom')

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException):
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side),
                    request_user=SimpleNamespace(public_id=1),
                )

        managers.own.replace.assert_called_once_with(PUBLIC_ID, snapshot)

    def test_an_unfinished_undo_is_a_500_naming_it(self, side: _Side, flask_app: Flask) -> None:
        """The update cannot be restored: the 500 says the entity is still changed."""
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID, side.membership_key: []}
        managers.own.get_one_by.side_effect = lambda _criteria: {'public_id': PUBLIC_ID, 'changed': True}
        managers.sync.side_effect = side.update_error('nope')

        with patcher, flask_app.test_request_context('/', method='PUT'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.update)(
                    public_id=PUBLIC_ID,
                    data=_payload(side),
                    request_user=SimpleNamespace(public_id=1),
                )

        assert caught.value.code == HTTP_SERVER_ERROR
        assert 'could not be fully undone' in caught.value.description
