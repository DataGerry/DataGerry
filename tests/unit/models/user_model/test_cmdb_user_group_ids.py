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
Unit tests of a CmdbUser's group list - the schema rule, the model's canonical list and its read-only first group

Pinned through a real Validator on the create and the update schema: a list of 1..MAX_GROUPS_PER_USER distinct ids
passes; an empty list, a repeated id, an id that is no id, a single int and an oversized list are refused; the create
schema fills the default group, the update schema leaves an omitted list out. The model keeps the list sorted and
without repeats, falls back to the default group, writes a list and reads one
"""
from typing import Any

import pytest
from cerberus import Validator

from cmdb.class_schema.class_schema_constants import IDS_NOT_UNIQUE_MSG
from cmdb.class_schema.user_model.cmdb_user_schema import DEFAULT_GROUP, MAX_GROUPS_PER_USER
from cmdb.class_schema.write_schema_helper import build_update_schema, build_write_schema
from cmdb.models.user_model import CmdbUser, CmdbUserKey, canonical_group_ids
# -------------------------------------------------------------------------------------------------------------------- #

KEY: str = CmdbUserKey.GROUP_IDS.value
ADMIN_GROUP: int = 1
OTHER_GROUP: int = 5
THIRD_GROUP: int = 9
PUBLIC_ID: int = 42
USER_NAME: str = 'group-list-user'

CREATE_RULES: dict[str, Any] = {KEY: build_write_schema(CmdbUser.SCHEMA)[KEY]}
# As the update route builds it: no defaults, nothing required
UPDATE_RULES: dict[str, Any] = {KEY: build_update_schema(CmdbUser.SCHEMA, all_optional=True)[KEY]}

REFUSED_LISTS: list[Any] = [
    [], [OTHER_GROUP, OTHER_GROUP], [True], [0], ['5'], OTHER_GROUP, list(range(1, MAX_GROUPS_PER_USER + 2)),
]
REFUSED_LISTS_NAMES: list[str] = ['empty', 'repeated', 'boolean', 'zero', 'text', 'single-int', 'over-cap']


@pytest.mark.parametrize('rules', [CREATE_RULES, UPDATE_RULES], ids=['create', 'update'])
@pytest.mark.parametrize('value', REFUSED_LISTS, ids=REFUSED_LISTS_NAMES)
def test_a_list_that_is_no_group_list_is_refused(rules: dict[str, Any], value: Any) -> None:
    """At least one group, each once, each an id, at most the cap"""
    assert not Validator(rules).validate({KEY: value})


@pytest.mark.parametrize('rules', [CREATE_RULES, UPDATE_RULES], ids=['create', 'update'])
@pytest.mark.parametrize('value', [[OTHER_GROUP], [THIRD_GROUP, ADMIN_GROUP], list(range(1, MAX_GROUPS_PER_USER + 1))],
                         ids=['one', 'two-unsorted', 'at-cap'])
def test_a_group_list_passes(rules: dict[str, Any], value: list[int]) -> None:
    """The control - the order is free, the cap itself is allowed"""
    assert Validator(rules).validate({KEY: value})


def test_a_repeated_group_is_named() -> None:
    """The refusal names the repeated ids"""
    validator = Validator(CREATE_RULES)
    validator.validate({KEY: [THIRD_GROUP, OTHER_GROUP, THIRD_GROUP, OTHER_GROUP]})

    assert validator.errors == {KEY: [IDS_NOT_UNIQUE_MSG.format(ids=[OTHER_GROUP, THIRD_GROUP])]}


@pytest.mark.parametrize('document', [{}, {KEY: None}], ids=['left-out', 'null'])
def test_a_create_without_groups_gets_the_default_group(document: dict[str, Any]) -> None:
    """The create schema fills the default group - for a null too, as for the single group before"""
    validator = Validator(CREATE_RULES)

    assert validator.validate(document)
    assert validator.document == {KEY: [DEFAULT_GROUP]}


def test_an_update_refuses_null_groups() -> None:
    """No default on the update: null is no list"""
    assert not Validator(UPDATE_RULES).validate({KEY: None})


def test_an_update_without_groups_leaves_them_out() -> None:
    """The update schema has no default: the stored list is kept"""
    validator = Validator(UPDATE_RULES)

    assert validator.validate({})
    assert validator.document == {}


@pytest.mark.parametrize('given, expected', [
    (None, [DEFAULT_GROUP]), ([], [DEFAULT_GROUP]),
    ([THIRD_GROUP, ADMIN_GROUP, THIRD_GROUP], [ADMIN_GROUP, THIRD_GROUP]),
], ids=['none', 'empty', 'unsorted-repeated'])
def test_the_canonical_list_is_sorted_unique_and_never_empty(given: Any, expected: list[int]) -> None:
    """The stored form"""
    assert canonical_group_ids(given) == expected


def test_the_model_keeps_the_canonical_list() -> None:
    """Built from an unsorted list: stored sorted"""
    user = CmdbUser(public_id=PUBLIC_ID, user_name=USER_NAME, active=True, group_ids=[THIRD_GROUP, OTHER_GROUP])

    assert user.group_ids == [OTHER_GROUP, THIRD_GROUP]


def test_the_model_offers_no_single_group() -> None:
    """Every reader takes the whole list - no "first group" stands in for the others"""
    user = CmdbUser(public_id=PUBLIC_ID, user_name=USER_NAME, active=True, group_ids=[THIRD_GROUP, OTHER_GROUP])

    assert not hasattr(user, 'group_id')


def test_the_list_round_trips_through_the_document() -> None:
    """to_json writes a new list, from_data reads it back canonical"""
    user = CmdbUser(public_id=PUBLIC_ID, user_name=USER_NAME, active=True, group_ids=[THIRD_GROUP, ADMIN_GROUP])
    document = CmdbUser.to_json(user)

    assert document[KEY] == [ADMIN_GROUP, THIRD_GROUP]
    assert document[KEY] is not user.group_ids
    assert CmdbUser.from_data({**document, KEY: [THIRD_GROUP, ADMIN_GROUP]}).group_ids == [ADMIN_GROUP, THIRD_GROUP]
    assert 'group_id' not in document
