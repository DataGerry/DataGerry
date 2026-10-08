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
Unit tests for the CmdbUserSetting routes and their one answer shape

``serialize_user_setting`` is tested on its own; then every route is unwrapped past its auth decorators and driven
inside a test_request_context with the manager patched, to pin that what each one answers is the serializer's output -
the four keys, never the stored ``public_id``
"""
import ast
import inspect
from json import loads
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from cmdb.models.settings_model import UserSettingKey
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_helper import serialize_user_setting
from cmdb.interface.rest_api.routes.user_management_routes import user_settings_routes
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_constants import (
    OWNER_EXCEPTION,
    USER_SETTINGS_RIGHT,
)
from cmdb.interface.rest_api.routes.user_management_routes.user_settings_routes import (
    delete_cmdb_user_setting,
    get_cmdb_user_setting,
    insert_cmdb_user_setting,
    update_cmdb_user_setting,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.user_management_routes.user_settings_routes'

USER_ID: int = 7
RESOURCE: str = 'table-objects'
STORED_PUBLIC_ID: int = 31
SETTING_TYPE: str = 'APPLICATION'
PAYLOADS: list[dict[str, Any]] = [{'id': 'columns', 'data': ['name']}]

FOUR_KEYS: set[str] = {
    UserSettingKey.RESOURCE.value, UserSettingKey.USER_ID.value,
    UserSettingKey.PAYLOADS.value, UserSettingKey.SETTING_TYPE.value,
}


def _stored(**overrides: Any) -> dict[str, Any]:
    """A stored setting document - with the stamped public_id the routes must not answer."""
    document: dict[str, Any] = {
        UserSettingKey.PUBLIC_ID.value: STORED_PUBLIC_ID,
        UserSettingKey.RESOURCE.value: RESOURCE,
        UserSettingKey.USER_ID.value: USER_ID,
        UserSettingKey.PAYLOADS.value: PAYLOADS,
        UserSettingKey.SETTING_TYPE.value: SETTING_TYPE,
    }
    document.update(overrides)

    return document


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain down to the view body."""
    while hasattr(func, '__wrapped__'):
        func = func.__wrapped__

    return func


@pytest.fixture(name='manager')
def fixture_manager() -> Any:
    """The settings manager every route resolves, patched in."""
    manager = MagicMock(name='user_settings_manager')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager):
        yield manager


def _body(response: Any) -> dict[str, Any]:
    """The JSON body of a route's response."""
    return loads(response.get_data())


# -------------------------------------------------------------------------------------------------------------------- #
#                                               serialize_user_setting                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSerializeUserSetting:
    """The one shape: four keys, normalised, never the stored id."""

    def test_a_stored_document_answers_the_four_keys(self) -> None:
        """The public_id is dropped; the rest passes through"""
        assert serialize_user_setting(_stored()) == {
            UserSettingKey.RESOURCE.value: RESOURCE,
            UserSettingKey.USER_ID.value: USER_ID,
            UserSettingKey.PAYLOADS.value: PAYLOADS,
            UserSettingKey.SETTING_TYPE.value: SETTING_TYPE,
        }

    def test_a_missing_payload_list_is_answered_empty(self) -> None:
        """An old document without payloads reads like the list read reads it"""
        document: dict[str, Any] = _stored()
        del document[UserSettingKey.PAYLOADS.value]

        assert serialize_user_setting(document)[UserSettingKey.PAYLOADS.value] == []

    def test_an_unreadable_document_is_answered_as_stored_without_its_id(self) -> None:
        """A scope this version does not know: inspectable and repairable - but the stamped id still stays home"""
        answered: dict[str, Any] = serialize_user_setting(_stored(**{UserSettingKey.SETTING_TYPE.value: 'NOPE'}))

        assert answered[UserSettingKey.SETTING_TYPE.value] == 'NOPE'
        assert UserSettingKey.PUBLIC_ID.value not in answered
        assert '_id' not in answered


