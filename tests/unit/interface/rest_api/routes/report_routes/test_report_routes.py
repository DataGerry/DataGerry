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
Unit tests for the CmdbReport REST routes and their helpers

Covers report_helper (request-param validation / normalisation, report-type lookup, the
Ref-Section-Field guard over selected columns + condition rules, and the locked-down evaluation of
a stored report query) and the report_routes handlers (status-code mapping, branch selection and
the preview-limit). Handlers are unwrapped past their decorators and driven in a Flask
test_request_context with the managers / helpers patched, so no Mongo and no blueprint registration
run.
"""
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.interface.rest_api.routes.report_routes.report_constants import PREVIEW_LIMIT, ReportQueryKey
from cmdb.interface.rest_api.routes.report_routes.report_helper import (
    normalize_report_params,
    resolve_report_type,
    collect_condition_field_names,
    abort_if_ref_section_fields,
    build_report_query,
    eval_report_query,
)
from cmdb.interface.rest_api.routes.report_routes.report_routes import (
    create_cmdb_report,
    get_cmdb_report,
    get_cmdb_reports,
    count_cmdb_reports_of_type,
    run_cmdb_report_query,
    update_cmdb_report,
    delete_cmdb_report,
)
from cmdb.errors.manager.reports_manager import (
    ReportsManagerInsertError,
    ReportsManagerGetError,
    ReportsManagerIterationError,
    ReportsManagerUpdateError,
    ReportsManagerDeleteError,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.report_routes.report_helper'
ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.report_routes.report_routes'

HTTP_BAD_REQUEST: int = 400
HTTP_NOT_FOUND: int = 404
HTTP_SERVER_ERROR: int = 500

SAMPLE_REPORT: dict[str, Any] = {'public_id': 7, 'name': 'R', 'type_id': 5, 'selected_fields': []}
WRITE_PARAMS: dict[str, Any] = {'type_id': 5, 'selected_fields': [], 'conditions': {}}


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


def _report_type(ref_section_field_names: list[str]) -> MagicMock:
    """Builds a CmdbType stand-in whose get_all_fields_of_type returns the given ref-section names."""
    report_type = MagicMock()
    report_type.get_all_fields_of_type.return_value = ref_section_field_names

    return report_type


def _leaf(field_name: str) -> dict[str, Any]:
    """Builds one leaf condition rule referencing a field."""
    return {'field': field_name, 'operator': '=', 'value': 'x'}


def _valid_params(**overrides: Any) -> dict[str, Any]:
    """Builds a valid report request-param dict (query-string style: all values are strings)."""
    params: dict[str, Any] = {
        'report_category_id': '3',
        'name': 'My Report',
        'type_id': '5',
        'selected_fields': '["text-a", "text-b"]',
        'conditions': '{"condition": "and", "rules": []}',
        'predefined': 'false',
        'mds_mode': MdsMode.ROWS.value,
    }
    params.update(overrides)

    return params


# ------------------------------------------------- normalize_report_params ------------------------------------------ #

def test_normalize_report_params_coerces_types() -> None:
    """Ids become ints, predefined a bool, conditions / selected_fields parsed JSON, mds kept."""
    params = _valid_params()

    normalize_report_params(params)

    assert params['report_category_id'] == 3
    assert params['type_id'] == 5
    assert params['predefined'] is False
    assert params['selected_fields'] == ['text-a', 'text-b']
    assert params['conditions'] == {'condition': 'and', 'rules': []}
    assert params['mds_mode'] == MdsMode.ROWS


def test_normalize_report_params_falls_back_to_rows_for_unknown_mds_mode() -> None:
    """An unrecognised mds_mode is normalised to MdsMode.ROWS."""
    params = _valid_params(mds_mode='NONSENSE')

    normalize_report_params(params)

    assert params['mds_mode'] == MdsMode.ROWS


@pytest.mark.parametrize('missing_key', ['report_category_id', 'name', 'type_id', 'selected_fields',
                                         'conditions', 'predefined', 'mds_mode'])
def test_normalize_report_params_missing_required_maps_to_400(missing_key: str) -> None:
    """A payload missing any required parameter aborts 400 (instead of crashing into 500)."""
    params = _valid_params()
    del params[missing_key]

    with pytest.raises(HTTPException) as exc_info:
        normalize_report_params(params)

    assert exc_info.value.code == HTTP_BAD_REQUEST


@pytest.mark.parametrize('field,value', [
    ('type_id', 'not-an-int'),
    ('conditions', 'not-json'),
    ('selected_fields', 'not-json'),
    ('predefined', 'maybe'),
])
def test_normalize_report_params_malformed_value_maps_to_400(field: str, value: str) -> None:
    """A malformed id / boolean / JSON value aborts 400."""
    params = _valid_params(**{field: value})

    with pytest.raises(HTTPException) as exc_info:
        normalize_report_params(params)

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------- resolve_report_type ---------------------------------------------- #

def test_resolve_report_type_aborts_400_when_type_missing() -> None:
    """A type_id that does not resolve aborts 400 instead of crashing into a 500."""
    reports_manager = MagicMock()
    reports_manager.get_one_from_other_collection.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        resolve_report_type(reports_manager, 999)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_resolve_report_type_returns_instance_when_found() -> None:
    """A resolvable type is hydrated via CmdbType.from_data and returned."""
    reports_manager = MagicMock()
    reports_manager.get_one_from_other_collection.return_value = {'public_id': 5}
    sentinel = object()

    with patch(f'{HELPER_PATH}.CmdbType') as cmdb_type:
        cmdb_type.from_data.return_value = sentinel
        result = resolve_report_type(reports_manager, 5)

    assert result is sentinel


# ------------------------------------------------- collect_condition_field_names ------------------------------------ #

def test_collect_condition_field_names_handles_none_and_empty() -> None:
    """A None or rule-less conditions tree yields no field names."""
    assert collect_condition_field_names(None) == set()
    assert collect_condition_field_names({'condition': 'and', 'rules': []}) == set()


def test_collect_condition_field_names_collects_nested_leaves() -> None:
    """Field names are gathered from leaf rules at every nesting depth."""
    conditions: dict[str, Any] = {
        'condition': 'and',
        'rules': [_leaf('text-a'), {'condition': 'or', 'rules': [_leaf('text-b'), _leaf('linked-section')]}],
    }

    assert collect_condition_field_names(conditions) == {'text-a', 'text-b', 'linked-section'}


# ------------------------------------------------- abort_if_ref_section_fields -------------------------------------- #

def test_aborts_400_when_a_selected_field_is_a_ref_section_field() -> None:
    """A selected column that is a ref-section-field of the type aborts 400."""
    report_type = _report_type(['linked-section'])

    with pytest.raises(HTTPException) as exc_info:
        abort_if_ref_section_fields(report_type, ['text-a', 'linked-section'], None)

    assert exc_info.value.code == HTTP_BAD_REQUEST
    report_type.get_all_fields_of_type.assert_called_once_with(FieldType.REF_SECTION)


def test_aborts_400_when_a_condition_rule_references_a_ref_section_field() -> None:
    """A ref-section-field used only in a (nested) condition rule aborts 400."""
    report_type = _report_type(['linked-section'])
    conditions: dict[str, Any] = {
        'condition': 'and',
        'rules': [{'condition': 'or', 'rules': [_leaf('linked-section')]}],
    }

    with pytest.raises(HTTPException) as exc_info:
        abort_if_ref_section_fields(report_type, ['text-a'], conditions)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_passes_when_nothing_references_a_ref_section_field() -> None:
    """Non-ref-section columns and conditions pass, even when the type defines ref-section-fields."""
    report_type = _report_type(['linked-section'])
    conditions: dict[str, Any] = {'condition': 'and', 'rules': [_leaf('text-b')]}

    abort_if_ref_section_fields(report_type, ['text-a'], conditions)  # must not raise


def test_passes_when_type_has_no_ref_section_fields() -> None:
    """A type without any ref-section-field never rejects, whatever is referenced."""
    report_type = _report_type([])

    abort_if_ref_section_fields(report_type, ['text-a', 'linked-section'], None)  # must not raise


# ------------------------------------------------- eval_report_query ------------------------------------------------ #

def test_eval_report_query_rebuilds_dict_with_datetime() -> None:
    """A stored query string is evaluated back into a dict, including datetime() calls."""
    result = eval_report_query("{'field': 'x', 'when': datetime.datetime(2024, 11, 26)}")

    assert result['field'] == 'x'
    assert result['when'] == datetime(2024, 11, 26)


def test_eval_report_query_is_sandboxed_against_builtins() -> None:
    """The locked-down namespace removes builtins, so a builtin call cannot execute (NameError)."""
    with pytest.raises(NameError):
        eval_report_query("__import__('os').system('echo pwned')")


# ------------------------------------------------- build_report_query ----------------------------------------------- #

def test_build_report_query_wraps_serialized_query_under_data() -> None:
    """build_report_query stores the MongoDBQueryBuilder output as its repr string under 'data'."""
    built: dict[str, Any] = {'type_id': 5}

    with patch(f'{HELPER_PATH}.MongoDBQueryBuilder') as builder_cls:
        builder_cls.return_value.build.return_value = built
        result = build_report_query({'condition': 'and', 'rules': []}, MagicMock())

    assert result == {ReportQueryKey.DATA: str(built)}


def test_build_report_query_round_trips_through_eval_report_query() -> None:
    """A built query (datetime values and all) survives the str-store / eval-load round-trip."""
    built: dict[str, Any] = {'fields': {'$elemMatch': {'name': 'd', 'value': {'$gte': datetime(2024, 11, 26)}}}}

    with patch(f'{HELPER_PATH}.MongoDBQueryBuilder') as builder_cls:
        builder_cls.return_value.build.return_value = built
        stored = build_report_query({'condition': 'and', 'rules': []}, MagicMock())

    assert eval_report_query(stored[ReportQueryKey.DATA]) == built


# ------------------------------------------------- run_cmdb_report_query (preview) ---------------------------------- #

def _run_with_query(flask_app: Flask, url: str) -> MagicMock:
    """Drives the unwrapped run handler with a non-empty query and returns the patched BuilderParameters."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': "{'x': 1}"}}
    mgr.iterate.return_value = SimpleNamespace(results=[{'a': 1}])

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.eval_report_query', return_value={'x': 1}), \
         patch(f'{ROUTE_PATH}.BuilderParameters') as builder_params, \
         patch(f'{ROUTE_PATH}.DefaultResponse'), \
         flask_app.test_request_context(url):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    return builder_params


