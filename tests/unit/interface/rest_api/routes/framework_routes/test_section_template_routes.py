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

Since 2026-08-25 also: the template NAME is required and immutable (it is the key consuming types
reference it by, so a rename would orphan every one of them and the propagation would silently apply to
nobody), the 'fields' payload has to be a list of objects, and a failure in the second half of either
write path is reported as a partial application
"""
# pylint: disable=protected-access
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

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


UPDATE_TEMPLATE_NAME: str = 'tpl-under-update'


def _stored_template(**attributes: Any) -> MagicMock:
    """
    Builds the stored-template mock the update guard reads

    ``name`` has to be assigned rather than passed to MagicMock(), where it names the mock itself.
    """
    template = MagicMock(**attributes)
    template.name = attributes.pop('template_name', UPDATE_TEMPLATE_NAME)

    return template


def _update_params(**overrides: Any) -> dict[str, Any]:
    """Builds a valid update payload (query-string style)."""
    params: dict[str, Any] = {
        'public_id': str(TEMPLATE_PUBLIC_ID),
        # The name is required and immutable, so a valid payload repeats the stored one
        'name': UPDATE_TEMPLATE_NAME,
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


def test_create_insert_error_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerInsertError is translated to HTTP 400 (a failed insert operation)"""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.get_next_public_id.return_value = TEMPLATE_PUBLIC_ID
    mgr.insert_section_template.side_effect = SectionTemplatesManagerInsertError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params())

    assert excinfo.value.code == HTTP_BAD_REQUEST


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
         patch(f'{ROUTE_PATH}.CmdbSectionTemplate.to_json', return_value={'public_id': 1}), \
         patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor:
        _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    response_ctor.assert_called_once()


def test_get_all_iteration_error_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """A SectionTemplatesManagerIterationError is translated to HTTP 400 (a failed iterate operation)"""
    del patched_manager_provider
    mgr.iterate.side_effect = SectionTemplatesManagerIterationError('boom')

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.BuilderParameters'), \
         patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    assert excinfo.value.code == HTTP_BAD_REQUEST


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


