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
Integration tests for the Field Rules manager against the test MongoDB

Pinned: every rule and the active ones in public_id order (an inactive one left out); a name counts as taken by another
rule only; the Type pull removes the Type from every rule listing it, leaves an emptied rule in place and changes
nothing the second time; after a reset the ids no longer stored are pulled the same way
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import FieldRulesManager
from cmdb.models.access_model import CmdbFieldRule
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID, OTHER_TYPE_ID = 9401, 9402
FIRST, SECOND, INACTIVE = 9411, 9412, 9413
RULES: list[dict[str, Any]] = [
    {'public_id': SECOND, 'name': 'second', 'description': '', 'active': True, 'types': [TYPE_ID],
     'when': {'changed': ['a']}, 'unless': None, 'set': {'b': 'x'}},
    {'public_id': FIRST, 'name': 'first', 'description': '', 'active': True, 'types': [TYPE_ID, OTHER_TYPE_ID],
     'when': {'changed': ['a']}, 'unless': None, 'set': {'c': 'x'}},
    {'public_id': INACTIVE, 'name': 'inactive', 'description': '', 'active': False, 'types': '*',
     'when': {'changed': ['a']}, 'unless': None, 'set': {'d': 'x'}},
]


@pytest.fixture(name='collection', autouse=True)
def fixture_collection(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The rules seeded as copies, removed after"""
    collection: Any = database_manager.get_collection(CmdbFieldRule.COLLECTION, database_name)
    collection.delete_many({})
    collection.insert_many([dict(rule) for rule in RULES])

    yield collection

    collection.delete_many({})


@pytest.fixture(name='rules')
def fixture_rules(database_manager: MongoDatabaseManager) -> FieldRulesManager:
    """The Field Rules manager on the test database"""
    return FieldRulesManager(database_manager)


def _ids(documents: list[dict[str, Any]]) -> list[int]:
    """The public_ids, in the order read"""
    return [document['public_id'] for document in documents]


def test_every_rule_and_the_active_ones_in_order(rules: FieldRulesManager) -> None:
    """Ascending public_id; the inactive one only in the full list; no Mongo id"""
    assert _ids(rules.all_rules()) == [FIRST, SECOND, INACTIVE]
    assert _ids(rules.active_rules()) == [FIRST, SECOND]
    assert all('_id' not in rule for rule in rules.all_rules())


def test_a_name_is_taken_by_another_rule_only(rules: FieldRulesManager) -> None:
    """The rule's own name is free for it"""
    assert rules.name_taken('first') is True
    assert rules.name_taken('first', FIRST) is False
    assert rules.name_taken('free') is False


def test_the_type_pull(rules: FieldRulesManager, collection: Any) -> None:
    """Every rule listing the Type loses it; an emptied rule stays; a second pull changes nothing"""
    assert rules.pull_type_from_rules(TYPE_ID) == 2
    assert {rule['public_id']: rule['types'] for rule in collection.find({}, {'_id': 0})} == {
        FIRST: [OTHER_TYPE_ID], SECOND: [], INACTIVE: '*'}
    assert rules.pull_type_from_rules(TYPE_ID) == 0


def test_the_missing_types_pull(rules: FieldRulesManager, collection: Any) -> None:
    """Only the stored ids stay; a rule on every Type is left alone; a second pull changes nothing"""
    assert rules.pull_missing_types([OTHER_TYPE_ID]) == 2
    assert {rule['public_id']: rule['types'] for rule in collection.find({}, {'_id': 0})} == {
        FIRST: [OTHER_TYPE_ID], SECOND: [], INACTIVE: '*'}
    assert rules.pull_missing_types([OTHER_TYPE_ID]) == 0
