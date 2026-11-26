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
Census: every write that can change what an object's scope block is built from keeps the block current (phase 10, S1)

A block is built from an object's location field (or its node), its interface rows, the location chain above it, its
subnets' supernets and the object relations naming it (phase 11). The object writes through
``ObjectsManager.insert_object`` / ``update_object`` / the bulk location write / the reference scrub /
``apply_raw_updates`` keep it themselves; every other raw write of ``framework.objects`` (``insert``, ``update``,
``bulk_write``, ``replace``, ...) on an objects manager, every write of the location tree and every write of an object
relation is pinned here: either it computes the block (``stamp`` / ``refresh`` / ``refresh_naming`` /
``refresh_endpoints``) in the same function, or the reason it cannot change a block is written down. A new call site
fails until it is classified. The migrations are left out (``updater_20261128`` / ``updater_20261129`` compute every
block after them). Read with ``ast``
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
CMDB_ROOT: Path = REPO_ROOT / 'cmdb'
MIGRATIONS_DIR: Path = CMDB_ROOT / 'database' / 'updater' / 'versions'
OBJECTS_MANAGER_MODULE: str = 'cmdb/manager/objects_manager.py'
OBJECTS_MANAGER_SUFFIX: str = 'objects_manager'
RAW_OBJECT_WRITES: frozenset[str] = frozenset({'insert', 'insert_many', 'insert_many_reporting', 'update', 'update_many',
                                               'update_many_raw', 'update_many_pull', 'upsert', 'replace',
                                               'bulk_write'})
TREE_WRITES: frozenset[str] = frozenset({'insert_location', 'update_location', 'delete_location'})
OBJECT_RELATIONS_MANAGER_MODULE: str = 'cmdb/manager/object_relations_manager.py'
OBJECT_RELATIONS_MANAGER_SUFFIX: str = 'object_relations_manager'
RELATION_WRITES: frozenset[str] = frozenset({'insert_object_relation', 'update_object_relation',
                                             'delete_object_relation', 'delete_invalidated_object_relations',
                                             'find_one_and_delete', 'delete_many', 'delete', *RAW_OBJECT_WRITES})
BLOCK_CALLS: frozenset[str] = frozenset({'stamp', 'refresh', 'refresh_naming', 'refresh_endpoints',
                                         'try_refresh_endpoints'})

KEEPS: str = 'keeps the block'
SYNC_FIELDS: str = 'the sync writes a person\'s fixed values and a group\'s members - never a location or an interface row'
SYNC_FINGERPRINT: str = 'unsets the sync fingerprint only'
CASCADE_ROUNDS: str = ('the rounds of handle_delete_invalid_object_relations, which refreshes the ends of every relation '
                       'removed, also after a failure')
BULK_DELETE: str = 'its one caller, the bulk delete route, refreshes the ends of what it deleted, also after a failure'
TYPE_CASCADE: str = ('the cascade of a relation update; reconcile_object_relations refreshes the ends of what it '
                     'deleted, also after a failure')
FIELD_VALUES: str = 'rewrites the instances\' field values only - never an end'
LEDGERED_DELETE: str = ('the ledgered writes of its one caller, delete_location_with_reparenting, which refreshes the '
                        'blocks after them and after their undo')

