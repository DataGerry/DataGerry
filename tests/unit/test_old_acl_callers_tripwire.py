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
Tripwire: no new caller of the old type ACL decision functions

Every access decision is taken by the access engine (``cmdb/framework/access_engine``). The old functions in
``cmdb/security/acl/`` (``builder``, ``helpers``, the ``AccessControlList`` model) only delegate to it, kept under
their names so the callers did not all change at once; those callers are renamed to the engine API when the old ACL
is removed. Until then the list of callers may only shrink: a module that is not listed below may not import or
reach any of the old names, and a listed module may not take a further one. A new caller uses the engine function
the failure names. The frozen pure reader of a stored ``acl`` block serves the equivalence tests and, in ``cmdb/``,
only the type ACL migration's self-check - it compares the translation against exactly that reading.

Read with ``ast``, so every module is covered whether or not a test imports it. ``cmdb/security/acl/`` itself is left
out: it defines the names and delegates between them.
"""
import ast
from functools import cache
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'
ACL_PACKAGE: str = 'security/acl/'

ENGINE_DENIED_TYPE_IDS: str = 'access_engine.denied_type_ids'
ENGINE_SCOPE_FILTER: str = 'access_engine.scope_filter'
ENGINE_PERMITTED_TYPES: str = 'access_engine.permitted_types_criteria'
ENGINE_TYPE_ALLOWS: str = 'access_engine.type_allows'
FROZEN: str = "nothing - frozen for the migration's self-check and the equivalence tests; decide through the engine"

# Each old name -> what a new caller uses instead
OLD_NAMES: dict[str, str] = {
    'resolve_denied_type_ids': ENGINE_DENIED_TYPE_IDS,
    'build_acl_pipeline': f'{ENGINE_SCOPE_FILTER} as a $match',
    'build_scope_criteria': ENGINE_SCOPE_FILTER,
    'build_denied_types_condition': f'{ENGINE_SCOPE_FILTER} (or access_engine.object_criteria)',
    'build_permitted_types_criteria': ENGINE_PERMITTED_TYPES,
    'type_allowed': ENGINE_TYPE_ALLOWS,
    'has_access_control': ENGINE_TYPE_ALLOWS,
    'has_type_document_access': ENGINE_TYPE_ALLOWS,
    'verify_access': ENGINE_TYPE_ALLOWS,
    'build_denied_types_criteria': FROZEN,
    'normalize_permissions': FROZEN,
    'acl_grants_access': FROZEN,
}

# The callers when the engine took over (module relative to cmdb/, old name) - renamed with the old ACL's removal; the
# migration's self-check reads the stored ACLs by their frozen rule on purpose
ALLOWED_CALLERS: frozenset[tuple[str, str]] = frozenset({
    ('framework/access_engine/type_acl_migration.py', 'acl_grants_access'),
    ('framework/ci_explorer/access.py', 'has_type_document_access'),
    ('framework/ipam/read_scope.py', 'resolve_denied_type_ids'),
    ('framework/ipam/reference_disclosure.py', 'resolve_denied_type_ids'),
    ('framework/ipam/supernet_membership.py', 'has_type_document_access'),
    ('framework/port/connection_cable_view.py', 'resolve_denied_type_ids'),
    ('framework/rendering/reference_read_scope.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/responses/response_parameters/lookup_scope.py', 'build_scope_criteria'),
    ('interface/rest_api/routes/exporter_routes/exporter_type_routes.py', 'build_permitted_types_criteria'),
    ('interface/rest_api/routes/framework_routes/cmdb_locations/location_helper.py', 'verify_access'),
    ('interface/rest_api/routes/framework_routes/cmdb_locations/location_read_scope.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/framework_routes/cmdb_objects/objects_helper.py', 'build_acl_pipeline'),
    ('interface/rest_api/routes/framework_routes/cmdb_objects/objects_person_groups_helper.py',
     'resolve_denied_type_ids'),
    ('interface/rest_api/routes/framework_routes/cmdb_objects/objects_update_read.py', 'verify_access'),
    ('interface/rest_api/routes/framework_routes/cmdb_types/types_helper.py', 'has_access_control'),
    ('interface/rest_api/routes/framework_routes/cmdb_types/types_helper.py', 'has_type_document_access'),
    ('interface/rest_api/routes/framework_routes/cmdb_types/types_reference_section_helper.py',
     'has_type_document_access'),
    ('interface/rest_api/routes/importer_routes/importer_route_utils.py', 'build_permitted_types_criteria'),
    ('interface/rest_api/routes/isms_routes/isms_report_routes.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/isms_routes/isms_routes_helper.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/isms_routes/risk_assessment_naming_helper.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/rack_routes/rack_access_helper.py', 'verify_access'),
    ('interface/rest_api/routes/rack_routes/rack_mount_routes.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/relation_routes/relations_helper.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/report_routes/report_helper.py', 'has_type_document_access'),
    ('interface/rest_api/routes/user_management_routes/person_records_helper.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/user_management_routes/person_sync_routes_helper.py', 'resolve_denied_type_ids'),
    ('interface/rest_api/routes/webhook_routes/webhook_delivery_scope.py', 'has_type_document_access'),
    ('manager/base_manager.py', 'build_scope_criteria'),
    ('manager/categories_manager.py', 'build_permitted_types_criteria'),
    ('manager/locations_manager.py', 'build_denied_types_condition'),
    ('manager/objects_manager.py', 'build_denied_types_condition'),
    ('manager/objects_manager.py', 'build_scope_criteria'),
    ('manager/objects_manager.py', 'resolve_denied_type_ids'),
    ('manager/objects_manager.py', 'verify_access'),
    ('manager/objects_reference_helper.py', 'build_denied_types_condition'),
    ('manager/query_builder/base_query_builder.py', 'build_acl_pipeline'),
    ('manager/query_builder/quick_search_pipeline_builder.py', 'build_acl_pipeline'),
    ('manager/query_builder/search_pipeline_builder.py', 'build_acl_pipeline'),
    ('manager/types_manager.py', 'build_permitted_types_criteria'),
    ('manager/types_manager.py', 'resolve_denied_type_ids'),
    ('models/docapi_model/docapi_cache_helper.py', 'build_scope_criteria'),
})


def _referenced_names(source: str) -> set[str]:
    """
    The old names one module's source imports or reaches as an attribute

    Args:
        source (str): The module's source

    Returns:
        set[str]: The old names it references - an import (aliased or not) or ``<anything>.<name>``
    """
    found: set[str] = set()

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            found.update(alias.name for alias in node.names if alias.name in OLD_NAMES)
        elif isinstance(node, ast.Attribute) and node.attr in OLD_NAMES:
            found.add(node.attr)

    return found


@cache
def _callers() -> frozenset[tuple[str, str]]:
    """
    Every (module relative to cmdb/, old name) referenced outside the old ACL package - scanned once per session

    Returns:
        frozenset[tuple[str, str]]: The references found
    """
    callers: set[tuple[str, str]] = set()

    for module in sorted(CMDB_ROOT.rglob('*.py')):
        relative: str = module.relative_to(CMDB_ROOT).as_posix()

        if relative.startswith(ACL_PACKAGE):
            continue

        callers.update((relative, name) for name in _referenced_names(module.read_text(encoding='utf-8')))

    return frozenset(callers)


@cache
def _defined_names() -> frozenset[str]:
    """
    Every function and method name the old ACL package defines - scanned once per session

    Returns:
        frozenset[str]: The names
    """
    return frozenset(node.name
                     for module in (CMDB_ROOT / ACL_PACKAGE).rglob('*.py')
                     for node in ast.walk(ast.parse(module.read_text(encoding='utf-8')))
                     if isinstance(node, ast.FunctionDef))


def test_no_new_caller_of_an_old_acl_function() -> None:
    """A new caller decides through the engine - the message names which function"""
    new: list[str] = [f'{module}: {name} -> use {OLD_NAMES[name]}'
                      for module, name in sorted(_callers() - ALLOWED_CALLERS)]

    assert new == []


@pytest.mark.parametrize('allowed', sorted(ALLOWED_CALLERS))
def test_every_allowed_caller_still_calls(allowed: tuple[str, str]) -> None:
    """A stale entry fails, so the list shrinks with the code"""
    assert allowed in _callers()


def test_every_allowed_name_is_an_old_name() -> None:
    """A typo in the list allows nothing"""
    assert {name for _module, name in ALLOWED_CALLERS} <= set(OLD_NAMES)


@pytest.mark.parametrize('name', sorted(OLD_NAMES))
def test_every_old_name_is_still_defined(name: str) -> None:
    """A renamed old function would leave the tripwire blind - the list follows the rename"""
    assert name in _defined_names()


class TestReferencedNames:
    """_referenced_names - the detector itself"""

    @pytest.mark.parametrize('source', [
        'from cmdb.security.acl.builder import resolve_denied_type_ids',
        'from cmdb.security.acl.builder import resolve_denied_type_ids as denied',
        'from cmdb.security.acl import builder\nbuilder.resolve_denied_type_ids(user, permission)',
        'import cmdb.security.acl.builder\ncmdb.security.acl.builder.resolve_denied_type_ids(user, permission)',
    ], ids=['import', 'aliased-import', 'module-attribute', 'dotted-attribute'])
    def test_every_way_of_reaching_a_name(self, source: str) -> None:
        """Import, alias, module attribute, full path"""
        assert _referenced_names(source) == {'resolve_denied_type_ids'}

    def test_a_model_method_counts(self) -> None:
        """``AccessControlList.verify_access`` is an old decision too"""
        assert _referenced_names('acl.verify_access(group_id, permission)') == {'verify_access'}

    def test_an_engine_call_does_not(self) -> None:
        """The engine names are free"""
        source: str = ('from cmdb.framework.access_engine import denied_type_ids, scope_filter\n'
                       'denied_type_ids(user, operations)')

        assert not _referenced_names(source)
