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

Covers report_helper (the write whitelist, request-param validation / normalisation, the boolean
query-flag parser, the load-or-404 lookup, the category / type foreign-key guards, the
Ref-Section-Field guard over selected columns + condition rules, the locked-down evaluation of a
stored report query and the two write-payload builders) and the report_routes handlers (status-code
mapping, branch selection, the server-owned keys of a write payload and the preview-limit). Handlers
are unwrapped past their decorators and driven in a Flask test_request_context with the managers /
helpers patched, so no Mongo and no blueprint registration run.
"""
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import BadRequest, HTTPException

from cmdb.manager.rights_manager import RightsManager
from cmdb.models.type_model import CmdbType
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.reports_model.cmdb_report_category import CmdbReportCategory
from cmdb.models.reports_model.mds_mode_enum import MdsMode
from cmdb.models.reports_model.report_constants import ReportQueryKey
from cmdb.interface.rest_api.routes.report_routes.report_constants import (
    PREVIEW_LIMIT,
    PREVIEW_PARAM,
    REPORT_REQUIRED_PARAMS,
    REPORT_WRITE_KEYS,
    ReportKey,
    ReportRight,
)
from cmdb.interface.rest_api.routes.report_routes.report_helper import (
    abort_if_report_category_missing,
    abort_if_ref_section_fields,
    build_report_create_payload,
    build_report_payload,
    build_report_query,
    build_report_update_payload,
    collect_condition_field_names,
    eval_report_query,
    load_report_or_404,
    normalize_report_params,
    parse_boolean_param,
    resolve_report_query,
    resolve_report_type,
    strip_unknown_report_keys,
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
from cmdb.errors.manager import BaseManagerGetError
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

REPORT_ID: int = 7
TYPE_ID: int = 5
CATEGORY_ID: int = 3
BOGUS_PAYLOAD_ID: int = 88888

SAMPLE_REPORT: dict[str, Any] = {'public_id': REPORT_ID, 'name': 'R', 'type_id': TYPE_ID, 'selected_fields': []}
WRITE_PARAMS: dict[str, Any] = {'type_id': TYPE_ID, 'selected_fields': [], 'conditions': {}}
BUILT_PAYLOAD: dict[str, Any] = {'name': 'R', 'type_id': TYPE_ID, 'predefined': False}


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
    """Ids become ints, conditions / selected_fields parsed JSON, mds kept."""
    payload = normalize_report_params(_valid_params())

    assert payload['report_category_id'] == CATEGORY_ID
    assert payload['type_id'] == TYPE_ID
    assert payload['selected_fields'] == ['text-a', 'text-b']
    assert payload['conditions'] == {'condition': 'and', 'rules': []}
    assert payload['mds_mode'] == MdsMode.ROWS


def test_normalize_report_params_returns_a_new_payload_without_mutating_the_request() -> None:
    """The raw request parameters are left untouched - the normalised values live in the return value."""
    params = _valid_params()

    payload = normalize_report_params(params)

    assert params['type_id'] == str(TYPE_ID)
    assert payload is not params


def test_normalize_report_params_drops_the_server_owned_and_unknown_keys() -> None:
    """'predefined', a payload public_id, a client report_query and any extra key are dropped."""
    payload = normalize_report_params(_valid_params(
        predefined='true', public_id=str(BOGUS_PAYLOAD_ID), report_query='{"data": "x"}', injected='value',
    ))

    assert set(payload) == set(REPORT_WRITE_KEYS)


def test_normalize_report_params_falls_back_to_rows_for_unknown_mds_mode() -> None:
    """An unrecognised mds_mode is normalised to MdsMode.ROWS."""
    payload = normalize_report_params(_valid_params(mds_mode='NONSENSE'))

    assert payload['mds_mode'] == MdsMode.ROWS


@pytest.mark.parametrize('missing_key', ['report_category_id', 'name', 'type_id', 'selected_fields',
                                         'conditions', 'mds_mode'])
def test_normalize_report_params_missing_required_maps_to_400(missing_key: str) -> None:
    """A payload missing any required parameter aborts 400 (instead of crashing into 500)."""
    params = _valid_params()
    del params[missing_key]

    with pytest.raises(HTTPException) as exc_info:
        normalize_report_params(params)

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_normalize_report_params_ignores_a_missing_predefined() -> None:
    """'predefined' is no longer a request parameter, so its absence is not an error."""
    params = _valid_params()
    del params['predefined']

    assert normalize_report_params(params)['name'] == 'My Report'


@pytest.mark.parametrize('field,value', [
    ('type_id', 'not-an-int'),
    ('report_category_id', 'not-an-int'),
    ('conditions', 'not-json'),
    ('selected_fields', 'not-json'),
])
def test_normalize_report_params_malformed_value_maps_to_400(field: str, value: str) -> None:
    """A malformed id or JSON value aborts 400."""
    params = _valid_params(**{field: value})

    with pytest.raises(HTTPException) as exc_info:
        normalize_report_params(params)

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------- ReportRight ------------------------------------------------------ #

def test_every_report_right_names_an_existing_right() -> None:
    """A ReportRight value that matches no declared right would silently deny every user.

    ``user_has_right`` resolves the string against the rights tree, so a typo here does not raise -
    it just never matches, turning the guarded route into a permanent 403 (backlog #109).
    """
    rights_manager = RightsManager()

    for member in ReportRight:
        assert rights_manager.get_right(member.value) is not None, member.value


def test_report_rights_cover_the_four_crud_operations() -> None:
    """The enum stays aligned with the ReportRight entries declared in all_rights."""
    assert {member.name for member in ReportRight} == {'VIEW', 'ADD', 'EDIT', 'DELETE'}
    assert all(member.value.startswith('base.framework.report.') for member in ReportRight)


# ------------------------------------------------- strip_unknown_report_keys ---------------------------------------- #

def test_write_keys_and_required_params_stay_in_sync() -> None:
    """Every writable key is required and vice versa - the two constants cannot drift apart."""
    assert REPORT_WRITE_KEYS == frozenset(REPORT_REQUIRED_PARAMS)
    assert ReportKey.PREDEFINED not in REPORT_WRITE_KEYS
    assert ReportKey.REPORT_QUERY not in REPORT_WRITE_KEYS


def test_strip_unknown_report_keys_keeps_only_the_whitelisted_keys() -> None:
    """Server-owned and unknown keys are dropped; the six writable ones survive."""
    params = _valid_params(public_id='1', report_query='{}', injected='value')

    assert set(strip_unknown_report_keys(params)) == set(REPORT_WRITE_KEYS)


# ------------------------------------------------- parse_boolean_param ---------------------------------------------- #

@pytest.mark.parametrize('raw_value,expected', [('true', True), ('false', False), ('TRUE', True), (True, True)])
def test_parse_boolean_param_accepts_the_boolean_literals(raw_value: Any, expected: bool) -> None:
    """'true' / 'false' (any case) and native bools are accepted."""
    assert parse_boolean_param(raw_value, PREVIEW_PARAM) is expected


@pytest.mark.parametrize('raw_value', ['1', 'yes', '', 'maybe', None])
def test_parse_boolean_param_rejects_anything_else_with_400(raw_value: Any) -> None:
    """An unrecognised flag is a bad request, not an internal error from str_to_bool's ValueError."""
    with pytest.raises(HTTPException) as exc_info:
        parse_boolean_param(raw_value, PREVIEW_PARAM)

    assert exc_info.value.code == HTTP_BAD_REQUEST
    assert PREVIEW_PARAM in exc_info.value.description


# ------------------------------------------------- load_report_or_404 ----------------------------------------------- #

def test_load_report_or_404_returns_the_raw_document() -> None:
    """The stored document is returned as-is - no model is built for it."""
    reports_manager = MagicMock()
    reports_manager.get_item.return_value = SAMPLE_REPORT

    assert load_report_or_404(reports_manager, REPORT_ID) is SAMPLE_REPORT
    reports_manager.get_item.assert_called_once_with(REPORT_ID, as_dict=True)


def test_load_report_or_404_missing_maps_to_404() -> None:
    """A missing report aborts 404."""
    reports_manager = MagicMock()
    reports_manager.get_item.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        load_report_or_404(reports_manager, REPORT_ID)

    assert exc_info.value.code == HTTP_NOT_FOUND


# ------------------------------------------------- abort_if_report_category_missing --------------------------------- #

def test_abort_if_report_category_missing_passes_for_an_existing_category() -> None:
    """An existing category is only checked for existence, in the report-category collection."""
    reports_manager = MagicMock()
    reports_manager.get_one_from_other_collection.return_value = {'public_id': CATEGORY_ID}

    abort_if_report_category_missing(reports_manager, CATEGORY_ID)  # must not raise

    collection, category_id = reports_manager.get_one_from_other_collection.call_args.args
    assert collection == 'framework.reportCategories'
    assert category_id == CATEGORY_ID


def test_abort_if_report_category_missing_maps_to_400() -> None:
    """A report pointing at a non-existent category is rejected with 400."""
    reports_manager = MagicMock()
    reports_manager.get_one_from_other_collection.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        abort_if_report_category_missing(reports_manager, CATEGORY_ID)

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


def test_collect_condition_field_names_skips_a_rule_that_is_neither_group_nor_leaf() -> None:
    """A rule carrying neither 'condition' nor 'field' contributes nothing instead of raising."""
    conditions: dict[str, Any] = {'condition': 'and', 'rules': [{}, {'operator': '='}, _leaf('text-a')]}

    assert collect_condition_field_names(conditions) == {'text-a'}


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


# ------------------------------------------------- resolve_report_query --------------------------------------------- #

def test_resolve_report_query_evaluates_the_stored_query() -> None:
    """A report carrying a stored query gets it evaluated back into a dict."""
    report: dict[str, Any] = {'report_query': {'data': "{'type_id': 5}"}}

    assert resolve_report_query(report, REPORT_ID) == {'type_id': 5}


@pytest.mark.parametrize('report', [
    {},
    {'report_query': None},
    {'report_query': {}},
    {'report_query': {'data': ''}},
    {'report_query': {'data': '   '}},
    {'report_query': {'data': None}},
    {'report_query': 'not-a-dict'},
])
def test_resolve_report_query_treats_a_missing_stored_query_as_empty(report: dict[str, Any]) -> None:
    """A document without a usable report_query yields an empty query instead of a KeyError / 500."""
    assert resolve_report_query(report, REPORT_ID) == {}


def test_resolve_report_query_unevaluable_query_maps_to_500_naming_the_report() -> None:
    """A stored query that cannot be evaluated is a corrupted document, reported with its id."""
    report: dict[str, Any] = {'report_query': {'data': "{'broken': "}}

    with pytest.raises(HTTPException) as exc_info:
        resolve_report_query(report, REPORT_ID)

    assert exc_info.value.code == HTTP_SERVER_ERROR
    assert str(REPORT_ID) in exc_info.value.description


# ------------------------------------------------- payload builders ------------------------------------------------- #

def _payload_manager() -> MagicMock:
    """Builds a ReportsManager stand-in whose foreign-key lookups both resolve."""
    reports_manager = MagicMock()
    reports_manager.get_one_from_other_collection.return_value = {'public_id': 1, 'fields': []}

    return reports_manager


def _patched_payload_chain(stack: ExitStack) -> None:
    """Patches the type hydration and the Mongo query builder, keeping the real collection names."""
    stack.enter_context(patch(f'{HELPER_PATH}.CmdbType.from_data', return_value=_report_type([])))
    stack.enter_context(patch(f'{HELPER_PATH}.build_report_query', return_value={'data': 'q'}))


def test_build_report_payload_normalises_and_adds_the_built_query() -> None:
    """The shared chain returns the normalised payload plus the server-built report_query."""
    with ExitStack() as stack:
        _patched_payload_chain(stack)
        payload = build_report_payload(_payload_manager(), _valid_params())

    assert payload['report_query'] == {'data': 'q'}
    assert payload['type_id'] == TYPE_ID
    assert 'predefined' not in payload


def test_build_report_payload_checks_both_foreign_keys() -> None:
    """The category and the type are both looked up before anything is written."""
    reports_manager = _payload_manager()

    with ExitStack() as stack:
        _patched_payload_chain(stack)
        build_report_payload(reports_manager, _valid_params())

    looked_up = [call.args[0] for call in reports_manager.get_one_from_other_collection.call_args_list]

    assert looked_up == [CmdbReportCategory.COLLECTION, CmdbType.COLLECTION]


def test_build_report_create_payload_forces_predefined_false() -> None:
    """A client can never create a predefined report, whatever the request says."""
    with ExitStack() as stack:
        _patched_payload_chain(stack)
        payload = build_report_create_payload(_payload_manager(), _valid_params(predefined='true'))

    assert payload['predefined'] is False
    assert 'public_id' not in payload


@pytest.mark.parametrize('stored,expected', [({'predefined': True}, True), ({'predefined': False}, False), ({}, False)])
def test_build_report_update_payload_pins_identity_and_predefined(
    stored: dict[str, Any], expected: bool,
) -> None:
    """The identity comes from the URL and predefined from the stored document, never from the payload."""
    with ExitStack() as stack:
        _patched_payload_chain(stack)
        payload = build_report_update_payload(
            _payload_manager(),
            _valid_params(predefined='true', public_id=str(BOGUS_PAYLOAD_ID)),
            REPORT_ID,
            stored,
        )

    assert payload['public_id'] == REPORT_ID
    assert payload['predefined'] is expected


# ------------------------------------------------- run_cmdb_report_query (preview) ---------------------------------- #

def _run_with_query(flask_app: Flask, url: str) -> MagicMock:
    """Drives the unwrapped run handler with a non-empty query and returns the patched BuilderParameters."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': "{'x': 1}"}}
    mgr.iterate_results.return_value = []

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.resolve_report_query', return_value={'x': 1}), \
         patch(f'{ROUTE_PATH}.BuilderParameters') as builder_params, \
         patch(f'{ROUTE_PATH}.DefaultResponse'), \
         flask_app.test_request_context(url):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    return builder_params


def test_run_report_reads_rows_without_the_count_aggregation(flask_app: Flask) -> None:
    """The run route uses iterate_results, so the total-count pipeline it would discard never runs."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': "{'x': 1}"}}
    mgr.iterate_results.return_value = []

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.resolve_report_query', return_value={'x': 1}), \
         patch(f'{ROUTE_PATH}.DefaultResponse'), \
         flask_app.test_request_context('/run/1'):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    mgr.iterate_results.assert_called_once()
    mgr.iterate.assert_not_called()


def test_run_report_serialises_each_row_via_to_json(flask_app: Flask) -> None:
    """Rows are serialised explicitly with CmdbObject.to_json, not left to the __dict__ fallback."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': "{'x': 1}"}}
    rows = [MagicMock(), MagicMock()]
    mgr.iterate_results.return_value = rows

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.resolve_report_query', return_value={'x': 1}), \
         patch(f'{ROUTE_PATH}.CmdbObject.to_json', side_effect=[{'public_id': 1}, {'public_id': 2}]) as to_json, \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response, \
         flask_app.test_request_context('/run/1'):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    assert to_json.call_count == len(rows)
    assert response.call_args.args[0] == [{'public_id': 1}, {'public_id': 2}]


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
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/run/1'):
        _unwrap(run_cmdb_report_query)(public_id=1, request_user=MagicMock())

    mgr.iterate_results.assert_not_called()
    response_ctor.assert_called_once_with({})


def test_run_report_without_a_stored_query_returns_empty_without_iterating(flask_app: Flask) -> None:
    """A document that carries no report_query at all answers empty instead of failing with a 500."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'public_id': REPORT_ID, 'name': 'legacy'}

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/run/1'):
        _unwrap(run_cmdb_report_query)(public_id=REPORT_ID, request_user=MagicMock())

    mgr.iterate_results.assert_not_called()
    response_ctor.assert_called_once_with({})


@pytest.mark.parametrize('preview_value', ['1', 'yes', 'maybe'])
def test_run_report_with_a_malformed_preview_flag_maps_to_400(flask_app: Flask, preview_value: str) -> None:
    """An unrecognised ?preview= value is a bad request, not an internal error - and nothing is read."""
    mgr = MagicMock()

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context(f'/run/1?preview={preview_value}'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(run_cmdb_report_query)(public_id=REPORT_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST
    mgr.get_item.assert_not_called()


def test_run_report_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception while running the report is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.get_item.return_value = {'report_query': {'data': "{'x': 1}"}}
    mgr.iterate_results.side_effect = RuntimeError('boom')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/run/1'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(run_cmdb_report_query)(public_id=REPORT_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  ROUTE HANDLERS                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def _patch_write_helpers(stack: ExitStack) -> None:
    """Patches the two payload builders (validation + foreign keys + query build) as no-ops."""
    stack.enter_context(patch(f'{ROUTE_PATH}.build_report_create_payload', return_value=dict(BUILT_PAYLOAD)))
    stack.enter_context(patch(f'{ROUTE_PATH}.build_report_update_payload', return_value=dict(BUILT_PAYLOAD)))


# ----------------------------------------------------- create ------------------------------------------------------- #

def test_create_inserts_and_returns_new_id(flask_app: Flask) -> None:
    """A valid create builds the payload, inserts exactly it and returns the new public_id."""
    mgr = MagicMock()
    mgr.insert_item.return_value = REPORT_ID

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.DefaultResponse'))
        stack.enter_context(flask_app.test_request_context('/', method='POST'))
        _unwrap(create_cmdb_report)(params=dict(WRITE_PARAMS), request_user=MagicMock())

    mgr.insert_item.assert_called_once_with(BUILT_PAYLOAD)
    response_ctor.assert_called_once_with(REPORT_ID)


def test_create_passes_a_helper_abort_through_unchanged(flask_app: Flask) -> None:
    """A 400 raised by the payload builder keeps its status instead of becoming a 500."""
    mgr = MagicMock()

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        stack.enter_context(patch(f'{ROUTE_PATH}.build_report_create_payload', side_effect=BadRequest('nope')))
        stack.enter_context(flask_app.test_request_context('/', method='POST'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(create_cmdb_report)(params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST
    mgr.insert_item.assert_not_called()


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


def test_get_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.get_item.side_effect = RuntimeError('boom')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_report)(public_id=REPORT_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


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


def test_list_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.iterate_items.side_effect = RuntimeError('boom')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_reports)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


def test_list_passes_an_http_exception_through_unchanged(flask_app: Flask) -> None:
    """An HTTPException raised inside the list route keeps its status instead of becoming a 500."""
    mgr = MagicMock()

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.BuilderParameters', side_effect=BadRequest('nope')), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(get_cmdb_reports)(params=MagicMock(), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


# ------------------------------------------------------- count ------------------------------------------------------ #

def test_count_returns_count_for_type(flask_app: Flask) -> None:
    """The route counts reports of the given type - the path id is a type_id, not a report id."""
    mgr = MagicMock()
    mgr.count_documents.return_value = 3

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         patch(f'{ROUTE_PATH}.DefaultResponse') as response_ctor, \
         flask_app.test_request_context('/5/count_reports_of_type'):
        _unwrap(count_cmdb_reports_of_type)(type_id=TYPE_ID, request_user=MagicMock())

    mgr.count_documents.assert_called_once_with({'type_id': TYPE_ID})
    response_ctor.assert_called_once_with(3)


def test_count_base_manager_get_error_maps_to_400(flask_app: Flask) -> None:
    """count_documents fails with BaseManagerGetError - the arm that actually catches it maps to 400."""
    mgr = MagicMock()
    mgr.count_documents.side_effect = BaseManagerGetError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/5/count_reports_of_type'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(count_cmdb_reports_of_type)(type_id=TYPE_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_count_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.count_documents.side_effect = RuntimeError('boom')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/5/count_reports_of_type'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(count_cmdb_reports_of_type)(type_id=TYPE_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


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

def test_update_writes_the_payload_and_echoes_the_merged_document(flask_app: Flask) -> None:
    """The update is a $set of the payload, so the echo is the stored doc with the payload merged over
    it - equal to what a re-read would return, without the second query."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        response_ctor = stack.enter_context(patch(f'{ROUTE_PATH}.UpdateSingleResponse'))
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        _unwrap(update_cmdb_report)(public_id=REPORT_ID, params=dict(WRITE_PARAMS), request_user=MagicMock())

    mgr.update_item.assert_called_once_with(REPORT_ID, BUILT_PAYLOAD)
    # One read only: the pre-update existence check
    mgr.get_item.assert_called_once_with(REPORT_ID, as_dict=True)
    response_ctor.assert_called_once_with({**SAMPLE_REPORT, **BUILT_PAYLOAD})


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


def test_update_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerGetError while loading the target maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.side_effect = ReportsManagerGetError('x')

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(update_cmdb_report)(public_id=REPORT_ID, params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST


def test_update_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT
    mgr.update_item.side_effect = RuntimeError('boom')

    with ExitStack() as stack:
        stack.enter_context(patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr))
        _patch_write_helpers(stack)
        stack.enter_context(flask_app.test_request_context('/7', method='PUT'))
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(update_cmdb_report)(public_id=REPORT_ID, params=dict(WRITE_PARAMS), request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR


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

    # The existence check fetches the lightweight raw dict, not a built model
    mgr.get_item.assert_called_once_with(7, as_dict=True)
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


def test_delete_get_error_maps_to_400(flask_app: Flask) -> None:
    """A ReportsManagerGetError while loading the target maps to HTTP 400."""
    mgr = MagicMock()
    mgr.get_item.side_effect = ReportsManagerGetError('x')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7/', method='DELETE'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(delete_cmdb_report)(public_id=REPORT_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_BAD_REQUEST
    mgr.delete_item.assert_not_called()


def test_delete_unexpected_error_maps_to_500(flask_app: Flask) -> None:
    """Any other exception is translated to HTTP 500."""
    mgr = MagicMock()
    mgr.get_item.return_value = SAMPLE_REPORT
    mgr.delete_item.side_effect = RuntimeError('boom')

    with patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=mgr), \
         flask_app.test_request_context('/7/', method='DELETE'):
        with pytest.raises(HTTPException) as exc_info:
            _unwrap(delete_cmdb_report)(public_id=REPORT_ID, request_user=MagicMock())

    assert exc_info.value.code == HTTP_SERVER_ERROR