def test_run_report_preview_caps_results_at_the_database_level(flask_app: Flask) -> None:
    """preview=true runs the query with limit=PREVIEW_LIMIT instead of fetching all rows."""
    builder_params = _run_with_query(flask_app, '/run/1?preview=true')

    assert builder_params.call_args.kwargs['limit'] == PREVIEW_LIMIT


def test_run_report_without_preview_applies_no_limit(flask_app: Flask) -> None:
    """Without preview the query runs unbounded (limit=0)."""
    builder_params = _run_with_query(flask_app, '/run/1')

    assert builder_params.call_args.kwargs['limit'] == 0


def test_run_report_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerGetError while loading the report maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.side_effect = ReportsManagerGetError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/run/1'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_run_report_with_empty_query_returns_empty_without_iterating(flask_app: Flask) -> None:
    """A report whose evaluated query is empty returns an empty result and never iterates objects."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': '{}'}}

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.eval_report_query', return_value={}), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/run/1'):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    mgr.iterate.assert_not_called()
    response_ctor.assert_called_once_with({})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ROUTE HANDLERS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _patch_write_helpers(stack: ExitStack) -> None:
    """Patches the create/update helper chain (normalise, type lookup, guard, query build) as no-ops."""
    stack.enter_context(patch(f'{ROUTE_PATH}.normalize_report_params'))
    stack.enter_context(patch(f'{ROUTE_PATH}.resolve_report_type', return_value=MagicMock()))
    stack.enter_context(patch(f'{ROUTE_PATH}.abort_if_ref_section_fields'))
    stack.enter_context(patch(f'{ROUTE_PATH}.build_report_query', return_value={'data': 'q'}))


# ----------------------------------------------------- create ------------------------------------------------------- #

def test_create_inserts_and_returns_new_id(flask_app: Flask) -> None:
    """A valid create normalises, guards, builds the query, inserts and returns the new public_id."""
    mgr = MagicMock()
    mgr.insert_item.return_value = 7

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.DefaultResponse'))
        stack.enter_context(flask_app.test_request_context('/', method='POST'))
        _unwrap(create_cmdb_report)(params=dict(WRITE_PARAMS), request_user=MagicMock())

    response_ctor.assert_called_once_with(7)


def test_create_insert_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerInsertError is translated to HTTP 400."""
    mgr = MagicMock()
    mgr.insert_item.side_effect = ReportsManagerInsertError('bad')

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/', method='POST'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(create_cmdb_report)(params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_create_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.insert_item.side_effect = RuntimeError('boom')

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/', method='POST'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(create_cmdb_report)(params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


