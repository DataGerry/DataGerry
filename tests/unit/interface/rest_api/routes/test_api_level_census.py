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
A census of every REST route's `ApiLevel`, read with `ast` from the route files

The level decides one thing: what the hosted cloud's API key (HTTP Basic + `x-api-key`) may reach. The split:
the core CMDB entities and the schema are `ADMIN`, the feature and presentation surfaces - the logs included -
are `LOCKED` (never the cloud API key), and `SUPER_ADMIN` guards the tenant setup and the user writes. Inside an
`ADMIN` file a route that serves a feature follows the feature, so a few routes are listed one by one. Nothing
else fails when a decorator is flipped, so this does - and a new route file fails until it is placed here

The webhook delivery log is `LOCKED` like every other log, and also because each event records the receiver's
response code, which would let an API client probe which hosts a webhook can reach
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

ROUTES_ROOT: Path = Path(__file__).resolve().parents[5] / 'cmdb' / 'interface' / 'rest_api' / 'routes'
LEVEL_KEYWORD: str = 'required_api_level'
LEVEL_DECORATOR: str = 'verify_api_access'
ROUTE_DECORATOR: str = 'route'

ADMIN: str = 'ADMIN'
SUPER_ADMIN: str = 'SUPER_ADMIN'
LOCKED: str = 'LOCKED'

# The routes there are - the count must not silently shrink; a route removed on purpose lowers it here
MIN_ROUTES: int = 360

# route file -> the level its routes require
FILE_LEVELS: dict[str, str] = {
    # The core CMDB entities and the schema: an ADMIN-level API key manages them
    'framework_routes/cmdb_categories/categories_routes.py': ADMIN,
    'framework_routes/cmdb_extendable_options/extendable_option_routes.py': ADMIN,
    'framework_routes/cmdb_locations/location_routes.py': ADMIN,
    'framework_routes/cmdb_objects/objects_routes.py': ADMIN,
    'framework_routes/cmdb_section_templates/section_template_routes.py': ADMIN,
    'framework_routes/cmdb_types/types_routes.py': ADMIN,
    'framework_routes/object_groups_routes.py': ADMIN,
    'relation_routes/object_relation_routes.py': ADMIN,
    'relation_routes/relations_routes.py': ADMIN,
    'report_routes/report_category_routes.py': ADMIN,
    'report_routes/report_routes.py': ADMIN,
    'user_management_routes/cmdb_groups/groups_routes.py': ADMIN,
    'user_management_routes/person_groups_routes.py': ADMIN,
    'user_management_routes/persons_routes.py': ADMIN,
    'isms_routes/control_measure_routes.py': ADMIN,
    'isms_routes/impact_category_routes.py': ADMIN,
    'isms_routes/impact_routes.py': ADMIN,
    'isms_routes/likelihood_routes.py': ADMIN,
    'isms_routes/measure_control_assignment_routes.py': ADMIN,
    'isms_routes/protection_goal_routes.py': ADMIN,
    'isms_routes/risk_assessment_routes.py': ADMIN,
    'isms_routes/risk_class_routes.py': ADMIN,
    'isms_routes/risk_matrix_routes.py': ADMIN,
    'isms_routes/risk_routes.py': ADMIN,
    'isms_routes/threat_routes.py': ADMIN,
    'isms_routes/vulnerability_routes.py': ADMIN,
    'webhook_routes/webhook_routes.py': ADMIN,
    'cmdb_license/license_activation_routes.py': ADMIN,
    'cmdb_license/license_routes.py': ADMIN,
    # The tenant setup and the user writes: the account's own level
    'setup_routes/setup_routes.py': SUPER_ADMIN,
    'user_management_routes/users_routes.py': SUPER_ADMIN,
    # The feature and presentation surfaces: never the cloud API key
    'ai_routes/chatgpt_routes.py': LOCKED,
    'auth_routes.py': LOCKED,
    'ci_explorer_routes/ci_explorer_routes.py': LOCKED,
    'config_routes/config_file_routes.py': LOCKED,
    'exporter_routes/exporter_object_routes.py': LOCKED,
    'exporter_routes/exporter_type_routes.py': LOCKED,
    'framework_routes/cmdb_docapi_templates/docapi_template_routes.py': LOCKED,
    'framework_routes/cmdb_logs/logs_routes.py': LOCKED,
    'framework_routes/cmdb_types/special_type_routes.py': LOCKED,
    'framework_routes/search_routes.py': LOCKED,
    'framework_routes/special_routes.py': LOCKED,
    'importer_routes/importer_isms_routes.py': LOCKED,
    'importer_routes/importer_object_routes.py': LOCKED,
    'importer_routes/importer_type_routes.py': LOCKED,
    'ipam_routes/ipam_assignable_routes.py': LOCKED,
    'ipam_routes/ipam_subnet_routes.py': LOCKED,
    'ipam_routes/ipam_supernet_routes.py': LOCKED,
    'ipam_routes/ipam_tree_routes.py': LOCKED,
    'ipam_routes/ipam_validation_routes.py': LOCKED,
    'isms_routes/isms_config_routes.py': LOCKED,
    'isms_routes/isms_report_routes.py': LOCKED,
    'media_library_routes/media_file_routes.py': LOCKED,
    'open_celium_routes/oc_connection_log_routes.py': LOCKED,
    'open_celium_routes/oc_connection_routes.py': LOCKED,
    'open_celium_routes/oc_connector_routes.py': LOCKED,
    'open_celium_routes/oc_invoker_routes.py': LOCKED,
    'open_celium_routes/oc_license_routes.py': LOCKED,
    'open_celium_routes/oc_scheduler_routes.py': LOCKED,
    'open_celium_routes/oc_template_routes.py': LOCKED,
    'port_connection_routes/port_connection_routes.py': LOCKED,
    'port_routes/port_bulk_routes.py': LOCKED,
    'port_routes/port_interface_link_routes.py': LOCKED,
    'port_routes/port_preview_routes.py': LOCKED,
    'port_routes/port_routes.py': LOCKED,
    'rack_routes/rack_assignable_routes.py': LOCKED,
    'rack_routes/rack_mount_routes.py': LOCKED,
    'relation_routes/object_relation_logs_routes.py': LOCKED,
    'settings_routes/date_routes.py': LOCKED,
    'settings_routes/system_routes.py': LOCKED,
    'user_management_routes/rights_routes.py': LOCKED,
    'user_management_routes/user_settings_routes.py': LOCKED,
    'webhook_routes/webhook_event_routes.py': LOCKED,
    # No route here declares a level - see UNLEVELLED_ROUTES
    'connection.py': None,
}

