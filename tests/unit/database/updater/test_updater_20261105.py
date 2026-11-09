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
Unit tests for cmdb.database.updater.versions.updater_20261105

The migration keeps one field value per name on every object relation. Its run against a real database is its own
integration test; this module owns the frozen literals, the write it sends, the version bump and the failure tail
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261105 as module
from cmdb.database.updater.versions.updater_20261105 import Update20261105
from cmdb.models.object_relation_model import CmdbObjectRelation, ObjectRelationKey
from cmdb.models.object_relation_model.object_relation_constants import ObjectRelationFieldValueKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261105
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'object relations gone'


def _updater(modified_count: int) -> tuple[Update20261105, MagicMock]:
    """The migration over a mocked database manager whose update changes `modified_count` documents"""
    dbm = MagicMock()
    dbm.update_many_raw.return_value = MagicMock(modified_count=modified_count)
    updater = Update20261105(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.OBJECT_RELATIONS_COLLECTION, CmdbObjectRelation.COLLECTION),
    (module.FIELD_VALUES_FIELD, ObjectRelationKey.FIELD_VALUES.value),
    (module.FIELD_NAME_KEY, ObjectRelationFieldValueKey.NAME.value),
], ids=['collection', 'field-values-key', 'name-key'])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The literals were frozen from the code's own"""
    assert frozen == live


def test_only_an_instance_repeating_a_name_is_matched() -> None:
    """An array whose name count differs from its distinct name count - what makes a second run match nothing"""
    held = {'$ifNull': ['$field_values.name', []]}

    assert module.REPEATED_NAME_CRITERIA == {
        'field_values': {'$type': 'array'},
        '$expr': {'$ne': [{'$size': held}, {'$size': {'$setUnion': [held, []]}}]},
    }


def test_the_rewrite_keeps_the_first_entry_of_each_name() -> None:
    """A $reduce in stored order appends an entry only while its name is not kept yet"""
    assert module.FIRST_ENTRY_PER_NAME_REWRITE == [{'$set': {'field_values': {'$reduce': {
        'input': '$field_values',
        'initialValue': [],
        'in': {'$cond': [
            {'$in': ['$$this.name', '$$value.name']},
            '$$value',
            {'$concatArrays': ['$$value', ['$$this']]},
        ]},
    }}}}]


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater(0)

    assert updater.creation_date() == CREATION_DATE
    assert 'object relation' in updater.description()


@pytest.mark.parametrize('modified_count', [3, 0], ids=['repeated-names', 'nothing-to-do'])
def test_rewrites_the_instances_and_bumps_the_version(modified_count: int) -> None:
    """One pipeline update on the object relations; the version moves whether or not there was something to do"""
    updater, dbm = _updater(modified_count)

    updater.start_update()

    dbm.update_many_raw.assert_called_once_with(module.OBJECT_RELATIONS_COLLECTION, DATABASE_NAME,
                                                module.REPEATED_NAME_CRITERIA, module.FIRST_ENTRY_PER_NAME_REWRITE)
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failed_update_is_the_updater_exception_carrying_it() -> None:
    """The failure tail wraps the exception itself, and the version does not move"""
    updater, dbm = _updater(0)
    failure = RuntimeError(DB_FAILURE)
    dbm.update_many_raw.side_effect = failure

    with pytest.raises(UpdaterException) as caught:
        updater.start_update()

    assert caught.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
