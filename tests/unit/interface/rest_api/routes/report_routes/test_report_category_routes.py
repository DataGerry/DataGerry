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
Unit tests for the CmdbReportCategory REST routes and their helper

Covers report_category_helper (the write whitelist, the required-name guard, the load-or-404 lookup,
the predefined guard and the in-use guard) and the report_category_routes handlers (status-code
mapping, branch selection and the server-owned keys of a write payload). Handlers are unwrapped past
their decorators and driven in a Flask test_request_context with the manager patched, so no Mongo and
no blueprint registration run.
"""
from contextlib import ExitStack
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    REPORT_CATEGORY_WRITE_KEYS,
    ReportCategoryAction,
    ReportCategoryKey,
)
from cmdb.interface.rest_api.routes.report_routes.report_category_helper import (
    abort_if_category_in_use,
    abort_if_predefined,
    build_category_update_payload,
    load_category_or_404,
    normalize_category_params,
    require_category_name,
    strip_unknown_category_keys,
)
from cmdb.interface.rest_api.routes.report_routes.report_category_routes import (
    create_cmdb_report_category,
    get_cmdb_report_category,
    get_cmdb_report_categories,
    update_cmdb_report_category,
    delete_cmdb_report_category,
)
from cmdb.models.reports_model.cmdb_report import CmdbReport
from cmdb.errors.manager.report_categories_manager import (
    ReportCategoriesManagerInsertError,
    ReportCategoriesManagerGetError,
    ReportCategoriesManagerIterationError,
    ReportCategoriesManagerUpdateError,
    ReportCategoriesManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.report_routes.report_category_routes'

HTTP_BAD_REQUEST: int = 400
HTTP_FORBIDDEN: int = 403
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

CATEGORY_ID: int = 42
BOGUS_PAYLOAD_ID: int = 88888

VALID_PARAMS: dict[str, Any] = {'name': 'Category'}


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the decorator chain (route / verify_api_access / insert_request_user)."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


def _category(predefined: bool = False, name: str = 'Category') -> MagicMock:
    """Builds a CmdbReportCategory stand-in carrying the two attributes the routes read."""
    category = MagicMock()
    category.predefined = predefined
    category.name = name

    return category


def _manager(**attributes: Any) -> MagicMock:
    """Builds a ReportCategoriesManager stand-in with the given return values / side effects."""
    manager = MagicMock()

    for name, value in attributes.items():
        setattr(manager, name, value)

    return manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                              strip_unknown_category_keys                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_only_the_name_is_client_settable() -> None:
    """The write whitelist holds exactly 'name' - everything else is server-owned."""
    assert set(REPORT_CATEGORY_WRITE_KEYS) == {ReportCategoryKey.NAME}


def test_strip_unknown_category_keys_keeps_only_the_whitelisted_key() -> None:
    """The identity, the predefined flag and any unknown parameter are dropped, 'name' survives."""
    params: dict[str, Any] = {
        'name': 'Category',
        'public_id': BOGUS_PAYLOAD_ID,
        'predefined': 'true',
        'injected': 'value',
    }

    assert strip_unknown_category_keys(params) == {'name': 'Category'}


def test_strip_unknown_category_keys_does_not_mutate_the_request_params() -> None:
    """A new dict is returned, so the caller's request parameters stay untouched."""
    params: dict[str, Any] = {'name': 'Category', 'injected': 'value'}

    strip_unknown_category_keys(params)

    assert params == {'name': 'Category', 'injected': 'value'}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                require_category_name                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_require_category_name_returns_the_trimmed_name() -> None:
    """A usable name is returned with its surrounding whitespace removed."""
    assert require_category_name({'name': '  Category  '}) == 'Category'