# module::function::write -> KEEPS, or why the write cannot change a block
CLASSIFIED: dict[str, str] = {
    'cmdb/framework/importer/helper/object_import_writer.py::insert_new_objects::insert_many_reporting': KEEPS,
    'cmdb/framework/importer/helper/object_import_writer.py::replace_stored_object::replace': KEEPS,
    'cmdb/framework/ipam/supernet_membership.py::clear_supernet_ref::bulk_write': KEEPS,
    'cmdb/framework/person_sync/sync_relocation.py::_move::update': KEEPS,
    'cmdb/framework/person_sync/sync_engine.py::insert_linked_object::insert': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_engine.py::sync_user_group_deleted::update': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_engine.py::write_edit::update': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_group_mapping.py::map_user_group::update': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_pass.py::run_sync_pass::bulk_write': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_pass.py::switch_off_pass::bulk_write': SYNC_FIELDS,
    'cmdb/framework/person_sync/sync_pass.py::switch_off_pass::update_many_raw': SYNC_FINGERPRINT,
    'cmdb/interface/rest_api/routes/framework_routes/cmdb_locations/location_helper.py::'
    '_delete_and_reparent::delete_location': LEDGERED_DELETE,
    'cmdb/interface/rest_api/routes/framework_routes/cmdb_locations/location_helper.py::'
    'sync_object_location::insert_location': KEEPS,
    'cmdb/interface/rest_api/routes/framework_routes/cmdb_locations/location_helper.py::'
    'sync_object_location::update_location': KEEPS,
    'cmdb/interface/rest_api/routes/framework_routes/cmdb_objects/objects_side_effects_helper.py::'
    '_delete_relation_rounds::delete_many': CASCADE_ROUNDS,
    'cmdb/interface/rest_api/routes/relation_routes/object_relation_routes.py::'
    'insert_cmdb_object_relation::insert_object_relation': KEEPS,
    'cmdb/interface/rest_api/routes/relation_routes/object_relation_routes.py::'
    'update_cmdb_object_relation::update_object_relation': KEEPS,
    'cmdb/interface/rest_api/routes/relation_routes/object_relation_routes.py::'
    'delete_cmdb_object_relation::find_one_and_delete': KEEPS,
    'cmdb/interface/rest_api/routes/relation_routes/relations_helper.py::delete_object_relations::find_one_and_delete':
        BULK_DELETE,
    'cmdb/interface/rest_api/routes/relation_routes/relations_helper.py::'
    'handle_deleted_type_ids::delete_invalidated_object_relations': TYPE_CASCADE,
    'cmdb/manager/object_relations_manager.py::delete_invalidated_object_relations::find_one_and_delete': TYPE_CASCADE,
    'cmdb/manager/object_relations_manager.py::update_changed_fields::update_many_raw': FIELD_VALUES,
    'cmdb/manager/objects_manager.py::apply_raw_updates::update_many_raw': KEEPS,
    'cmdb/manager/objects_manager.py::delete_all_object_references::update_many_raw': KEEPS,
    'cmdb/manager/objects_manager.py::insert_object::insert': KEEPS,
    'cmdb/manager/objects_manager.py::set_location_field_for_objects::update_many_raw': KEEPS,
    'cmdb/manager/objects_manager.py::update_object::update': KEEPS,
}


def _functions(tree: ast.Module) -> list[ast.FunctionDef]:
    """Top-level functions and the methods of top-level classes - a nested function counts as its enclosing one's"""
    found: list[ast.FunctionDef] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            found.append(node)
        elif isinstance(node, ast.ClassDef):
            found.extend(item for item in node.body if isinstance(item, ast.FunctionDef))

    return found


def _is_object_write(module: str, call: ast.Call) -> bool:
    """A raw write on an objects manager (``self`` inside it), a write of the location tree or of an object relation"""
    if not isinstance(call.func, ast.Attribute):
        return False

    if call.func.attr in TREE_WRITES:
        return True

    receiver: str = ast.unparse(call.func.value)

    if receiver.endswith(OBJECT_RELATIONS_MANAGER_SUFFIX) or (module == OBJECT_RELATIONS_MANAGER_MODULE
                                                               and receiver == 'self'):
        return call.func.attr in RELATION_WRITES

    return call.func.attr in RAW_OBJECT_WRITES and (
        receiver.endswith(OBJECTS_MANAGER_SUFFIX) or (module == OBJECTS_MANAGER_MODULE and receiver == 'self'))


def _census() -> dict[str, set[str]]:
    """Per write found (``module::function::write``), every name its function calls"""
    found: dict[str, set[str]] = {}

    for path in sorted(CMDB_ROOT.rglob('*.py')):
        if MIGRATIONS_DIR in path.parents:
            continue

        module: str = path.relative_to(REPO_ROOT).as_posix()

        for function in _functions(ast.parse(path.read_text(encoding='utf-8'))):
            calls: list[ast.Call] = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
            called: set[str] = {call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, 'id', '')
                                for call in calls}

            for call in calls:
                if _is_object_write(module, call):
                    found[f'{module}::{function.name}::{call.func.attr}'] = called

    return found


def test_every_write_is_classified() -> None:
    """A new write is classified before it ships; a gone one leaves the list"""
    assert sorted(_census()) == sorted(CLASSIFIED)


@pytest.mark.parametrize('write', [write for write, reason in CLASSIFIED.items() if reason == KEEPS])
def test_a_keeping_write_computes_the_block_in_its_function(write: str) -> None:
    """stamp, refresh or refresh_naming beside the write"""
    assert _census()[write] & BLOCK_CALLS, write


def test_the_scan_sees_the_writes() -> None:
    """So a moved package cannot make it pass vacuously"""
    assert len(_census()) >= len(CLASSIFIED)