# ------------------------------------------------------- get -------------------------------------------------------- #

def test_get_returns_report(flask_app: Flask) -> None:
    """A found report is handed to DefaultResponse."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/7'):
        _unwrap(get_cmdb_report)(public_id=7, request_user=MagicMock())

    response_ctor.assert_called_once_with(SAMPLE_REPORT)


def test_get_missing_maps_to_404(flask_app: Flask) -> None:
    """A missing report aborts 404."""
    mgr = MagicMock()
    mgr.get_item.return_value = None

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report)(public_id=7, request_user=MagicMock())

    assert exc_info.value.code == HTTP_NOT_FOUND


def test_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerGetError maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.side_effect = ReportsManagerGetError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report)(public_id=7, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------------- list ------------------------------------------------------- #

def test_list_serializes_each_report_via_to_json(flask_app: Flask) -> None:
    """Each iterated report is serialized through CmdbReport.to_json and handed to GetMultiResponse."""
    mgr = MagicMock()
    mgr.iterate_items.return_value = SimpleNamespace(results=[SAMPLE_REPORT], total=1)

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.CmdbReport') as cmdb_report, \
         patch(f'{ROUTE_PATH}.GetMultiResponse') as response_ctor, \
         flask_app.test_request_context('/'):
        cmdb_report.to_json.side_effect = lambda report: report
        _unwrap(get_cmdb_reports)(params=MagicMock(), request_user=MagicMock())

    assert response_ctor.call_args.args[0] == [SAMPLE_REPORT]


def test_list_iteration_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerIterationError maps to HTTP 400."""
    mgr = MagicMock()
    mgr.iterate_items.side_effect = ReportsManagerIterationError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_reports)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------------- count ------------------------------------------------------ #

