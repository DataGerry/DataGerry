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
    nothing. Documents written before updater_20260909 can still carry that null
  - **an unknown reference is refused before anything is written**, rather than stored and then
    mirrored into no document
  - **the delete route makes exactly one call.** The reciprocal cleanup moved into the manager's
    cascade, so the route must not repeat it - and must not be the only place it happens
  - the error tails: which manager error becomes a 400, and that anything else becomes a 500
"""
# pylint: disable=too-many-arguments,too-many-positional-arguments
from types import SimpleNamespace
from typing import Any, Callable, NamedTuple
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.person_model import PersonKey
from cmdb.models.person_group_model import PersonGroupKey

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
    payload: dict[str, Any]
    add_method: str
    sync_method: str
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
    {
        PersonKey.DISPLAY_NAME.value: 'Ada Lovelace',
        PersonKey.FIRST_NAME.value: 'Ada',
        PersonKey.LAST_NAME.value: 'Lovelace',
    },
    'add_person_to_groups',
    'update_person_in_groups',
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
    {PersonGroupKey.NAME.value: 'Security officers', PersonGroupKey.EMAIL.value: ''},
    'add_group_to_persons',
    'update_group_in_persons',
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
    """The two managers a route resolves, kept apart so a test can say which one was written"""
    own: MagicMock
    counterpart: MagicMock


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


def _patched_managers(side: _Side) -> Any:
    """
    Patches ManagerProvider.get_manager so each ManagerType returns its own mock

    Args:
        side (_Side): The route file under test

    Returns:
        Any: A context manager yielding the two managers
    """
    managers = _Managers(MagicMock(), MagicMock())
    by_type: dict[ManagerType, MagicMock] = {
        side.own_manager_type: managers.own,
        side.counterpart_manager_type: managers.counterpart,
    }

    patcher = patch(
        f'{side.route_path}.ManagerProvider.get_manager',
        side_effect=lambda manager_type, _user: by_type[manager_type],
    )

    return patcher, managers


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
        disagreed from that moment with nothing in the response to say so.
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

        getattr(managers.counterpart, side.add_method).assert_called_once_with(NEW_ID, [5])

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
    """What the update route computes, including from a document written before the fix."""

    def test_a_stored_null_membership_is_read_as_empty(self, side: _Side, flask_app: Flask) -> None:
        """
        The 500 this sweep was scheduled for: set(None) raised inside the route's try block

        A document written before updater_20260909 can still carry the null, so the route stays
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

        getattr(managers.counterpart, side.sync_method).assert_called_once_with(PUBLIC_ID, {4}, set())

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

        getattr(managers.counterpart, side.sync_method).assert_called_once_with(PUBLIC_ID, set(), {1})

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

        getattr(managers.counterpart, side.sync_method).assert_not_called()


@pytest.mark.parametrize('side', SIDES, ids=SIDE_IDS)
class TestDeleteIsOneManagerCall:
    """The cascade belongs to the manager, and the route must not own half of it."""

    def test_delegates_the_whole_cascade(self, side: _Side, flask_app: Flask) -> None:
        """
        delete_with_follow_up now removes the entity from the counterpart collection itself

        The route used to make that second call, which is why deleting through any other path left
        the membership behind.
        """
        patcher, managers = _patched_managers(side)
        managers.own.get_item.return_value = {'public_id': PUBLIC_ID}

        with patcher, flask_app.test_request_context('/', method='DELETE'):
            _unwrap(side.delete)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        managers.own.delete_with_follow_up.assert_called_once_with(PUBLIC_ID)

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

    def test_an_unreadable_created_document_is_a_404(self, side: _Side, flask_app: Flask) -> None:
        """The write landed but the read back found nothing, which is not a successful create."""
        patcher, managers = _patched_managers(side)
        managers.own.insert_item.return_value = NEW_ID
        managers.own.get_item.return_value = None

        with patcher, flask_app.test_request_context('/', method='POST'):
            with pytest.raises(HTTPException) as caught:
                _unwrap(side.insert)(data=_payload(side), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND

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

        Before this sweep the person cascades raised whatever pymongo raised, and the route answered
        500 for a failure its ObjectGroup twin reported as a 400.
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
