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
Unit tests for how the BaseManager is put together

Every manager is a BaseManager, which is built from three parts: its own CRUD and aggregation methods,
OtherCollectionAccessMixin (reads, counts and deletes in another collection) and PublicIdCounterAccessMixin (the
public_id counters). What is pinned: the public API every manager relies on is exactly the one listed, each method
lives in the part it belongs to, the manager overrides none of the inherited ones, no manager subclass overrides a
mixin method, and the mixins resolve in a fixed order. The public-method limit itself is held tree-wide by
tests/unit/test_public_method_tripwire.py
"""
import importlib
import inspect
import pkgutil

import pytest

import cmdb.manager
from cmdb.manager.base_manager import BaseManager
from cmdb.manager.other_collection_access_mixin import OtherCollectionAccessMixin
from cmdb.manager.public_id_counter_access_mixin import PublicIdCounterAccessMixin
# -------------------------------------------------------------------------------------------------------------------- #

OTHER_COLLECTION_METHODS: frozenset[str] = frozenset({
    'get_one_from_other_collection', 'count_from_other_collection', 'get_many_from_other_collection',
    'delete_many_from_other_collection',
})
COUNTER_METHODS: frozenset[str] = frozenset({
    'get_next_public_id', 'reserve_public_ids', 'reset_public_id_counter_of', 'set_public_id_counter_of',
})
OWN_METHODS: frozenset[str] = frozenset({
    'insert', 'insert_many', 'get_distinct', 'aggregate_query', 'iterate_query', 'get_one', 'find_all', 'find',
    'get_one_by', 'get_many', 'aggregate_all', 'aggregate_within_time_limit', 'count_documents', 'update', 'replace',
    'upsert', 'update_many', 'update_many_pull', 'update_many_raw', 'bulk_write', 'delete', 'find_one_and_delete',
    'delete_many',
})
MIXINS: dict[type, frozenset[str]] = {
    OtherCollectionAccessMixin: OTHER_COLLECTION_METHODS,
    PublicIdCounterAccessMixin: COUNTER_METHODS,
}


def _public_methods(part: type) -> set[str]:
    """The public methods a class defines itself"""
    return {name for name, member in vars(part).items()
            if not name.startswith('_') and (callable(member) or isinstance(member, staticmethod))}


def _manager_classes() -> list[type]:
    """Every BaseManager subclass defined in the cmdb.manager package"""
    for module in pkgutil.walk_packages(cmdb.manager.__path__, f'{cmdb.manager.__name__}.'):
        importlib.import_module(module.name)

    found: list[type] = []
    pending: list[type] = [BaseManager]

    while pending:
        for subclass in pending.pop().__subclasses__():
            found.append(subclass)
            pending.append(subclass)

    return found


def test_the_public_api_is_exactly_the_listed_one() -> None:
    """Nothing a manager uses went missing in the split, nothing new appeared unnoticed"""
    api: set[str] = set().union(*(_public_methods(part) for part in BaseManager.__mro__ if part is not object))

    assert api == OWN_METHODS | OTHER_COLLECTION_METHODS | COUNTER_METHODS


@pytest.mark.parametrize('part, expected', [(BaseManager, OWN_METHODS), *MIXINS.items()],
                         ids=['BaseManager', 'OtherCollectionAccessMixin', 'PublicIdCounterAccessMixin'])
def test_each_method_lives_in_its_part(part: type, expected: frozenset[str]) -> None:
    """The base class does not redefine what a mixin holds"""
    assert _public_methods(part) == expected


def test_the_parts_resolve_in_a_fixed_order() -> None:
    """Base first, then the cross-collection part, then the counters"""
    assert BaseManager.__mro__[1:4] == (OtherCollectionAccessMixin, PublicIdCounterAccessMixin, object)


def test_the_acl_step_is_private() -> None:
    """Only iterate_query applies a reader's ACL to builder parameters"""
    assert not hasattr(BaseManager, 'apply_acl_to_builder_params')
    assert hasattr(BaseManager, '_apply_acl_to_builder_params')


def test_the_scan_finds_the_managers() -> None:
    """A moved package cannot make the override check pass on nothing"""
    assert len(_manager_classes()) >= len(OWN_METHODS)


@pytest.mark.parametrize('mixin, methods', MIXINS.items(), ids=lambda value: getattr(value, '__name__', ''))
def test_no_manager_overrides_a_mixin_method(mixin: type, methods: frozenset[str]) -> None:
    """Every manager reaches another collection and the counters the same way"""
    overridden: dict[str, list[str]] = {
        manager.__qualname__: sorted(methods & set(vars(manager)))
        for manager in _manager_classes() if methods & set(vars(manager))
    }

    assert not overridden, f'{mixin.__name__}: {overridden}'


def test_delete_all_is_a_keyword_only_option() -> None:
    """The full delete is named at the call, never passed by position"""
    parameter = inspect.signature(OtherCollectionAccessMixin.delete_many_from_other_collection).parameters['delete_all']

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is False