def test_get_manager_error_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerGetError is translated to HTTP 400 (a failed get operation)"""
    del patched_manager_provider
    mgr.get_section_template.side_effect = SectionTemplatesManagerGetError('boom')

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_BAD_REQUEST


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
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')

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


def test_update_predefined_template_not_editable_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """A predefined template cannot be edited via the API: any update aborts 400 without persisting"""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=True, type='section')

    # predefined='true' matches the stored flag, so this isolates the not-editable guard
    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(predefined='true'))

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()


def test_update_changing_predefined_maps_to_400(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """Turning a non-predefined template into a predefined one aborts 400 (immutable flag)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(predefined='true'))

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_update_changing_type_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """Changing the immutable 'type' aborts 400 (not swallowed into 500)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='multi-data-section')

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


def test_update_manager_error_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerUpdateError is translated to HTTP 400 (a failed update operation)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')
    mgr.update_section_template.side_effect = SectionTemplatesManagerUpdateError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_BAD_REQUEST


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


def test_delete_manager_error_maps_to_400(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """A SectionTemplatesManagerDeleteError is translated to HTTP 400 (a failed delete operation)"""
    del patched_manager_provider
    mgr.get_section_template.return_value = MagicMock(predefined=False, is_global=False)
    mgr.delete_section_template.side_effect = SectionTemplatesManagerDeleteError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                     name immutability + propagation                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

def test_update_requires_the_name(flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any) -> None:
    """
    A payload without a name is refused (regression)

    It used to be accepted and written, and handle_section_template_changes then read the name off the
    payload, found none, and returned - so the update reported success while no consuming type was
    touched.
    """
    del patched_manager_provider
    params = _update_params()
    del params['name']

    with flask_app.test_request_context('/', method='PUT'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(update_section_template)(params=params, request_user=MagicMock())

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()


def test_update_can_not_rename_the_template(flask_app: Flask, mgr: MagicMock,
                                            patched_manager_provider: Any) -> None:
    """
    Renaming is refused: the name is what consuming types reference

    A rename would leave the template under a new name while every type keeps the old one in
    global_template_ids, and the propagation would look up the NEW name and find nobody.
    """
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(name='a-different-name'))

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()
    mgr.handle_section_template_changes.assert_not_called()


def test_update_keeping_the_name_propagates(flask_app: Flask, mgr: MagicMock,
                                            patched_manager_provider: Any) -> None:
    """The guard must not refuse a template its own name - and then the propagation runs."""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')

    with patch(f'{ROUTE_PATH}.UpdateSingleResponse'):
        _call_update(flask_app, _update_params())

    mgr.update_section_template.assert_called_once()
    mgr.handle_section_template_changes.assert_called_once()


def test_update_reports_a_failed_propagation_as_a_partial_application(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """
    The template is already written when the propagation runs, so a failure says so

    Reporting a plain failed update would be a lie: the template really did change.
    """
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')
    mgr.handle_section_template_changes.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_SERVER_ERROR
    assert 'was updated' in excinfo.value.description


@pytest.mark.parametrize('fields', ['"5"', '{}', '[1]', 'null'], ids=['string', 'object', 'list-of-int', 'null'])
def test_update_rejects_a_fields_payload_that_is_not_a_list_of_objects(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any, fields: str,
) -> None:
    """
    'fields' has to be a list of field objects (regression)

    Only the JSON syntax was checked, so a bare value such as "5" parsed cleanly and was stored as the
    field list.
    """
    del patched_manager_provider

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(fields=fields))

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()


def test_create_rejects_a_fields_payload_that_is_not_a_list_of_objects(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """The same shape rule on the way in."""
    del patched_manager_provider
    mgr.get_one_by.return_value = None

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params(fields='"5"'))

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.insert_section_template.assert_not_called()


def test_delete_reports_a_failure_after_the_cleanup_as_a_partial_application(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """
    The consumers are cleaned before the document goes, so a failure after that is a partial application
    """
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, is_global=True)
    mgr.delete_section_template.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_SERVER_ERROR
    assert 'removed from the types' in excinfo.value.description


def test_delete_of_a_non_global_template_maps_a_failure_normally(
    flask_app: Flask, mgr: MagicMock, patched_manager_provider: Any,
) -> None:
    """Nothing was cleaned up, so the failure is an ordinary delete error rather than a partial one."""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, is_global=False)
    mgr.delete_section_template.side_effect = SectionTemplatesManagerDeleteError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.cleanup_global_section_templates.assert_not_called()


def test_get_single_returns_the_template_document(flask_app: Flask, mgr: MagicMock,
                                                  patched_manager_provider: Any) -> None:
    """
    The read hands out the template as a document, not the model instance

    It used to pass the instance into DefaultResponse, which only serialised through the response
    encoder's fallback.
    """
    del patched_manager_provider
    stored = _stored_template(predefined=False, type='section')
    mgr.get_section_template.return_value = stored
    document = {'public_id': TEMPLATE_PUBLIC_ID, 'name': UPDATE_TEMPLATE_NAME}

    with patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         patch(f'{ROUTE_PATH}.CmdbSectionTemplate.to_json', return_value=document) as to_json:
        with flask_app.test_request_context('/', method='GET'):
            _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    to_json.assert_called_once_with(stored)
    response_ctor.assert_called_once_with(document)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        unexpected failures -> 500                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

def test_create_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                             patched_manager_provider: Any) -> None:
    """An unmapped failure while inserting is a 500, not a leaked traceback."""
    del patched_manager_provider
    mgr.get_one_by.return_value = None
    mgr.insert_section_template.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_create(flask_app, _create_params())

    assert excinfo.value.code == HTTP_SERVER_ERROR


def test_get_all_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                              patched_manager_provider: Any) -> None:
    """An unmapped failure while iterating is a 500."""
    del patched_manager_provider
    mgr.iterate.side_effect = RuntimeError('boom')

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.BuilderParameters'), \
         patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    assert excinfo.value.code == HTTP_SERVER_ERROR


def test_get_single_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                                 patched_manager_provider: Any) -> None:
    """An unmapped failure while reading one template is a 500."""
    del patched_manager_provider
    mgr.get_section_template.side_effect = RuntimeError('boom')

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_section_template)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_SERVER_ERROR


def test_count_manager_error_maps_to_400(flask_app: Flask, mgr: MagicMock,
                                         patched_manager_provider: Any) -> None:
    """A failed read behind the count is a 400."""
    del patched_manager_provider
    mgr.get_section_template.side_effect = SectionTemplatesManagerGetError('boom')

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_global_section_template_count)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_count_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                            patched_manager_provider: Any) -> None:
    """An unmapped failure while counting is a 500."""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(is_global=True)
    mgr.get_global_template_usage_count.side_effect = RuntimeError('boom')

    with flask_app.test_request_context('/', method='GET'):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_global_section_template_count)(public_id=TEMPLATE_PUBLIC_ID, request_user=MagicMock())

    assert excinfo.value.code == HTTP_SERVER_ERROR


def test_update_read_error_maps_to_400(flask_app: Flask, mgr: MagicMock,
                                       patched_manager_provider: Any) -> None:
    """A failed read of the target template is a 400."""
    del patched_manager_provider
    mgr.get_section_template.side_effect = SectionTemplatesManagerGetError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_update_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                             patched_manager_provider: Any) -> None:
    """An unmapped failure while writing is a 500 naming the id."""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, type='section')
    mgr.update_section_template.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params())

    assert excinfo.value.code == HTTP_SERVER_ERROR
    assert str(TEMPLATE_PUBLIC_ID) in excinfo.value.description


def test_delete_read_error_maps_to_400(flask_app: Flask, mgr: MagicMock,
                                       patched_manager_provider: Any) -> None:
    """A failed read of the target template is a 400."""
    del patched_manager_provider
    mgr.get_section_template.side_effect = SectionTemplatesManagerGetError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_BAD_REQUEST


def test_delete_unexpected_error_maps_to_500(flask_app: Flask, mgr: MagicMock,
                                             patched_manager_provider: Any) -> None:
    """An unmapped failure before the cleanup is a 500."""
    del patched_manager_provider
    mgr.get_section_template.return_value = _stored_template(predefined=False, is_global=True)
    mgr.cleanup_global_section_templates.side_effect = RuntimeError('boom')

    with pytest.raises(HTTPException) as excinfo:
        _call_delete(flask_app)

    assert excinfo.value.code == HTTP_SERVER_ERROR


@pytest.mark.parametrize('boolean_key', ['is_global', 'predefined'])
def test_update_non_boolean_flag_maps_to_400(flask_app: Flask, mgr: MagicMock,
                                             patched_manager_provider: Any, boolean_key: str) -> None:
    """The boolean flags arrive as strings, so an unrecognised value is a client error."""
    del patched_manager_provider

    with pytest.raises(HTTPException) as excinfo:
        _call_update(flask_app, _update_params(**{boolean_key: 'maybe'}))

    assert excinfo.value.code == HTTP_BAD_REQUEST
    mgr.update_section_template.assert_not_called()


def test_get_all_http_exception_keeps_its_status(flask_app: Flask, mgr: MagicMock,
                                                 patched_manager_provider: Any) -> None:
    """An HTTPException from a collaborator passes through instead of becoming a 500."""
    del patched_manager_provider
    mgr.iterate.side_effect = NotFound()

    with flask_app.test_request_context('/', method='GET'), \
         patch(f'{ROUTE_PATH}.BuilderParameters'), \
         patch(f'{ROUTE_PATH}.CollectionParameters.get_builder_params', return_value={}):
        with pytest.raises(HTTPException) as excinfo:
            _unwrap(get_all_section_templates)(params=MagicMock(), request_user=MagicMock())

    assert excinfo.value.code == HTTP_NOT_FOUND
