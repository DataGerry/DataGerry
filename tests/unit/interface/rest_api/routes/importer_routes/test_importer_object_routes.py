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
Unit tests for cmdb.interface.rest_api.routes.importer_routes.importer_object_routes

DB-free, and the tier this module was missing: the object-import routes already have 47 functional
tests, but the arms below cannot be reached over HTTP - a registry that raises while being iterated,
a parser class that fails to load, the unexpected-failure tails. Collaborators are patched at the
route module path and every route is unwrapped past its auth decorators.

The batched log helper gets its own section: it re-reads and renders the imported objects in ONE
query and ONE render pass, and it must stay best-effort - the objects are already committed when it
runs, so neither a failed batch nor a single failed insert may surface to the caller
(discussion-backlog #160).
"""
from io import BytesIO
from typing import Any, Callable
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException, NotFound

from cmdb.framework.rendering.render_constants import RenderObjectInfoKey
from cmdb.interface.rest_api.routes.importer_routes import importer_object_routes as routes
from cmdb.interface.rest_api.routes.importer_routes.importer_object_routes import (
    _build_importer_config,
    _log_imported_objects,
    _remove_temp_file,
    _render_imported_objects,
    _resolve_file_format,
    get_default_object_importer_config,
    get_default_object_parser_config,
    get_object_importer,
    import_objects,
    parse_objects,
)
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_PATH: str = 'cmdb.interface.rest_api.routes.importer_routes.importer_object_routes'


def _unwrap(func: Callable[..., Any]) -> Callable[..., Any]:
    """Strips the auth / api-level decorators off a route function."""
    inner = func

    while hasattr(inner, '__wrapped__'):
        inner = inner.__wrapped__

    return inner


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """Returns a minimal Flask app to host the test_request_context calls."""
    return Flask(__name__)


def _rendered(public_id: int, version: str = '1.0.0') -> MagicMock:
    """Builds a stand-in RenderResult carrying the object_information the log entry reads."""
    result = MagicMock()
    result.object_information = {
        RenderObjectInfoKey.OBJECT_ID.value: public_id,
        RenderObjectInfoKey.VERSION.value: version,
    }

    return result


# -------------------------------------------------------------------------------------------------------------------- #
#                                              _resolve_file_format                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_resolve_file_format_returns_a_supported_format(flask_app: Flask) -> None:
    """A registered format is handed back unchanged"""
    with flask_app.test_request_context('/', method='POST', data={'file_format': 'csv'}):
        assert _resolve_file_format() == 'csv'


def test_resolve_file_format_aborts_400_without_a_format(flask_app: Flask) -> None:
    """A missing format is the caller's mistake, not a server fault"""
    with flask_app.test_request_context('/', method='POST', data={}):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_file_format()

    assert exc_info.value.code == 400


def test_resolve_file_format_names_the_supported_formats(flask_app: Flask) -> None:
    """An unsupported format is refused with a message naming it AND what is supported"""
    with flask_app.test_request_context('/', method='POST', data={'file_format': 'xml'}):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_file_format()

    assert exc_info.value.code == 400
    assert 'xml' in exc_info.value.description
    assert 'csv' in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                             _build_importer_config                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_build_importer_config_instantiates_the_class() -> None:
    """The payload is handed to the config class as keyword arguments"""
    config_class = MagicMock()

    assert _build_importer_config(config_class, {'type_id': 1}) is config_class.return_value
    config_class.assert_called_once_with(type_id=1)


@pytest.mark.parametrize('bound', ['start_element', 'max_elements'])
def test_build_importer_config_rejects_a_negative_bound(bound: str) -> None:
    """A negative count silently means something else entirely, so it is refused up front"""
    with pytest.raises(HTTPException) as exc_info:
        _build_importer_config(MagicMock(), {bound: -5})

    assert exc_info.value.code == 400


@pytest.mark.parametrize('value', [0, 5, True, False, 'not-a-number', None])
def test_build_importer_config_accepts_everything_else(value: Any) -> None:
    """Only a genuinely negative int is refused - booleans are not counts and are left alone"""
    _build_importer_config(MagicMock(), {'start_element': value})


def test_build_importer_config_reports_an_unusable_payload_as_400() -> None:
    """A key the config class does not accept is a malformed request, not a server fault"""
    config_class = MagicMock(side_effect=TypeError("unexpected keyword argument 'nope'"))

    with pytest.raises(HTTPException) as exc_info:
        _build_importer_config(config_class, {'nope': 1})

    assert exc_info.value.code == 400


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  _remove_temp_file                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_remove_temp_file_ignores_a_missing_path() -> None:
    """Cleanup is best-effort: no file, or a path that is already gone, is a no-op"""
    with patch(f'{ROUTE_PATH}.os.remove') as remove:
        _remove_temp_file(None)
        _remove_temp_file('/tmp/definitely-not-there')

    remove.assert_not_called()


def test_remove_temp_file_removes_an_existing_path() -> None:
    """An existing working file is unlinked"""
    with patch(f'{ROUTE_PATH}.os.path.exists', return_value=True), \
         patch(f'{ROUTE_PATH}.os.remove') as remove:
        _remove_temp_file('/tmp/import-file')

    remove.assert_called_once_with('/tmp/import-file')


# -------------------------------------------------------------------------------------------------------------------- #
#                                     _render_imported_objects / _log_imported_objects                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_render_imported_objects_reads_and_renders_in_one_pass() -> None:
    """One $in query and one CmdbMultiRender instance, however many objects were imported"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [{'public_id': 1}, {'public_id': 2}]

    with patch(f'{ROUTE_PATH}.CmdbObject.from_data', side_effect=lambda doc: doc), \
         patch(f'{ROUTE_PATH}.CmdbMultiRender') as multi_render:
        multi_render.return_value.result.return_value = [_rendered(1), _rendered(2)]

        rendered = _render_imported_objects([1, 2], objects_manager, MagicMock())

    objects_manager.find_objects.assert_called_once_with({'public_id': {'$in': [1, 2]}})
    assert multi_render.call_count == 1
    assert sorted(rendered) == [1, 2]


def test_render_imported_objects_returns_empty_when_nothing_is_stored() -> None:
    """Objects deleted between the import and the logging simply have no render"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []

    with patch(f'{ROUTE_PATH}.CmdbMultiRender') as multi_render:
        assert not _render_imported_objects([1], objects_manager, MagicMock())

    multi_render.assert_not_called()


def test_log_imported_objects_writes_one_log_per_object() -> None:
    """Every rendered object gets its CREATE entry, carrying the version off the render"""
    logs_manager = MagicMock()
    messages = [MagicMock(public_id=1), MagicMock(public_id=2)]

    with patch(f'{ROUTE_PATH}._render_imported_objects', return_value={1: _rendered(1), 2: _rendered(2, '2.0.0')}), \
         patch(f'{ROUTE_PATH}.json.dumps', return_value='{}'):
        _log_imported_objects(messages, MagicMock(), logs_manager, MagicMock())

    assert logs_manager.insert_log.call_count == 2
    assert logs_manager.insert_log.call_args.kwargs['version'] == '2.0.0'


def test_log_imported_objects_does_nothing_without_imports() -> None:
    """An import in which every row failed has nothing to log and reads nothing back"""
    objects_manager = MagicMock()

    _log_imported_objects([], objects_manager, MagicMock(), MagicMock())

    objects_manager.find_objects.assert_not_called()


def test_log_imported_objects_skips_an_object_it_could_not_render() -> None:
    """A missing render costs that object its log entry, not the others"""
    logs_manager = MagicMock()
    messages = [MagicMock(public_id=1), MagicMock(public_id=2)]

    with patch(f'{ROUTE_PATH}._render_imported_objects', return_value={2: _rendered(2)}), \
         patch(f'{ROUTE_PATH}.json.dumps', return_value='{}'):
        _log_imported_objects(messages, MagicMock(), logs_manager, MagicMock())

    assert logs_manager.insert_log.call_count == 1


def test_log_imported_objects_survives_a_failing_render_batch() -> None:
    """#160: the objects are already committed, so a broken batch may not fail the import"""
    logs_manager = MagicMock()

    with patch(f'{ROUTE_PATH}._render_imported_objects', side_effect=RuntimeError('render blew up')):
        _log_imported_objects([MagicMock(public_id=1)], MagicMock(), logs_manager, MagicMock())

    logs_manager.insert_log.assert_not_called()


def test_log_imported_objects_survives_a_failing_insert() -> None:
    """A single failing log write must not cost the remaining objects theirs"""
    logs_manager = MagicMock()
    logs_manager.insert_log.side_effect = [RuntimeError('logs down'), None]
    messages = [MagicMock(public_id=1), MagicMock(public_id=2)]

    with patch(f'{ROUTE_PATH}._render_imported_objects', return_value={1: _rendered(1), 2: _rendered(2)}), \
         patch(f'{ROUTE_PATH}.json.dumps', return_value='{}'):
        _log_imported_objects(messages, MagicMock(), logs_manager, MagicMock())

    assert logs_manager.insert_log.call_count == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the unexpected-failure arms of the routes                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_importer_listing_failure_becomes_500(flask_app: Flask) -> None:
    """A registry that cannot be read is a server fault"""
    bare = _unwrap(get_object_importer)
    broken = MagicMock()
    broken.values.side_effect = RuntimeError('registry broken')

    with patch(f'{ROUTE_PATH}.OBJECT_IMPORTER_REGISTRY', broken), \
         flask_app.test_request_context('/importer/'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500


@pytest.mark.parametrize('route, registry_name, kwargs', [
    (get_default_object_importer_config, 'OBJECT_IMPORTER_CONFIG_REGISTRY', {'importer_type': 'csv'}),
    (get_default_object_parser_config, 'OBJECT_PARSER_REGISTRY', {'parser_type': 'csv'}),
])
def test_a_broken_config_registry_becomes_500(
    flask_app: Flask, route: Any, registry_name: str, kwargs: dict[str, Any],
) -> None:
    """Anything other than a missing key is a server fault, not a 404"""
    bare = _unwrap(route)
    broken = MagicMock()
    broken.__getitem__.side_effect = RuntimeError('registry broken')

    with patch(f'{ROUTE_PATH}.{registry_name}', broken), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock(), **kwargs)

    assert exc_info.value.code == 500


@pytest.mark.parametrize('route, registry_name, kwargs', [
    (get_default_object_importer_config, 'OBJECT_IMPORTER_CONFIG_REGISTRY', {'importer_type': 'nope'}),
    (get_default_object_parser_config, 'OBJECT_PARSER_REGISTRY', {'parser_type': 'nope'}),
])
def test_an_unknown_type_stays_a_404(
    flask_app: Flask, route: Any, registry_name: str, kwargs: dict[str, Any],
) -> None:
    """The 404 for an unknown type must not be swallowed into the 500 tail"""
    bare = _unwrap(route)

    with patch(f'{ROUTE_PATH}.{registry_name}', {}), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock(), **kwargs)

    assert exc_info.value.code == 404