# route file -> {route function: its level, where it differs from the file's}
ROUTE_EXCEPTIONS: dict[str, dict[str, str]] = {
    # The frontend's helper reads on objects follow the features they serve
    'framework_routes/cmdb_objects/objects_routes.py': {
        'group_cmdb_objects_by_type_id': LOCKED,
        'get_cmdb_object_mds_reference': LOCKED,
        'get_cmdb_object_mds_references': LOCKED,
        'get_cmdb_object_references': LOCKED,
    },
    # Port Connectivity's virtual templates
    'framework_routes/cmdb_section_templates/section_template_routes.py': {
        'get_virtual_cmdb_section_templates': LOCKED,
    },
    # Reading the users is an ADMIN read; only the writes need the account's own level
    'user_management_routes/users_routes.py': {
        'get_cmdb_users': ADMIN,
        'get_cmdb_user': ADMIN,
    },
}

# Routes that declare no level at all: (file, function) -> why
UNLEVELLED_ROUTES: dict[tuple[str, str], str] = {
    ('auth_routes.py', 'post_login'): 'the login is how a caller gets credentials',
    ('connection.py', 'connection_test_frontend'): 'the connection probe answers before anyone has logged in',
    ('connection.py', 'frontend_init'): "the frontend's bootstrap answers before anyone has logged in",
}


def _decorator_name(decorator: ast.expr) -> str:
    """The name a decorator (called or bare) ends in"""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator

    if isinstance(target, ast.Attribute):
        return target.attr

    return target.id if isinstance(target, ast.Name) else ''


def _required_level(function: ast.FunctionDef) -> str | None:
    """The ApiLevel member a route's verify_api_access names, None without one"""
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call) and _decorator_name(decorator) == LEVEL_DECORATOR:
            for keyword in decorator.keywords:
                if keyword.arg == LEVEL_KEYWORD and isinstance(keyword.value, ast.Attribute):
                    return keyword.value.attr

    return None


def _census() -> dict[str, dict[str, str | None]]:
    """Every route file -> {route function: the level it requires}"""
    census: dict[str, dict[str, str | None]] = {}

    for path in sorted(ROUTES_ROOT.rglob('*.py')):
        routes = {
            node.name: _required_level(node)
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8')))
            if isinstance(node, ast.FunctionDef)
            and any(_decorator_name(decorator) == ROUTE_DECORATOR for decorator in node.decorator_list)
        }

        if routes:
            census[path.relative_to(ROUTES_ROOT).as_posix()] = routes

    return census


CENSUS: dict[str, dict[str, str | None]] = _census()
ROUTES: list[tuple[str, str, str | None]] = [
    (file_name, function, level) for file_name, routes in CENSUS.items() for function, level in routes.items()
]


def _expected(file_name: str, function: str) -> str | None:
    """The level the split asks of one route"""
    if (file_name, function) in UNLEVELLED_ROUTES:
        return None

    return ROUTE_EXCEPTIONS.get(file_name, {}).get(function, FILE_LEVELS[file_name])


class TestTheCensus:
    """The census itself is complete and current"""

    def test_it_finds_the_routes(self) -> None:
        """A moved folder must not make every check vacuous"""
        assert len(ROUTES) >= MIN_ROUTES

    def test_every_route_file_is_placed(self) -> None:
        """A new route file picks its side here, by what it serves"""
        assert set(CENSUS) == set(FILE_LEVELS)

    def test_every_listed_route_exists(self) -> None:
        """An exception or an unlevelled route naming a route that is gone is stale"""
        listed = {(file_name, function) for file_name, routes in ROUTE_EXCEPTIONS.items() for function in routes}

        for file_name, function in listed | set(UNLEVELLED_ROUTES):
            assert function in CENSUS.get(file_name, {}), f'{file_name}:{function} is no route'

    def test_every_exception_differs_from_its_file(self) -> None:
        """An exception stating the file's own level is noise"""
        for file_name, routes in ROUTE_EXCEPTIONS.items():
            for function, level in routes.items():
                assert level != FILE_LEVELS[file_name], f'{file_name}:{function} repeats the file level'


@pytest.mark.parametrize(('file_name', 'function', 'level'), ROUTES, ids=[f'{f}:{n}' for f, n, _ in ROUTES])
def test_every_route_requires_its_level(file_name: str, function: str, level: str | None) -> None:
    """The route's verify_api_access names the level the split gives it"""
    assert level == _expected(file_name, function)