@pytest.mark.parametrize('params', [
    {},
    {'name': ''},
    {'name': '   '},
    {'name': None},
    {'name': 5},
])
def test_require_category_name_missing_or_blank_maps_to_400(params: dict[str, Any]) -> None:
    """An absent, blank or non-string name aborts 400 instead of persisting a nameless category."""
    with pytest.raises(HTTPException) as exc_info:
        require_category_name(params)

    assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                               normalize_category_params                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_normalize_category_params_strips_and_trims() -> None:
    """The payload is reduced to the trimmed name; server-owned and unknown keys never reach it."""
    params: dict[str, Any] = {'name': ' Category ', 'public_id': BOGUS_PAYLOAD_ID, 'predefined': 'true', 'x': '1'}

    assert normalize_category_params(params) == {'name': 'Category'}


def test_normalize_category_params_rejects_a_payload_whose_name_was_stripped_away() -> None:
    """A payload carrying only disallowed keys has no name left and aborts 400."""
    with pytest.raises(HTTPException) as exc_info:
        normalize_category_params({'public_id': BOGUS_PAYLOAD_ID, 'predefined': 'true'})

    assert exc_info.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                load_category_or_404                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_load_category_or_404_returns_the_model_instance() -> None:
    """An existing category is returned as the model instance by default."""
    category = _category()
    manager = _manager(get_item=MagicMock(return_value=category))

    assert load_category_or_404(manager, CATEGORY_ID) is category
    manager.get_item.assert_called_once_with(CATEGORY_ID, as_dict=False)


def test_load_category_or_404_forwards_as_dict() -> None:
    """as_dict is passed through so the single read can return the raw document."""
    document: dict[str, Any] = {'public_id': CATEGORY_ID, 'name': 'Category'}
    manager = _manager(get_item=MagicMock(return_value=document))

    assert load_category_or_404(manager, CATEGORY_ID, as_dict=True) is document
    manager.get_item.assert_called_once_with(CATEGORY_ID, as_dict=True)


def test_load_category_or_404_missing_maps_to_404() -> None:
    """A missing category aborts 404."""
    manager = _manager(get_item=MagicMock(return_value=None))

    with pytest.raises(HTTPException) as exc_info:
        load_category_or_404(manager, CATEGORY_ID)

    assert exc_info.value.code == HTTP_NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 abort_if_predefined                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('action', [ReportCategoryAction.UPDATED, ReportCategoryAction.DELETED])
def test_abort_if_predefined_refuses_a_predefined_category(action: ReportCategoryAction) -> None:
    """A predefined category is read-only: both write actions are refused with 403, naming the verb."""
    with pytest.raises(HTTPException) as exc_info:
        abort_if_predefined(_category(predefined=True), action)

    assert exc_info.value.code == HTTP_FORBIDDEN
    assert action.value in exc_info.value.description


def test_abort_if_predefined_passes_a_user_created_category() -> None:
    """A user-created category is writable."""
    abort_if_predefined(_category(predefined=False), ReportCategoryAction.UPDATED)  # must not raise


# -------------------------------------------------------------------------------------------------------------------- #
#                                               abort_if_category_in_use                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_abort_if_category_in_use_counts_referencing_reports_server_side() -> None:
    """The guard counts in the report collection by report_category_id, loading no report document."""
    manager = _manager(count_from_other_collection=MagicMock(return_value=0))

    abort_if_category_in_use(manager, CATEGORY_ID)  # must not raise

    manager.count_from_other_collection.assert_called_once_with(
        CmdbReport.COLLECTION, {'report_category_id': CATEGORY_ID}
    )


def test_abort_if_category_in_use_referenced_maps_to_403() -> None:
    """A category a report still references can not be deleted."""
    manager = _manager(count_from_other_collection=MagicMock(return_value=1))

    with pytest.raises(HTTPException) as exc_info:
        abort_if_category_in_use(manager, CATEGORY_ID)

    assert exc_info.value.code == HTTP_FORBIDDEN


