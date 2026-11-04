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
Tripwire: a catch-all arm in the route layer lets a database outage through

A database outage (``APP_HANDLED_DATABASE_ERRORS``: a lost connection, a lock timeout, the connector's own error) is
answered by the app's handlers with 503 / 423, so a client knows to retry. A route or route helper that catches
``Exception`` first answers it with its own status instead - a 500 the frontend ignores, or worse a 400 that tells an
automation not to retry. Routes end in ``@handle_route_errors(...)``, which lets the outage through; an inline
catch-all arm is legal only when

- an earlier arm of the same ``try`` catches ``APP_HANDLED_DATABASE_ERRORS`` (and so re-raises the outage), or
- the arm ends in a bare ``raise`` - it only adds something before passing the error on.

Every other arm is listed in ``KNOWN_CATCH_ALLS`` with why it may swallow an outage (best-effort work after the
main write, no database call at all, a ruled answer). The list may shrink but not grow, and a stale entry fails too.

Read with ``ast``, so every module is covered whether or not a test imports it.
"""
import ast
from pathlib import Path

from tests.utils.catch_all_scan import is_catch_all, owner_of, parent_map
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_ROOT: Path = Path(__file__).resolve().parents[5] / 'cmdb' / 'interface' / 'rest_api' / 'routes'

# The name of the tuple an arm ahead of the catch-all must catch
OUTAGE_ERRORS_NAME: str = 'APP_HANDLED_DATABASE_ERRORS'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 150

# The arms allowed to catch an outage, by ``<file>::<owner>``, with how many each owner holds and why
KNOWN_CATCH_ALLS: dict[str, tuple[int, str]] = {
    'connection.py::connection_test_frontend': (1, 'an outage is `connected: false`; the arm is the route failing'),
    'connection.py::frontend_init': (1, 'no database call; an empty config is the fallback'),
    'framework_routes/cmdb_locations/location_helper.py::sync_object_location': (1, 'best-effort after the write'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::write_object_log': (1, 'best-effort log'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::write_object_logs': (1, 'best-effort log'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::log_object_change': (1, 'best-effort log'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::handle_create_object_log': (1, 'best-effort log'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::emit_object_state_change_events': (
        1, 'best-effort log'),
    'framework_routes/cmdb_objects/objects_side_effects_helper.py::prepare_relation_delete_logs': (
        1, 'best-effort log'),
    'framework_routes/cmdb_section_templates/section_template_routes.py::update_section_template': (
        1, 'the template is written; a retry would propagate nothing, so the half-done state is named (ruled)'),
    'importer_routes/importer_object_routes.py::_log_imported_objects': (1, 'best-effort log after the import'),
    'rack_routes/rack_location_helper.py::attach_member_location': (1, 'best-effort after the rack write'),
    'rack_routes/rack_location_helper.py::detach_member_location': (1, 'best-effort after the rack write'),
    'relation_routes/relations_helper.py::log_object_relation_deletions': (1, 'best-effort log'),
    'report_routes/report_helper.py::resolve_report_query': (1, 'no database call; parses a stored query'),
    'webhook_routes/webhook_helper.py::deliver_webhook_event': (2, 'delivery + its record, best-effort'),
    'webhook_routes/webhook_helper.py::send_webhook_event': (1, 'best-effort event fan-out'),
}


def _catches_outage(handler: ast.ExceptHandler) -> bool:
    """
    Whether an except arm catches ``APP_HANDLED_DATABASE_ERRORS``

    Args:
        handler (ast.ExceptHandler): The except arm

    Returns:
        bool: True when the arm names the tuple
    """
    if handler.type is None:
        return False

    names: list[ast.expr] = list(handler.type.elts) if isinstance(handler.type, ast.Tuple) else [handler.type]

    return any(isinstance(name, ast.Name) and name.id == OUTAGE_ERRORS_NAME for name in names)


def _ends_in_bare_raise(handler: ast.ExceptHandler) -> bool:
    """
    Whether an except arm's last statement is a bare ``raise``

    Args:
        handler (ast.ExceptHandler): The except arm

    Returns:
        bool: True when the arm passes what it caught on
    """
    last: ast.stmt = handler.body[-1]

    return isinstance(last, ast.Raise) and last.exc is None


def swallowing_census(source: str) -> dict[str, int]:
    """
    The module's catch-all arms that may swallow an outage, counted per owner

    Args:
        source (str): A module's source

    Returns:
        dict[str, int]: owner -> how many such arms it has
    """
    tree: ast.Module = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = parent_map(tree)
    census: dict[str, int] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue

        for position, handler in enumerate(node.handlers):
            if not is_catch_all(handler) or _ends_in_bare_raise(handler):
                continue

            if any(_catches_outage(earlier) for earlier in node.handlers[:position]):
                continue

            owner: str = owner_of(handler, parents)
            census[owner] = census.get(owner, 0) + 1

    return census


def _tree_census() -> tuple[dict[str, int], int]:
    """Every swallowing arm of the route layer, keyed ``<file>::<owner>``, and how many modules were scanned"""
    census: dict[str, int] = {}
    modules: list[Path] = sorted(ROUTES_ROOT.rglob('*.py'))

    for path in modules:
        for owner, count in swallowing_census(path.read_text(encoding='utf-8')).items():
            census[f'{path.relative_to(ROUTES_ROOT).as_posix()}::{owner}'] = count

    return census, len(modules)


def test_the_census_tells_the_three_shapes_apart() -> None:
    """Swallowing, re-raised by an earlier arm, passed on by a bare raise; typed arms ignored"""
    source = '''
def swallows():
    try:
        pass
    except Exception:
        pass

def guarded():
    try:
        pass
    except APP_HANDLED_DATABASE_ERRORS:
        raise
    except Exception:
        pass

def guarded_in_a_tuple():
    try:
        pass
    except (KeyError, APP_HANDLED_DATABASE_ERRORS):
        raise
    except BaseException:
        pass

def guarded_too_late():
    try:
        pass
    except Exception:
        pass
    except APP_HANDLED_DATABASE_ERRORS:
        raise

def passes_on():
    try:
        pass
    except Exception as err:
        log(err)
        raise

def raises_another():
    try:
        pass
    except Exception as err:
        raise OtherError(err) from err

def typed():
    try:
        pass
    except ValueError:
        pass
'''
    assert swallowing_census(source) == {'swallows': 1, 'guarded_too_late': 1, 'raises_another': 1}


def test_no_route_swallows_an_outage_beyond_the_known_arms() -> None:
    """New arms fail; the known ones may only shrink, and a fixed one leaves the list"""
    census, scanned = _tree_census()
    known: dict[str, int] = {owner: count for owner, (count, _why) in KNOWN_CATCH_ALLS.items()}

    assert scanned >= MIN_SCANNED_MODULES
    new = {owner: count for owner, count in census.items() if count > known.get(owner, 0)}
    assert not new, (f'catch-all arm(s) that turn a database outage into their own answer - end the route in '
                     f'@handle_route_errors, or re-raise APP_HANDLED_DATABASE_ERRORS first: {new}')
    stale = {owner: count for owner, count in known.items() if census.get(owner, 0) < count}
    assert not stale, f'KNOWN_CATCH_ALLS lists arms that are gone - lower or remove the entry: {stale}'
