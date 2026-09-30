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
Unit tests for cmdb.interface.blueprints.api_blueprint

APIBlueprint provides the decorator layer every REST route is built on: ``protect`` (the right check
on the user ``insert_request_user`` injected, + the ``excepted`` self-access carve-out), ``validate``
(Cerberus schema validation), and the ``parse_*`` query/body parameter decorators. Each test applies
the decorator to a stub route and drives it inside a BaseCmdbApp ``test_request_context`` with the
collaborators (``user_has_right`` / ``CmdbUser``) patched at the module path - no Mongo, no tokens.
"""
# pylint: disable=protected-access  # these tests intentionally exercise the module-private helper
# pylint: disable=unused-argument  # stub routes accept whatever the decorator under test forwards
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Blueprint
from werkzeug.exceptions import HTTPException

from cmdb.interface.blueprints.api_blueprint import APIBlueprint
from cmdb.interface.blueprints.api_blueprint_constants import (
    PROTECT_WITHOUT_REQUEST_USER_MESSAGE,
    RIGHT_CHECK_FAILED_MESSAGE,
)
from cmdb.interface.cmdb_app import BaseCmdbApp
from cmdb.errors.manager.groups_manager import GroupsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.blueprints.api_blueprint'

RIGHT: str = 'base.framework.object.view'
ROUTE_RESULT: str = 'ROUTE_CALLED'
SELF_ACCESS_EXCEPTED: dict[str, str] = {'public_id': 'public_id'}

def _app(cloud_mode: bool = False) -> BaseCmdbApp:
    """Builds a BaseCmdbApp with a stub database_manager and the given cloud flag."""
    app = BaseCmdbApp(__name__)
    app.database_manager = MagicMock()
    app.cloud_mode = cloud_mode
    app.local_mode = False

    return app


def _route(*args, **kwargs) -> str:
    """Stub route body - returns a sentinel so tests can assert the route ran."""
    return ROUTE_RESULT


# ================================================= construction ===================================================== #

class TestConstruction:
    """APIBlueprint is a thin Flask Blueprint subclass."""

    def test_is_a_flask_blueprint(self) -> None:
        """Instantiating an APIBlueprint yields a Flask Blueprint."""
        blueprint = APIBlueprint('api_test', __name__)
        assert isinstance(blueprint, Blueprint)


# =================================================== protect ======================================================== #

class TestProtectNoEnforcement:
    """``protect`` only enforces when both ``auth`` and ``right`` are set."""

    def test_auth_false_calls_route_without_checks(self) -> None:
        """auth=False short-circuits the whole check and runs the route."""
        wrapped = APIBlueprint.protect(auth=False, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right') as mocked_right:
            with _app().test_request_context():
                assert wrapped() == ROUTE_RESULT
        mocked_right.assert_not_called()

    def test_no_right_is_a_no_op(self) -> None:
        """auth-only .protect(auth=True) with no right performs no enforcement

        A documented no-op.
        """
        wrapped = APIBlueprint.protect(auth=True)(_route)
        with patch(f'{MODULE_PATH}.user_has_right') as mocked_right:
            with _app().test_request_context():
                assert wrapped() == ROUTE_RESULT
        mocked_right.assert_not_called()


class TestProtectRightCheck:
    """The right check runs on the user ``insert_request_user`` handed in - nothing is read twice."""

    def test_user_with_right_runs_route(self) -> None:
        """A user holding the right runs the route, and it is THAT user whose right is asked"""
        request_user = MagicMock()
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=True) as mocked_right:
            with _app().test_request_context():
                assert wrapped(request_user=request_user) == ROUTE_RESULT
        mocked_right.assert_called_once_with(RIGHT, request_user)

    def test_user_without_right_aborts_403(self) -> None:
        """A user lacking the right and no excepted rule aborts 403."""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=False):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    wrapped(request_user=MagicMock())
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    @pytest.mark.parametrize('cloud_mode', [False, True], ids=['on-premise', 'cloud'])
    def test_the_token_is_never_read(self, cloud_mode: bool) -> None:
        """The same path in both modes: no header parsing, no token decoding, no user read"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=True), \
             patch('cmdb.interface.route_utils.parse_authorization_header') as parse, \
             patch('cmdb.interface.route_utils.decode_request_token') as decode:
            with _app(cloud_mode=cloud_mode).test_request_context(headers={'Authorization': 'Bearer t'}):
                assert wrapped(request_user=MagicMock()) == ROUTE_RESULT
        parse.assert_not_called()
        decode.assert_not_called()

    def test_a_route_without_insert_request_user_is_a_500(self) -> None:
        """A wiring fault on the route, not the caller's fault - and no right is ever granted without a user"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right') as mocked_right:
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    wrapped()
        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == PROTECT_WITHOUT_REQUEST_USER_MESSAGE
        mocked_right.assert_not_called()

    def test_a_failed_right_check_is_a_500_not_a_403(self) -> None:
        """A group that could not be READ is an outage, not a missing right"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', side_effect=GroupsManagerGetError('db down')):
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    wrapped(request_user=MagicMock())
        assert exc_info.value.code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert exc_info.value.description == RIGHT_CHECK_FAILED_MESSAGE