# -------------------------------------------------------------------------------------------------------------------- #
#                                             build_category_update_payload                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_category_update_payload_pins_the_server_owned_keys() -> None:
    """The identity comes from the URL and predefined from the stored doc, whatever the payload says."""
    params: dict[str, Any] = {'name': 'Renamed', 'public_id': BOGUS_PAYLOAD_ID, 'predefined': 'true'}

    payload = build_category_update_payload(params, CATEGORY_ID, _category(predefined=False))

    assert payload == {'name': 'Renamed', 'public_id': CATEGORY_ID, 'predefined': False}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    ROUTE HANDLERS                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def _drive(
        flask_app: Flask,
        handler: Callable[..., Any],
        manager: MagicMock,
        url: str = '/',
        method: str = 'GET',
        response_ctor_name: str = 'DefaultResponse',
        **kwargs: Any,
    ) -> MagicMock:
    """Drives an unwrapped handler with the manager patched, returning the patched response class."""
    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.{response_ctor_name}'))
        stack.enter_context(flask_app.test_request_context(url, method=method))
        _unwrap(handler)(request_user=MagicMock(), **kwargs)

    return response_ctor


def _expect_status(
        flask_app: Flask,
        handler: Callable[..., Any],
        manager: MagicMock,
        expected_code: int,
        url: str = '/',
        method: str = 'GET',
        **kwargs: Any,
    ) -> None:
    """Asserts that driving the handler aborts with the expected status code."""
    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        stack.enter_context(flask_app.test_request_context(url, method=method))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(handler)(request_user=MagicMock(), **kwargs)

    assert exc_info.value.code == expected_code


# ------------------------------------------------------ create ------------------------------------------------------ #

def test_create_inserts_a_sanitised_payload_and_returns_the_new_id(flask_app: Flask) -> None:
    """A create persists the trimmed name plus predefined=False and returns the new public_id."""
    manager = _manager(insert_item=MagicMock(return_value=7))

    response_ctor = _drive(
        flask_app, create_cmdb_report_category, manager, method='POST',
        params={'name': ' Category ', 'public_id': BOGUS_PAYLOAD_ID, 'predefined': 'true', 'injected': 'x'},
    )

    manager.insert_item.assert_called_once_with({'name': 'Category', 'predefined': False})
    response_ctor.assert_called_once_with(7)


def test_create_without_a_name_maps_to_400(flask_app: Flask) -> None:
    """A payload without a usable name is refused before the insert."""
    manager = _manager(insert_item=MagicMock())

    _expect_status(flask_app, create_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='POST', params={})

    manager.insert_item.assert_not_called()


def test_create_insert_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerInsertError is translated to HTTP 400."""
    manager = _manager(insert_item=MagicMock(side_effect=ReportCategoriesManagerInsertError('bad')))

    _expect_status(flask_app, create_cmdb_report_category, manager, HTTP_BAD_REQUEST,
                   method='POST', params=dict(VALID_PARAMS))


def test_create_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _manager(insert_item=MagicMock(side_effect=RuntimeError('boom')))

    _expect_status(flask_app, create_cmdb_report_category, manager, HTTP_SERVER_ERROR,
                   method='POST', params=dict(VALID_PARAMS))


# -------------------------------------------------------- get ------------------------------------------------------- #

def test_get_returns_the_stored_document(flask_app: Flask) -> None:
    """A single read answers with the raw document of the requested category."""
    document: dict[str, Any] = {'public_id': CATEGORY_ID, 'name': 'Category'}
    manager = _manager(get_item=MagicMock(return_value=document))

    response_ctor = _drive(flask_app, get_cmdb_report_category, manager, public_id=CATEGORY_ID)

    response_ctor.assert_called_once_with(document)


def test_get_missing_maps_to_404(flask_app: Flask) -> None:
    """A missing category answers 404."""
    manager = _manager(get_item=MagicMock(return_value=None))

    _expect_status(flask_app, get_cmdb_report_category, manager, HTTP_NOT_FOUND, public_id=CATEGORY_ID)


def test_get_manager_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerGetError is translated to HTTP 400."""
    manager = _manager(get_item=MagicMock(side_effect=ReportCategoriesManagerGetError('x')))

    _expect_status(flask_app, get_cmdb_report_category, manager, HTTP_BAD_REQUEST, public_id=CATEGORY_ID)


def test_get_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _manager(get_item=MagicMock(side_effect=RuntimeError('boom')))

    _expect_status(flask_app, get_cmdb_report_category, manager, HTTP_SERVER_ERROR, public_id=CATEGORY_ID)