def test_parse_objects_reports_an_unexpected_failure_as_500(flask_app: Flask) -> None:
    """A failure outside the parse attempt itself is a server fault"""
    bare = _unwrap(parse_objects)

    with patch(f'{ROUTE_PATH}.get_file_in_request', side_effect=RuntimeError('boom')), \
         flask_app.test_request_context('/parse/', method='POST', data={'file_format': 'csv'}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500


def test_parse_objects_does_not_swallow_an_http_error_from_the_parser(flask_app: Flask) -> None:
    """An HTTPException raised while parsing propagates instead of becoming a generic 400"""
    bare = _unwrap(parse_objects)

    with patch(f'{ROUTE_PATH}.get_file_in_request', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.get_element_from_data_request', return_value={}), \
         patch(f'{ROUTE_PATH}.generate_parsed_output', side_effect=NotFound('gone')), \
         flask_app.test_request_context('/parse/', method='POST', data={'file_format': 'csv'}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 404


def test_parse_objects_forwards_a_provided_parser_config(flask_app: Flask) -> None:
    """A supplied parser config reaches the parser instead of being replaced by the defaults"""
    bare = _unwrap(parse_objects)
    parser_config = {'delimiter': ';'}

    with patch(f'{ROUTE_PATH}.get_file_in_request', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.get_element_from_data_request', return_value=parser_config), \
         patch(f'{ROUTE_PATH}.generate_parsed_output') as generate, \
         flask_app.test_request_context('/parse/', method='POST', data={'file_format': 'csv'}):
        generate.return_value.output.return_value = [{'public_id': 1}]

        bare(request_user=MagicMock())

    assert generate.call_args.args[2] == parser_config


def test_import_objects_reports_an_unexpected_failure_as_500(flask_app: Flask) -> None:
    """A failure outside the mapped importer errors is a server fault"""
    bare = _unwrap(import_objects)

    with patch(f'{ROUTE_PATH}.get_file_in_request', side_effect=RuntimeError('boom')), \
         flask_app.test_request_context(
             '/', method='POST',
             data={'file': (BytesIO(b'a,b\n1,2\n'), 'import.csv'), 'file_format': 'csv'},
             content_type='multipart/form-data',
         ):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 500


def test_a_parser_class_that_fails_to_load_is_a_500(flask_app: Flask) -> None:
    """A registered format whose parser class cannot be loaded is a server fault, not a bad request"""
    with patch(f'{ROUTE_PATH}.load_parser_class', side_effect=routes.ParserLoadError('broken')), \
         flask_app.test_request_context('/'):
        with pytest.raises(HTTPException) as exc_info:
            routes._build_object_importer(  # pylint: disable=protected-access
                'csv', '/tmp/f', {}, {}, MagicMock(), MagicMock(),
            )

    assert exc_info.value.code == 500


def test_parse_objects_reports_an_unparsable_file_as_400(flask_app: Flask) -> None:
    """A file the parser cannot read with the given config is the caller's problem, not a 500"""
    bare = _unwrap(parse_objects)

    with patch(f'{ROUTE_PATH}.get_file_in_request', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}.get_element_from_data_request', return_value={}), \
         patch(f'{ROUTE_PATH}.generate_parsed_output', side_effect=RuntimeError('malformed csv')), \
         flask_app.test_request_context('/parse/', method='POST', data={'file_format': 'csv'}):
        with pytest.raises(HTTPException) as exc_info:
            bare(request_user=MagicMock())

    assert exc_info.value.code == 400
    assert 'configuration' in exc_info.value.description


def test_import_objects_accepts_a_provided_parser_config(flask_app: Flask) -> None:
    """A supplied parser config is used as-is instead of falling back to the parser defaults"""
    bare = _unwrap(import_objects)
    importer = MagicMock()

    with patch(f'{ROUTE_PATH}.get_file_in_request', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}._save_import_file_to_temp', return_value='/tmp/import-file'), \
         patch(f'{ROUTE_PATH}.get_element_from_data_request', return_value={'delimiter': ';'}), \
         patch(f'{ROUTE_PATH}.ManagerProvider.get_manager', return_value=MagicMock()), \
         patch(f'{ROUTE_PATH}._resolve_import_type', return_value=MagicMock(special_type='')), \
         patch(f'{ROUTE_PATH}.enforce_special_type_license'), \
         patch(f'{ROUTE_PATH}._build_object_importer', return_value=importer) as build, \
         patch(f'{ROUTE_PATH}._run_object_import') as run_import, \
         patch(f'{ROUTE_PATH}._log_imported_objects'), \
         patch(f'{ROUTE_PATH}._remove_temp_file'), \
         flask_app.test_request_context(
             '/', method='POST',
             data={'file': (BytesIO(b'a,b\n1,2\n'), 'import.csv'), 'file_format': 'csv'},
             content_type='multipart/form-data',
         ):
        run_import.return_value.as_report.return_value = {'success_imports': 1, 'failed_imports': []}

        bare(request_user=MagicMock())

    assert build.call_args.args[2] == {'delimiter': ';'}