class TestProtectExcepted:
    """The ``excepted`` carve-out reads the injected user, on-premise and in cloud mode alike."""

    @pytest.mark.parametrize('cloud_mode', [False, True], ids=['on-premise', 'cloud'])
    def test_a_user_acting_on_their_own_record_passes(self, cloud_mode: bool) -> None:
        """No right, but the user attribute equals the route parameter"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT, excepted=SELF_ACCESS_EXCEPTED)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=False), \
             patch(f'{MODULE_PATH}.CmdbUser') as cmdb_user:
            cmdb_user.to_public_json.return_value = {'public_id': 5}
            with _app(cloud_mode=cloud_mode).test_request_context():
                assert wrapped(request_user=MagicMock(), public_id=5) == ROUTE_RESULT

    def test_a_user_acting_on_another_record_is_403(self) -> None:
        """The attribute does not match the route parameter"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT, excepted=SELF_ACCESS_EXCEPTED)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=False), \
             patch(f'{MODULE_PATH}.CmdbUser') as cmdb_user:
            cmdb_user.to_public_json.return_value = {'public_id': 5}
            with _app().test_request_context():
                with pytest.raises(HTTPException) as exc_info:
                    wrapped(request_user=MagicMock(), public_id=999)
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_a_user_holding_the_right_never_reaches_the_carve_out(self) -> None:
        """The carve-out is asked only when the right is missing"""
        wrapped = APIBlueprint.protect(auth=True, right=RIGHT, excepted=SELF_ACCESS_EXCEPTED)(_route)
        with patch(f'{MODULE_PATH}.user_has_right', return_value=True), \
             patch.object(APIBlueprint, '_user_matches_excepted') as matches:
            with _app().test_request_context():
                assert wrapped(request_user=MagicMock(), public_id=999) == ROUTE_RESULT
        matches.assert_not_called()


class TestUserMatchesExcepted:
    """The extracted (D1) carve-out matcher, tested in isolation."""

    def test_match_returns_true(self) -> None:
        """A user attribute equal to the route parameter matches."""
        assert APIBlueprint._user_matches_excepted(
            {'public_id': 'public_id'}, {'public_id': 7}, {'public_id': 7}, RIGHT
        ) is True

    def test_no_match_returns_false(self) -> None:
        """A user attribute different from the route parameter does not match."""
        assert APIBlueprint._user_matches_excepted(
            {'public_id': 'public_id'}, {'public_id': 7}, {'public_id': 8}, RIGHT
        ) is False

    def test_missing_route_parameter_aborts_403(self) -> None:
        """A referenced route parameter that is absent aborts 403."""
        with pytest.raises(HTTPException) as exc_info:
            APIBlueprint._user_matches_excepted(
                {'public_id': 'public_id'}, {'public_id': 7}, {}, RIGHT
            )
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    def test_missing_user_attribute_aborts_403(self) -> None:
        """A user missing the compared attribute aborts 403."""
        with pytest.raises(HTTPException) as exc_info:
            APIBlueprint._user_matches_excepted(
                {'public_id': 'public_id'}, {'other': 1}, {'public_id': 7}, RIGHT
            )
        assert exc_info.value.code == HTTPStatus.FORBIDDEN


# =================================================== validate ======================================================= #

class TestValidate:
    """``validate`` checks the JSON body against a Cerberus schema and injects the normalized document."""

    SCHEMA: dict[str, Any] = {'name': {'type': 'string', 'required': True}}

    def test_valid_data_injected_as_document(self) -> None:
        """A valid body is normalized (unknown keys purged) and passed as ``data``."""
        captured: dict[str, Any] = {}

        def route(*args, data=None, **kwargs) -> str:
            captured['data'] = data
            return ROUTE_RESULT

        wrapped = APIBlueprint.validate(self.SCHEMA)(route)
        with _app().test_request_context(json={'name': 'x', 'extra': 'purged'}):
            assert wrapped() == ROUTE_RESULT
        assert captured['data'] == {'name': 'x'}

    def test_invalid_data_aborts_400(self) -> None:
        """A body failing the schema aborts 400."""
        wrapped = APIBlueprint.validate(self.SCHEMA)(_route)
        with _app().test_request_context(json={'name': 123}):
            with pytest.raises(HTTPException) as exc_info:
                wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_a_refused_body_is_told_which_field_failed_and_why(self) -> None:
        """The 400 names the failing field and the rule, instead of a message that names nothing."""
        wrapped = APIBlueprint.validate(self.SCHEMA)(_route)
        with _app().test_request_context(json={'name': 123}):
            with pytest.raises(HTTPException) as exc_info:
                wrapped()
        assert exc_info.value.description == 'Invalid data provided: name: must be of string type'

    def test_validator_exception_aborts_400(self) -> None:
        """An exception raised inside the validator aborts 400 (Validator built at decoration time)."""
        with patch(f'{MODULE_PATH}.Validator') as validator_cls:
            validator_cls.return_value.validate.side_effect = ValueError('boom')
            wrapped = APIBlueprint.validate(self.SCHEMA)(_route)
            with _app().test_request_context(json={'name': 'x'}):
                with pytest.raises(HTTPException) as exc_info:
                    wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST

    def test_a_validator_failure_does_not_echo_the_schema(self) -> None:
        """The schema is internal: a crash inside the validator answers a fixed message naming nothing."""
        with patch(f'{MODULE_PATH}.Validator') as validator_cls:
            validator_cls.return_value.validate.side_effect = ValueError('boom')
            wrapped = APIBlueprint.validate(self.SCHEMA)(_route)
            with _app().test_request_context(json={'name': 'x'}):
                with pytest.raises(HTTPException) as exc_info:
                    wrapped()
        assert exc_info.value.description == 'The request body could not be validated!'
        assert 'name' not in exc_info.value.description


# =============================================== parse_parameters =================================================== #

class TestParseParameters:
    """``parse_parameters`` builds a parameters object from the query string."""

    def test_success_injects_params(self) -> None:
        """A parsed parameters object is injected as ``params``."""
        captured: dict[str, Any] = {}
        params_class = MagicMock()
        params_class.from_data.return_value = 'PARSED'

        def route(*args, params=None, **kwargs) -> str:
            captured['params'] = params
            return ROUTE_RESULT

        wrapped = APIBlueprint.parse_parameters(params_class)(route)
        with _app().test_request_context('/?limit=5'):
            assert wrapped() == ROUTE_RESULT
        assert captured['params'] == 'PARSED'

    def test_parse_failure_aborts_400(self) -> None:
        """A parameters class that raises aborts 400."""
        params_class = MagicMock()
        params_class.from_data.side_effect = ValueError('bad')
        wrapped = APIBlueprint.parse_parameters(params_class)(_route)
        with _app().test_request_context('/?limit=5'):
            with pytest.raises(HTTPException) as exc_info:
                wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ============================================ parse_request_parameters ============================================== #

class TestParseRequestParameters:
    """``parse_request_parameters`` forwards the raw query dict."""

    def test_success_injects_query_dict(self) -> None:
        """The request args dict is injected as ``params``."""
        captured: dict[str, Any] = {}

        def route(*args, params=None, **kwargs) -> str:
            captured['params'] = params
            return ROUTE_RESULT

        wrapped = APIBlueprint.parse_request_parameters()(route)
        with _app().test_request_context('/?a=1&b=2'):
            assert wrapped() == ROUTE_RESULT
        assert captured['params'] == {'a': '1', 'b': '2'}

    def test_parse_failure_aborts_400(self) -> None:
        """A failure reading request args aborts 400."""
        wrapped = APIBlueprint.parse_request_parameters()(_route)
        fake_request = MagicMock()
        fake_request.args.to_dict.side_effect = RuntimeError('boom')
        with patch(f'{MODULE_PATH}.request', fake_request):
            with pytest.raises(HTTPException) as exc_info:
                wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# =============================================== parse_request_body ================================================= #

class TestParseRequestBody:
    """``parse_request_body`` forwards the JSON body when it is a dict."""

    def test_dict_body_injected_as_data(self) -> None:
        """A JSON object body is injected as ``data``."""
        captured: dict[str, Any] = {}

        def route(*args, data=None, **kwargs) -> str:
            captured['data'] = data
            return ROUTE_RESULT

        wrapped = APIBlueprint.parse_request_body()(route)
        with _app().test_request_context(json={'a': 1}):
            assert wrapped() == ROUTE_RESULT
        assert captured['data'] == {'a': 1}

    def test_non_dict_body_aborts_400(self) -> None:
        """A non-object body (silent None / list) aborts 400."""
        wrapped = APIBlueprint.parse_request_body()(_route)
        with _app().test_request_context(json=[1, 2, 3]):
            with pytest.raises(HTTPException) as exc_info:
                wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST


# ========================================== parse_collection_parameters ============================================= #

class TestParseCollectionParameters:
    """``parse_collection_parameters`` builds a CollectionParameters instance from the query string."""

    def test_success_injects_params(self) -> None:
        """A parsed CollectionParameters is injected as ``params``."""
        captured: dict[str, Any] = {}

        def route(*args, params=None, **kwargs) -> str:
            captured['params'] = params
            return ROUTE_RESULT

        wrapped = APIBlueprint.parse_collection_parameters()(route)
        with patch(f'{MODULE_PATH}.CollectionParameters') as cp_cls:
            cp_cls.from_data.return_value = 'COLLECTION_PARAMS'
            with _app().test_request_context('/?limit=10&page=1'):
                assert wrapped() == ROUTE_RESULT
        assert captured['params'] == 'COLLECTION_PARAMS'

    def test_parse_failure_aborts_400(self) -> None:
        """A failure building CollectionParameters aborts 400."""
        wrapped = APIBlueprint.parse_collection_parameters()(_route)
        with patch(f'{MODULE_PATH}.CollectionParameters') as cp_cls:
            cp_cls.from_data.side_effect = ValueError('bad')
            with _app().test_request_context('/?limit=10'):
                with pytest.raises(HTTPException) as exc_info:
                    wrapped()
        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