# -------------------------------------------------------------------------------------------------------------------- #
#                                         every route answers the one shape                                           #
# -------------------------------------------------------------------------------------------------------------------- #
class TestEveryRouteAnswersTheOneShape:
    """Create, single read, update and delete - the list read already normalises in the manager."""

    def test_the_create(self, manager: MagicMock) -> None:
        """raw is the four keys; the stamped id is the envelope's result_id"""
        manager.get_user_setting.return_value = None
        manager.insert_item.return_value = STORED_PUBLIC_ID
        body: dict[str, Any] = _stored()
        del body[UserSettingKey.PUBLIC_ID.value]

        with Flask(__name__).test_request_context(method='POST'):
            answer: dict[str, Any] = _body(_unwrap(insert_cmdb_user_setting)(
                user_id=USER_ID, data=body, request_user=MagicMock()))

        assert set(answer['raw']) == FOUR_KEYS
        assert answer['result_id'] == STORED_PUBLIC_ID

    def test_the_single_read(self, manager: MagicMock) -> None:
        """The stored document, normalised - its public_id does not leave"""
        manager.get_user_setting.return_value = _stored()

        with Flask(__name__).test_request_context():
            answer: dict[str, Any] = _body(_unwrap(get_cmdb_user_setting)(
                user_id=USER_ID, resource=RESOURCE, request_user=MagicMock()))

        assert set(answer['result']) == FOUR_KEYS

    def test_the_update(self, manager: MagicMock) -> None:
        """The model's four keys, through the same serializer"""
        manager.get_user_setting.return_value = _stored()
        body: dict[str, Any] = _stored()
        del body[UserSettingKey.PUBLIC_ID.value]

        with Flask(__name__).test_request_context(method='PUT'):
            answer: dict[str, Any] = _body(_unwrap(update_cmdb_user_setting)(
                user_id=USER_ID, resource=RESOURCE, data=body, request_user=MagicMock()))

        assert set(answer['result']) == FOUR_KEYS

    def test_the_delete(self, manager: MagicMock) -> None:
        """The deleted document, normalised"""
        manager.get_user_setting.return_value = _stored()

        with Flask(__name__).test_request_context(method='DELETE'):
            answer: dict[str, Any] = _body(_unwrap(delete_cmdb_user_setting)(
                user_id=USER_ID, resource=RESOURCE, request_user=MagicMock()))

        assert set(answer['raw']) == FOUR_KEYS

    @pytest.mark.parametrize('route, kwargs, key, method', [
        (get_cmdb_user_setting, {'resource': RESOURCE}, 'result', 'GET'),
        (delete_cmdb_user_setting, {'resource': RESOURCE}, 'raw', 'DELETE'),
    ], ids=['single-read', 'delete'])
    def test_each_answer_is_the_serializers(self, manager: MagicMock, route: Callable[..., Any],
                                            kwargs: dict[str, Any], key: str, method: str) -> None:
        """Routed through serialize_user_setting itself, so a sixth route cannot drift alone"""
        manager.get_user_setting.return_value = _stored()
        marker: dict[str, Any] = {'serialized': True}

        with patch(f'{ROUTE_PATH}.serialize_user_setting', return_value=marker) as serializer, \
                Flask(__name__).test_request_context(method=method):
            answer: dict[str, Any] = _body(_unwrap(route)(user_id=USER_ID, request_user=MagicMock(), **kwargs))

        serializer.assert_called_once_with(_stored())
        assert answer[key] == marker


# ----------------------------------------------------- the gate ----------------------------------------------------- #

SETTINGS_ROUTES: list[str] = [
    'insert_cmdb_user_setting', 'get_cmdb_user_settings', 'get_cmdb_user_setting', 'update_cmdb_user_setting',
    'delete_cmdb_user_setting',
]


def _settings_route_decorators(function_name: str) -> list[ast.expr]:
    """One route's decorators, outermost first"""
    tree = ast.parse(inspect.getsource(user_settings_routes))

    return next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == function_name).decorator_list


def _decorator_name(decorator: ast.expr) -> str:
    """`bp.protect(...)` -> 'protect'"""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    return target.attr if isinstance(target, ast.Attribute) else getattr(target, 'id', '')


@pytest.mark.parametrize('function_name', SETTINGS_ROUTES)
def test_every_settings_route_is_the_owners_or_a_user_editors(function_name: str) -> None:
    """One `.protect`: the user-edit right with the owner carve-out, below the authentication"""
    protects = [decorator for decorator in _settings_route_decorators(function_name)
                if _decorator_name(decorator) == 'protect']

    assert len(protects) == 1
    keywords = {keyword.arg: ast.unparse(keyword.value) for keyword in protects[0].keywords}
    assert (keywords['right'], keywords['excepted']) == ('USER_SETTINGS_RIGHT', 'OWNER_EXCEPTION')


def test_the_owner_carve_out_compares_the_callers_id_with_the_paths() -> None:
    """public_id of the caller against the route's user_id - and the right is the one to edit users"""
    assert OWNER_EXCEPTION == {'public_id': 'user_id'}
    assert USER_SETTINGS_RIGHT == 'base.user-management.user.edit'