# ------------------------------------------------------ get list ---------------------------------------------------- #

def _drive_list(flask_app: Flask, manager: MagicMock) -> MagicMock:
    """Drives the unwrapped list handler with the collection-parameter plumbing patched out."""
    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        stack.enter_context(patch(f'{ROUTE_PATH}.CollectionParameters'))
        stack.enter_context(patch(f'{ROUTE_PATH}.BuilderParameters'))
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.GetMultiResponse'))
        stack.enter_context(flask_app.test_request_context('/'))
        _unwrap(get_cmdb_report_categories)(params=MagicMock(), request_user=MagicMock())

    return response_ctor


def test_list_serialises_every_iterated_category(flask_app: Flask) -> None:
    """Each iterated category is serialised through CmdbReportCategory.to_json into the envelope."""
    iteration_result = MagicMock()
    iteration_result.results = [_category(name='A'), _category(name='B')]
    iteration_result.total = 2
    manager = _manager(iterate_items=MagicMock(return_value=iteration_result))

    response_ctor = _drive_list(flask_app, manager)

    category_list = response_ctor.call_args.args[0]

    assert [entry['name'] for entry in category_list] == ['A', 'B']
    assert response_ctor.call_args.args[1] == 2


def test_list_iteration_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerIterationError is translated to HTTP 400."""
    manager = _manager(iterate_items=MagicMock(side_effect=ReportCategoriesManagerIterationError('x')))

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        stack.enter_context(patch(f'{ROUTE_PATH}.CollectionParameters'))
        stack.enter_context(patch(f'{ROUTE_PATH}.BuilderParameters'))
        stack.enter_context(flask_app.test_request_context('/'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report_categories)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_list_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _manager(iterate_items=MagicMock(side_effect=RuntimeError('boom')))

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        stack.enter_context(patch(f'{ROUTE_PATH}.CollectionParameters'))
        stack.enter_context(patch(f'{ROUTE_PATH}.BuilderParameters'))
        stack.enter_context(flask_app.test_request_context('/'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report_categories)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


def test_list_passes_an_http_exception_through_unchanged(flask_app: Flask) -> None:
    """An HTTPException raised inside the list route keeps its status instead of becoming a 500."""
    manager = _manager(iterate_items=MagicMock())

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=manager))
        stack.enter_context(patch(f'{ROUTE_PATH}.CollectionParameters'))
        stack.enter_context(patch(f'{ROUTE_PATH}.BuilderParameters', side_effect=BadRequest('nope')))
        stack.enter_context(flask_app.test_request_context('/'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report_categories)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------------ update ------------------------------------------------------ #

def test_update_writes_a_sanitised_and_pinned_payload(flask_app: Flask) -> None:
    """The update persists the trimmed name with the identity and predefined pinned server-side."""
    manager = _manager(get_item=MagicMock(return_value=_category(predefined=False)), update_item=MagicMock())

    response_ctor = _drive(
        flask_app, update_cmdb_report_category, manager, method='PUT',
        response_ctor_name='UpdateSingleResponse', public_id=CATEGORY_ID,
        params={'name': ' Renamed ', 'public_id': BOGUS_PAYLOAD_ID, 'predefined': 'true', 'injected': 'x'},
    )

    expected_payload: dict[str, Any] = {'name': 'Renamed', 'public_id': CATEGORY_ID, 'predefined': False}

    manager.update_item.assert_called_once_with(CATEGORY_ID, expected_payload)
    response_ctor.assert_called_once_with(expected_payload)


def test_update_of_a_predefined_category_maps_to_403(flask_app: Flask) -> None:
    """A predefined category may not be renamed - the write is refused before it happens."""
    manager = _manager(get_item=MagicMock(return_value=_category(predefined=True)), update_item=MagicMock())

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_FORBIDDEN, method='PUT',
                   public_id=CATEGORY_ID, params={'name': 'Renamed'})

    manager.update_item.assert_not_called()


def test_update_without_a_name_maps_to_400(flask_app: Flask) -> None:
    """A payload without a usable name is refused before the update."""
    manager = _manager(get_item=MagicMock(return_value=_category()), update_item=MagicMock())

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='PUT',
                   public_id=CATEGORY_ID, params={})

    manager.update_item.assert_not_called()


def test_update_missing_maps_to_404(flask_app: Flask) -> None:
    """Updating a missing category answers 404."""
    manager = _manager(get_item=MagicMock(return_value=None), update_item=MagicMock())

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_NOT_FOUND, method='PUT',
                   public_id=CATEGORY_ID, params=dict(VALID_PARAMS))


def test_update_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerGetError while loading the category is translated to HTTP 400."""
    manager = _manager(get_item=MagicMock(side_effect=ReportCategoriesManagerGetError('x')))

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='PUT',
                   public_id=CATEGORY_ID, params=dict(VALID_PARAMS))