def test_count_returns_count_for_type(flask_app: Flask) -> None:
    """The route counts reports of the given type and returns the count."""
    mgr = MagicMock()
    mgr.count_documents.return_value = 3

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/5/count_reports_of_type'):
        _unwrap(count_cmdb_reports_of_type)(public_id=5, request_user=MagicMock())

    response_ctor.assert_called_once_with(3)


# ------------------------------------------------------- run -------------------------------------------------------- #

def test_run_missing_report_maps_to_404(flask_app: Flask) -> None:
    """Running a missing report aborts 404."""
    mgr = MagicMock()
    mgr.get_item.return_value = None

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/run/7'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(run_cmdb_report_query)(public_id=7, request_user=MagicMock())

    assert exc_info.value.code == HTTP_NOT_FOUND


# ------------------------------------------------------ update ------------------------------------------------------ #

def test_update_returns_reread_report(flask_app: Flask) -> None:
    """A valid update writes the report and returns the re-read document."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.UpdateSingleResponse'))
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        _unwrap(update_cmdb_report)(public_id=7, params=dict(WRITE_PARAMS), request_user=MagicMock())

    response_ctor.assert_called_once_with(SAMPLE_REPORT)


def test_update_missing_target_maps_to_404(flask_app: Flask) -> None:
    """Updating a non-existent report aborts 404 before any write."""
    mgr = MagicMock()
    mgr.get_item.return_value = None

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(update_cmdb_report)(public_id=7, params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_NOT_FOUND
    mgr.update_item.assert_not_called()


def test_update_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerUpdateError maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT
    mgr.update_item.side_effect = ReportsManagerUpdateError('x')

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(update_cmdb_report)(public_id=7, params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------------ delete ------------------------------------------------------ #

def test_delete_removes_report(flask_app: Flask) -> None:
    """A found report is deleted and the ack is returned."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT
    mgr.delete_item.return_value = True

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/7/', method='DELETE'):
        _unwrap(delete_cmdb_report)(public_id=7, request_user=MagicMock())

    mgr.delete_item.assert_called_once_with(7)
    response_ctor.assert_called_once_with(True)


def test_delete_missing_maps_to_404(flask_app: Flask) -> None:
    """Deleting a missing report aborts 404 without attempting the delete."""
    mgr = MagicMock()
    mgr.get_item.return_value = None

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7/', method='DELETE'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(delete_cmdb_report)(public_id=7, request_user=MagicMock())

    assert exc_info.value.code == HTTP_NOT_FOUND
    mgr.delete_item.assert_not_called()


def test_delete_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerDeleteError maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT
    mgr.delete_item.side_effect = ReportsManagerDeleteError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7/', method='DELETE'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(delete_cmdb_report)(public_id=7, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST
