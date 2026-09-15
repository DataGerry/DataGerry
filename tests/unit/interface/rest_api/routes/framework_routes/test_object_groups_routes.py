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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.object_groups_routes

Each handler is unwrapped past its auth / validation decorators and driven inside a Flask
test_request_context, with ObjectGroupsManager patched at the route module path. No Mongo, no
blueprint registration.

The five routes are plain CRUD, so what is pinned is the glue: the identity pin on update, the single
cascade call on delete - which removes IsmsRiskAssessments, not merely references - and the error
tails, none of which any functional test can reach over HTTP
"""
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.object_group_model import ObjectGroupKey, ObjectGroupMode
from cmdb.errors.manager.object_groups_manager import (
    ObjectGroupsManagerDeleteError,
    ObjectGroupsManagerGetError,
    ObjectGroupsManagerInsertError,
    ObjectGroupsManagerIterationError,
    ObjectGroupsManagerUpdateError,
)
from cmdb.interface.rest_api.routes.framework_routes.object_groups_routes import (
    delete_cmdb_object_group,
    get_cmdb_object_group,
    get_cmdb_object_groups,
    insert_cmdb_object_group,
    update_cmdb_object_group,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.object_groups_routes'

PUBLIC_ID: int = 6
NEW_ID: int = 11

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

PAYLOAD: dict[str, Any] = {
    ObjectGroupKey.NAME.value: 'Core switches',
    ObjectGroupKey.GROUP_TYPE.value: ObjectGroupMode.STATIC.value,
    ObjectGroupKey.ASSIGNED_IDS.value: [1, 2],
}


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / validate / protect / verify / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='mgr')
def fixture_mgr() -> MagicMock:
    """The ObjectGroupsManager stub every route resolves through ManagerProvider."""
    return MagicMock()


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ManagerProvider.get_manager at the route module path."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr) as provider:
        yield provider


class TestInsert:
    """The create route: write, read back, respond."""

    def test_returns_the_created_group(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The document read back after the write is what the response carries, not the payload."""
        del patched_manager_provider
        mgr.insert_item.return_value = NEW_ID
        mgr.get_item.return_value = {'public_id': NEW_ID, **PAYLOAD}

        with flask_app.test_request_context('/', method='POST'), \
             patch(f'{ROUTE_PATH}.InsertSingleResponse') as response_ctor:
            _unwrap(insert_cmdb_object_group)(data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1))

        response_ctor.assert_called_once_with(mgr.get_item.return_value, NEW_ID)

    def test_an_unreadable_created_group_is_a_404(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The write landed but the read back found nothing, which is not a successful create."""
        del patched_manager_provider
        mgr.insert_item.return_value = NEW_ID
        mgr.get_item.return_value = None

        with flask_app.test_request_context('/', method='POST'), pytest.raises(HTTPException) as caught:
            _unwrap(insert_cmdb_object_group)(data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND

    def test_a_failing_write_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """A rejected write is the client's problem to fix."""
        del patched_manager_provider
        mgr.insert_item.side_effect = ObjectGroupsManagerInsertError('nope')

        with flask_app.test_request_context('/', method='POST'), pytest.raises(HTTPException) as caught:
            _unwrap(insert_cmdb_object_group)(data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_a_failing_read_back_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The read back has its own error arm, separate from the write's."""
        del patched_manager_provider
        mgr.insert_item.return_value = NEW_ID
        mgr.get_item.side_effect = ObjectGroupsManagerGetError('nope')

        with flask_app.test_request_context('/', method='POST'), pytest.raises(HTTPException) as caught:
            _unwrap(insert_cmdb_object_group)(data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_error_is_a_500(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The generic tail."""
        del patched_manager_provider
        mgr.insert_item.side_effect = RuntimeError('boom')

        with flask_app.test_request_context('/', method='POST'), pytest.raises(HTTPException) as caught:
            _unwrap(insert_cmdb_object_group)(data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR


class TestRead:
    """The two read routes."""

    def test_a_failing_list_read_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The iteration error the collection route maps."""
        del patched_manager_provider
        mgr.iterate_items.side_effect = ObjectGroupsManagerIterationError('nope')

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as caught:
            _unwrap(get_cmdb_object_groups)(params=MagicMock(), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_list_error_is_a_500(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The generic tail of the collection route."""
        del patched_manager_provider
        mgr.iterate_items.side_effect = RuntimeError('boom')

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as caught:
            _unwrap(get_cmdb_object_groups)(params=MagicMock(), request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR

    def test_a_missing_group_is_a_404(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The read route's own abort, which its except arms must not swallow into a 500."""
        del patched_manager_provider
        mgr.get_item.return_value = None

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as caught:
            _unwrap(get_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND

    def test_a_failing_single_read_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """A get error names the id it could not read."""
        del patched_manager_provider
        mgr.get_item.side_effect = ObjectGroupsManagerGetError('nope')

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as caught:
            _unwrap(get_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_single_read_error_is_a_500(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """The generic tail of the single-read route."""
        del patched_manager_provider
        mgr.get_item.side_effect = RuntimeError('boom')

        with flask_app.test_request_context('/'), pytest.raises(HTTPException) as caught:
            _unwrap(get_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR


class TestUpdate:
    """The update route, whose only logic is the identity pin."""

    def test_the_public_id_of_the_url_wins_over_the_body(
        self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
    ) -> None:
        """A forged body public_id must not be able to rewrite another group's identity."""
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}

        with flask_app.test_request_context('/', method='PUT'):
            _unwrap(update_cmdb_object_group)(
                public_id=PUBLIC_ID,
                data={**PAYLOAD, 'public_id': 9999},
                request_user=SimpleNamespace(public_id=1),
            )

        assert mgr.update_item.call_args.args[1].get_public_id() == PUBLIC_ID

    def test_a_missing_group_is_a_404(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """Updating something that does not exist is not a create."""
        del patched_manager_provider
        mgr.get_item.return_value = None

        with flask_app.test_request_context('/', method='PUT'), pytest.raises(HTTPException) as caught:
            _unwrap(update_cmdb_object_group)(
                public_id=PUBLIC_ID, data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1),
            )

        assert caught.value.code == HTTP_NOT_FOUND
        mgr.update_item.assert_not_called()

    def test_a_failing_write_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The update error arm."""
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}
        mgr.update_item.side_effect = ObjectGroupsManagerUpdateError('nope')

        with flask_app.test_request_context('/', method='PUT'), pytest.raises(HTTPException) as caught:
            _unwrap(update_cmdb_object_group)(
                public_id=PUBLIC_ID, data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1),
            )

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_error_is_a_500(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The generic tail of the update route."""
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}
        mgr.update_item.side_effect = RuntimeError('boom')

        with flask_app.test_request_context('/', method='PUT'), pytest.raises(HTTPException) as caught:
            _unwrap(update_cmdb_object_group)(
                public_id=PUBLIC_ID, data=dict(PAYLOAD), request_user=SimpleNamespace(public_id=1),
            )

        assert caught.value.code == HTTP_SERVER_ERROR


class TestDelete:
    """The delete route, whose one call removes ISMS documents as well."""

    def test_delegates_the_whole_cascade(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """
        delete_with_follow_up removes every IsmsRiskAssessment assessing the group

        The route neither warns about that nor reports how many went with it, which is recorded on
        the route itself.
        """
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}

        with flask_app.test_request_context('/', method='DELETE'):
            _unwrap(delete_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        mgr.delete_with_follow_up.assert_called_once_with(PUBLIC_ID)

    def test_a_missing_group_is_a_404(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """Nothing is deleted and nothing is cascaded for an id that does not exist."""
        del patched_manager_provider
        mgr.get_item.return_value = None

        with flask_app.test_request_context('/', method='DELETE'), pytest.raises(HTTPException) as caught:
            _unwrap(delete_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_NOT_FOUND
        mgr.delete_with_follow_up.assert_not_called()

    def test_a_failing_cascade_is_a_400(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The manager wraps the cascade's failure, which is what makes this a 400 rather than a 500."""
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}
        mgr.delete_with_follow_up.side_effect = ObjectGroupsManagerDeleteError('nope')

        with flask_app.test_request_context('/', method='DELETE'), pytest.raises(HTTPException) as caught:
            _unwrap(delete_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_BAD_REQUEST

    def test_an_unexpected_error_is_a_500(self, flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
        """The generic tail of the delete route."""
        del patched_manager_provider
        mgr.get_item.return_value = {'public_id': PUBLIC_ID, **PAYLOAD}
        mgr.delete_with_follow_up.side_effect = RuntimeError('boom')

        with flask_app.test_request_context('/', method='DELETE'), pytest.raises(HTTPException) as caught:
            _unwrap(delete_cmdb_object_group)(public_id=PUBLIC_ID, request_user=SimpleNamespace(public_id=1))

        assert caught.value.code == HTTP_SERVER_ERROR
