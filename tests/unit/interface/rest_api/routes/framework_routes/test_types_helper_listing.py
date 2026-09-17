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
Unit tests for the CmdbType listing helpers in ``types_helper``

The three functions the two listing routes call before they query: ``build_type_criteria`` (the
``active`` flag merged into the client's criteria), ``build_category_criteria`` (``?category=`` /
``?uncategorized=`` resolved against the CategoriesManager) and ``prepare_builder_parameters``, which
composes them into the BuilderParameters.

Split out of ``test_types_helper`` on 2026-09-17, when that module went past pylint's 1,500-line cap.
They are one subject: what a **read** hands to the query. Everything about a type **write** - the
guards, the side effects, the ACL normalisation - stayed behind.
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.type_model.type_schema_key_enum import TypeSchemaKey
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper import (
    build_category_criteria,
    build_type_criteria,
    prepare_builder_parameters,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_helper'


def _patch_managers_by_type(managers: dict) -> Any:
    """Patches ManagerProvider.get_manager to return the mock registered for each ManagerType."""
    return patch(f'{PATH}.ManagerProvider.get_manager', side_effect=lambda mtype, _user: managers[mtype])


def _listing_params(
        active: bool = True,
        criteria: Any = None,
        category: int | None = None,
        uncategorized: bool = False) -> SimpleNamespace:
    """The TypeIterationParameters fields the listing helpers read."""
    return SimpleNamespace(
        active=active,
        filter={'name': 'x'} if criteria is None else criteria,
        category=category,
        uncategorized=uncategorized,
    )

def test_build_type_criteria_adds_active_to_dict_criteria_with_keys() -> None:
    """An active flag is merged into a non-empty dict criteria."""
    assert build_type_criteria({'name': 'x'}, True) == {'name': 'x', TypeSchemaKey.ACTIVE.value: True}

def test_build_type_criteria_keeps_empty_dict_criteria_a_dict() -> None:
    """An empty dict criteria stays a dict instead of becoming a pipeline with an empty $match."""
    assert build_type_criteria({}, True) == {TypeSchemaKey.ACTIVE.value: True}

def test_build_type_criteria_appends_active_match_to_list_criteria() -> None:
    """An active flag is appended as a $match stage to an existing list criteria."""
    result = build_type_criteria([{'$match': {'name': 'x'}}], True)

    assert result == [{'$match': {'name': 'x'}}, {'$match': {TypeSchemaKey.ACTIVE.value: True}}]

def test_build_type_criteria_returns_criteria_unchanged_when_inactive() -> None:
    """A falsy active flag restricts nothing and hands the criteria straight back."""
    client_criteria = {'name': 'x'}

    assert build_type_criteria(client_criteria, False) == {'name': 'x'}

def test_build_type_criteria_does_not_mutate_the_dict_it_was_given() -> None:
    """The client's dict criteria is left exactly as it arrived - it is echoed back in the response."""
    client_criteria = {'name': 'x'}

    build_type_criteria(client_criteria, True)

    assert client_criteria == {'name': 'x'}

def test_build_type_criteria_does_not_mutate_the_list_it_was_given() -> None:
    """The client's list criteria is left exactly as it arrived - it is echoed back in the response."""
    client_criteria = [{'$match': {'name': 'x'}}]

    build_type_criteria(client_criteria, True)

    assert client_criteria == [{'$match': {'name': 'x'}}]

def test_prepare_builder_parameters_passes_the_merged_criteria_to_the_builder() -> None:
    """The merged criteria replaces the criteria the pager handed over."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params',
               return_value={'criteria': {'name': 'x'}, 'limit': 10}), \
         patch(f'{PATH}.BuilderParameters') as builder_params:
        prepare_builder_parameters(type_params, MagicMock())

    assert builder_params.call_args.kwargs['criteria'] == {'name': 'x', TypeSchemaKey.ACTIVE.value: True}
    assert builder_params.call_args.kwargs['limit'] == 10

def test_prepare_builder_parameters_leaves_the_echoed_filter_untouched() -> None:
    """The pager's own filter is never mutated, so the response echoes what the client sent."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {'name': 'x'}}), \
         patch(f'{PATH}.BuilderParameters'):
        prepare_builder_parameters(type_params, MagicMock())

    assert type_params.filter == {'name': 'x'}

def test_prepare_builder_parameters_adds_no_category_criteria_without_the_parameters() -> None:
    """An ordinary listing never reaches the CategoriesManager."""
    type_params = _listing_params()

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {}}), \
         patch(f'{PATH}.BuilderParameters') as builder_params, \
         patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        prepare_builder_parameters(type_params, MagicMock())

    provider.assert_not_called()
    builder_params.return_value.add_criteria.assert_not_called()

def test_prepare_builder_parameters_adds_the_category_criteria_when_asked() -> None:
    """A category filter lands on the BuilderParameters, not in the echoed pager filter."""
    type_params = _listing_params(category=4)
    categories = MagicMock()
    categories.get_category_type_ids.return_value = [7, 8]

    with patch(f'{PATH}.CollectionParameters.get_builder_params', return_value={'criteria': {}}), \
         patch(f'{PATH}.BuilderParameters') as builder_params, \
         _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        prepare_builder_parameters(type_params, MagicMock())

    builder_params.return_value.add_criteria.assert_called_once_with(
        {TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]}}
    )

def test_build_category_criteria_returns_none_without_either_parameter() -> None:
    """No category filter was asked for, so nothing is added."""
    with patch(f'{PATH}.ManagerProvider.get_manager') as provider:
        assert build_category_criteria(_listing_params(), MagicMock()) is None

    provider.assert_not_called()

def test_build_category_criteria_restricts_to_the_categorys_types() -> None:
    """?category=<id> filters this collection on the ids the category holds."""
    categories = MagicMock()
    categories.get_category_type_ids.return_value = [7, 8]

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(category=4), MagicMock())

    categories.get_category_type_ids.assert_called_once_with(4)
    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$in': [7, 8]}}

def test_build_category_criteria_for_an_unassigned_category_matches_nothing() -> None:
    """A category holding no types - or none at all - yields an empty list, not every type."""
    categories = MagicMock()
    categories.get_category_type_ids.return_value = []

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(category=99), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$in': []}}

def test_build_category_criteria_excludes_every_assigned_type_when_uncategorized() -> None:
    """?uncategorized=true is the complement of 'assigned to any category'."""
    categories = MagicMock()
    categories.get_assigned_type_ids.return_value = {9, 2, 5}

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(uncategorized=True), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$nin': [2, 5, 9]}}

def test_build_category_criteria_with_nothing_categorized_excludes_nothing() -> None:
    """Every type is uncategorized when no category holds any."""
    categories = MagicMock()
    categories.get_assigned_type_ids.return_value = set()

    with _patch_managers_by_type({ManagerType.CATEGORIES: categories}):
        criteria = build_category_criteria(_listing_params(uncategorized=True), MagicMock())

    assert criteria == {TypeSchemaKey.PUBLIC_ID.value: {'$nin': []}}