def test_update_update_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerUpdateError is translated to HTTP 400."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        update_item=MagicMock(side_effect=ReportCategoriesManagerUpdateError('x')),
    )

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='PUT',
                   public_id=CATEGORY_ID, params=dict(VALID_PARAMS))


def test_update_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        update_item=MagicMock(side_effect=RuntimeError('boom')),
    )

    _expect_status(flask_app, update_cmdb_report_category, manager, HTTP_SERVER_ERROR, method='PUT',
                   public_id=CATEGORY_ID, params=dict(VALID_PARAMS))


# ------------------------------------------------------ delete ------------------------------------------------------ #

def test_delete_removes_a_free_category(flask_app: Flask) -> None:
    """A user-created category no report references is deleted and the ack returned."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        count_from_other_collection=MagicMock(return_value=0),
        delete_item=MagicMock(return_value=True),
    )

    response_ctor = _drive(flask_app, delete_cmdb_report_category, manager, method='DELETE',
                           public_id=CATEGORY_ID)

    manager.delete_item.assert_called_once_with(CATEGORY_ID)
    response_ctor.assert_called_once_with(True)


def test_delete_of_a_predefined_category_maps_to_403(flask_app: Flask) -> None:
    """A predefined category may not be deleted, and the in-use count is never even asked for."""
    manager = _manager(
        get_item=MagicMock(return_value=_category(predefined=True)),
        count_from_other_collection=MagicMock(return_value=0),
        delete_item=MagicMock(),
    )

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_FORBIDDEN, method='DELETE',
                   public_id=CATEGORY_ID)

    manager.count_from_other_collection.assert_not_called()
    manager.delete_item.assert_not_called()


def test_delete_of_a_used_category_maps_to_403(flask_app: Flask) -> None:
    """A category a report still references may not be deleted."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        count_from_other_collection=MagicMock(return_value=3),
        delete_item=MagicMock(),
    )

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_FORBIDDEN, method='DELETE',
                   public_id=CATEGORY_ID)

    manager.delete_item.assert_not_called()


def test_delete_missing_maps_to_404(flask_app: Flask) -> None:
    """Deleting a missing category answers 404."""
    manager = _manager(get_item=MagicMock(return_value=None), delete_item=MagicMock())

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_NOT_FOUND, method='DELETE',
                   public_id=CATEGORY_ID)


def test_delete_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerGetError while loading the category is translated to HTTP 400."""
    manager = _manager(get_item=MagicMock(side_effect=ReportCategoriesManagerGetError('x')))

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='DELETE',
                   public_id=CATEGORY_ID)


def test_delete_delete_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportCategoriesManagerDeleteError is translated to HTTP 400."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        count_from_other_collection=MagicMock(return_value=0),
        delete_item=MagicMock(side_effect=ReportCategoriesManagerDeleteError('x')),
    )

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_BAD_REQUEST, method='DELETE',
                   public_id=CATEGORY_ID)


def test_delete_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    manager = _manager(
        get_item=MagicMock(return_value=_category()),
        count_from_other_collection=MagicMock(return_value=0),
        delete_item=MagicMock(side_effect=RuntimeError('boom')),
    )

    _expect_status(flask_app, delete_cmdb_report_category, manager, HTTP_SERVER_ERROR, method='DELETE',
                   public_id=CATEGORY_ID)
