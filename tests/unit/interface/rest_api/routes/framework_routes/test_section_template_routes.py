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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_routes

Each test unwraps the route handler past its auth / validation decorators and drives the bare
function inside a Flask test_request_context, with SectionTemplatesManager and the response
factories patched at the route module path. No Mongo and no blueprint registration runs - only
the route glue (input validation, status-code mapping, ordering of manager calls) is exercised.
The update not-found / immutable-property cases pin the bug fix that made those aborts surface as
their intended 404 / 400 instead of being swallowed into 500
"""
# pylint: disable=protected-access
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager import SectionTemplatesManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_routes import (
    create_section_template,
    get_all_section_templates,
    get_section_template,
    get_global_section_template_count,
    update_section_template,
    delete_section_template,
)
from cmdb.errors.manager.section_templates_manager import (
    SectionTemplatesManagerInsertError,
    SectionTemplatesManagerIterationError,
    SectionTemplatesManagerGetError,
    SectionTemplatesManagerUpdateError,
    SectionTemplatesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_routes'

TEMPLATE_PUBLIC_ID: int = 7

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / validate / protect / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


def _create_params(**overrides: Any) -> dict[str, Any]:
    """Builds a valid create payload (query-string style: booleans/fields are strings)."""
    params: dict[str, Any] = {
        'name': 'tpl',
        'label': 'Tpl',
        'type': 'section',
        'is_global': 'false',
        'predefined': 'false',
        'fields': '[]',
    }
    params.update(overrides)

    return params


def _update_params(**overrides: Any) -> dict[str, Any]:
    """Builds a valid update payload (query-string style)."""
    params: dict[str, Any] = {
        'public_id': str(TEMPLATE_PUBLIC_ID),
        'label': 'Tpl',
        'type': 'section',
        'is_global': 'false',
        'predefined': 'false',
        'fields': '[]',
    }
    params.update(overrides)

    return params


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


@pytest.fixture(name='mgr')
def fixture_mgr() -> MagicMock:
    """A MagicMock standing in for a SectionTemplatesManager, returned by the patched ManagerProvider."""
    return MagicMock(spec=SectionTemplatesManager)


@pytest.fixture(name='patched_manager_provider')
def fixture_patched_manager_provider(mgr: MagicMock) -> Any:
    """Patches ManagerProvider.get_manager at the route module path to return mgr."""
    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr) as provider:
        yield provider


# -------------------------------------------------------------------------------------------------------------------- #
#                                              create_section_template                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_create(flask_app: Flask, params: dict[str, Any]) -> Any:
    """Drives the unwrapped create handler inside a POST request context."""
    with flask_app.test_request_context('/', method='POST'):
        return _unwrap(create_section_template)(params=params, request_user=MagicMock())


def test_create_returns_new_public_id(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A valid payload inserts and returns the new public_id via DefaultResponse"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.get_next_public_id.return_value = TEMPLATE_PUBLIC_ID
    mgr.insert_section_template.return_value = TEMPLATE_PUBLIC_ID

    with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _call_create(flask_app, _create_params())

    response_ctor.assert_called_once_with(TEMPLATE_PUBLIC_ID)


def test_create_normalizes_booleans_and_fields_before_insert(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """is_global/predefined are coerced to bool, fields JSON-decoded, predefined forced False"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.get_next_public_id.return_value = TEMPLATE_PUBLIC_ID

    with patch(f'{ROUTE_PATH}.DefaultResponse'):
        _call_create(flask_app, _create_params(is_global='true', fields='[{"name": "f"}]'))

    inserted = mgr.insert_section_template.call_args.args[0]
    assert inserted['is_global'] is True
    assert inserted['predefined'] is False
    assert inserted['fields'] == [{"name": "f"}]


@pytest.mark.parametrize('missing_key', ['name', 'label', 'type', 'is_global', 'predefined', 'fields'])
def test_create_missing_required_param_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any, missing_key: str,
) -> None:
    """A payload missing any required parameter aborts 400 before touching the manager"""
    del patched_manager_provider
    params = _create_params()
    del params[missing_key]

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, params)

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.insert_section_template.assert_not_called()


