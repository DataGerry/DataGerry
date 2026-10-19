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
Unit tests for how the MongoDatabaseManager is put together

The manager is one object built from three parts - the document operations, MongoDatabaseAdminMixin and
MongoPublicIdCounterMixin - with the write-error reading in mongo_error_helper. What is pinned: the public API every
caller relies on is exactly the one listed, each method lives in the part it belongs to and the manager overrides
none of them, the mixins resolve in a fixed order, and none of the four modules is back over pylint's module-length or
public-method limit (read from .pylintrc, so a raised limit shows up here)
"""
import ast
from pathlib import Path

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.mongo_database_admin_mixin import MongoDatabaseAdminMixin
from cmdb.database.mongo_public_id_counter_mixin import MongoPublicIdCounterMixin
from tests.utils.pylint_limits import REPO_ROOT, pylint_limit
# -------------------------------------------------------------------------------------------------------------------- #

DATABASE_PACKAGE: Path = REPO_ROOT / 'cmdb' / 'database'
PART_MODULES: list[str] = ['mongo_database_manager.py', 'mongo_database_admin_mixin.py',
                           'mongo_public_id_counter_mixin.py', 'mongo_error_helper.py']

ADMIN_METHODS: frozenset[str] = frozenset({
    'target_database', 'check_database_exists', 'create_database', 'drop_database', 'create_collection',
    'get_collection', 'create_indexes', 'drop_index', 'get_index_info',
})
COUNTER_METHODS: frozenset[str] = frozenset({
    'init_public_id_counter', 'get_next_public_id', 'reserve_public_ids', 'reset_public_id_counter',
    'set_public_id_counter', 'update_public_id_counter', 'get_highest_id',
})
DOCUMENT_METHODS: frozenset[str] = frozenset({
    'reset_connection', 'status', 'insert', 'insert_many', 'bulk_write', 'update', 'replace', 'upsert_set', 'upsert',
    'update_many', 'update_many_raw', 'get_distinct', 'find_all', 'find', 'find_one_by', 'find_one', 'count',
    'aggregate', 'aggregate_all', 'aggregate_within_time_limit', 'delete', 'find_one_and_delete', 'delete_many_raw',
})


def _public_methods(part: type) -> set[str]:
    """The public methods a class defines itself"""
    return {name for name, member in vars(part).items() if callable(member) and not name.startswith('_')}


def test_the_public_api_is_exactly_the_listed_one() -> None:
    """Nothing a caller uses went missing in the split, nothing new appeared unnoticed"""
    api: set[str] = set().union(*(_public_methods(part) for part in MongoDatabaseManager.__mro__ if part is not object))

    assert api == ADMIN_METHODS | COUNTER_METHODS | DOCUMENT_METHODS


@pytest.mark.parametrize('part, expected', [
    (MongoDatabaseAdminMixin, ADMIN_METHODS),
    (MongoPublicIdCounterMixin, COUNTER_METHODS),
    (MongoDatabaseManager, DOCUMENT_METHODS),
], ids=['admin', 'counters', 'documents'])
def test_each_method_lives_in_its_part(part: type, expected: frozenset[str]) -> None:
    """The manager overrides no mixin method - one definition each"""
    assert _public_methods(part) == expected


def test_the_parts_resolve_in_a_fixed_order() -> None:
    """The counters read collections through the admin half's get_collection"""
    assert MongoDatabaseManager.__mro__ == (MongoDatabaseManager, MongoDatabaseAdminMixin, MongoPublicIdCounterMixin,
                                            object)
    assert MongoDatabaseManager.get_collection is MongoDatabaseAdminMixin.get_collection


def test_the_private_counter_helper_is_the_mixins() -> None:
    """insert raises the counter through it"""
    assert MongoDatabaseManager._raise_counter_to_stored_id is \
        MongoPublicIdCounterMixin._raise_counter_to_stored_id  # pylint: disable=protected-access


def test_delete_collection_is_gone() -> None:
    """It had no caller"""
    assert not hasattr(MongoDatabaseManager, 'delete_collection')


@pytest.mark.parametrize('module', PART_MODULES)
def test_no_part_is_over_the_module_length_limit(module: str) -> None:
    """max-module-lines"""
    lines: int = len((DATABASE_PACKAGE / module).read_text(encoding='utf-8').splitlines())

    assert lines <= pylint_limit('max-module-lines')


@pytest.mark.parametrize('module', PART_MODULES)
def test_no_class_is_over_the_public_method_limit(module: str) -> None:
    """max-public-methods - counted the way pylint counts, on each class's own methods"""
    tree = ast.parse((DATABASE_PACKAGE / module).read_text(encoding='utf-8'))
    counts: dict[str, int] = {
        node.name: sum(1 for item in node.body
                       if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'))
        for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    assert all(count <= pylint_limit('max-public-methods') for count in counts.values()), counts