def test_create_duplicate_name_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """An existing template with the same name aborts 400"""
    del patched_manager_provider
    mgr.get_one_by.return_value = {'public_id': 1, 'name': 'tpl'}

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params())

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_create_invalid_type_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """An unsupported section type aborts 400"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params(type='bogus'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_create_predefined_request_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """Requesting a predefined template via the API aborts 400"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params(predefined='true'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_create_malformed_fields_json_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """A non-JSON 'fields' string aborts 400 rather than crashing into 500"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.get_next_public_id.return_value = TEMPLATE_PUBLIC_ID

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params(fields='{not json'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_create_insert_error_maps_to_500(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerInsertError is translated to HTTP 500"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.get_next_public_id.return_value = TEMPLATE_PUBLIC_ID
    mgr.insert_section_template.side_effect = SectionTemplatesManagerInsertError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params())

    assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                             get_all_section_templates                                                #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_all_returns_multi_response(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """The iteration result is handed to GetMultiResponse"""
    del patched_manager_provider
    mgr.iterate.return_value = SimpleNamespace(results=[SimpleNamespace(a=1)], total=1)

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.BuilderParameters'), \
         patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}), \
         patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
        _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    response_ctor.assert_called_once()


def test_get_all_iteration_error_maps_to_500(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """A SectionTemplatesManagerIterationError is translated to HTTP 500"""
    del patched_manager_provider
    mgr.iterate.side_effect = SectionTemplatesManagerIterationError('boom')

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.BuilderParameters'), \
         patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              get_section_template                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_returns_template(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """An existing template is wrapped in DefaultResponse"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock()

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    response_ctor.assert_called_once()


def test_get_missing_template_maps_to_404(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A missing template aborts 404"""
    del patched_manager_provider
    mgr.get_section_template.return_value = None

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_NOT_FOUND


def test_get_manager_error_maps_to_500(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerGetError is translated to HTTP 500"""
    del patched_manager_provider
    mgr.get_section_template.side_effect = SectionTemplatesManagerGetError('boom')

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                       get_global_section_template_count                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_count_returns_counts(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """The usage counts are wrapped in DefaultResponse"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(name='tpl', is_global=True)
    mgr.get_global_template_usage_count.return_value = {'types': 1, 'objects': 2}

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor:
        _unwrap(get_global_section_template_count)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    response_ctor.assert_called_once_with({'types': 1, 'objects': 2})


def test_count_missing_template_maps_to_404(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A missing template aborts 404"""
    del patched_manager_provider
    mgr.get_section_template.return_value = None

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_global_section_template_count)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                              update_section_template                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_update(flask_app: Flask, params: dict[str, Any]) -> Any:
    """Drives the unwrapped update handler inside a PUT request context."""
    with flask_app.test_request_context('/', method='PUT'):
        return _unwrap(update_section_template)(params=params, request_user=MagicMock())


def test_update_persists_and_propagates(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A valid update persists the template and propagates the change to consumers"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, type='section')

    with patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
        _call_update(flask_app, _update_params())

    mgr.update_section_template.assert_called_once()
    mgr.handle_section_template_changes.assert_called_once()


def test_update_missing_template_maps_to_404(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A not-found target aborts 404 (the abort must not be swallowed into 500)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = None

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_NOT_FOUND
    mgr.update_section_template.assert_not_called()


def test_update_changing_predefined_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """Changing the immutable 'predefined' property aborts 400 (not swallowed into 500)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=True, type='section')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(predefined='false'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_update_changing_type_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """Changing the immutable 'type' aborts 400 (not swallowed into 500)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, type='multi-data-section')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(type='section'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_update_non_integer_public_id_maps_to_400(
    flask_app: Flask, patched_manager_provider: Any,
) -> None:
    """A non-integer public_id aborts 400 rather than crashing into 500"""
    del patched_manager_provider

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(public_id='abc'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_update_missing_label_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """An update payload missing 'label' aborts 400 before touching the manager"""
    del patched_manager_provider
    params = _update_params()
    del params['label']

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, params)

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()


def test_update_manager_error_maps_to_500(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerUpdateError is translated to HTTP 500"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, type='section')
    mgr.update_section_template.side_effect = SectionTemplatesManagerUpdateError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                              delete_section_template                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def _call_delete(flask_app: Flask) -> Any:
    """Drives the unwrapped delete handler inside a DELETE request context."""
    with flask_app.test_request_context('/', method='DELETE'):
        return _unwrap(delete_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())


def test_delete_non_global_skips_cleanup(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A non-global template is deleted without running global cleanup"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, is_global=False)
    mgr.delete_section_template.return_value = True

    with patch(f'{ROUTE_PATH}.DefaultResponse'):
        _call_delete(flask_app)

    mgr.cleanup_global_section_templates.assert_not_called()
    mgr.delete_section_template.assert_called_once_with(TEMPLATE_PUBLIC_ID)


def test_delete_global_runs_cleanup_first(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A global template triggers cleanup of types/objects before the document is deleted"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(name='glob', predefined=False, is_global=True)
    mgr.delete_section_template.return_value = True

    with patch(f'{ROUTE_PATH}.DefaultResponse'):
        _call_delete(flask_app)

    mgr.cleanup_global_section_templates.assert_called_once()
    mgr.delete_section_template.assert_called_once_with(TEMPLATE_PUBLIC_ID)


def test_delete_predefined_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A predefined template is not deletable and aborts 400"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=True, is_global=False)

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.delete_section_template.assert_not_called()


def test_delete_missing_template_maps_to_404(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A missing template aborts 404"""
    del patched_manager_provider
    mgr.get_section_template.return_value = None

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_NOT_FOUND


def test_delete_manager_error_maps_to_500(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerDeleteError is translated to HTTP 500 (not 400)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, is_global=False)
    mgr.delete_section_template.side_effect = SectionTemplatesManagerDeleteError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_SERVER_ERROR
