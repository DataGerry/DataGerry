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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.database.updater.versions.updater_20261122

The migration drops the required flag of a person's first and last name on every Type carrying PERSON. Its run
against a real database is its own integration test; this module owns the frozen literals, the write it sends, the
version bump and the failure tail
"""
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261122 as module
from cmdb.database.updater.versions.updater_20261122 import Update20261122
from cmdb.models.special_type_model.person_type_constants import PersonField
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType, FieldKey, TypeSchemaKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261122
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'types gone'


def _updater(modified_count: int) -> tuple[Update20261122, MagicMock]:
    """The migration over a mocked database manager whose update changes `modified_count` documents"""
    dbm = MagicMock()
    dbm.update_many_raw.return_value = MagicMock(modified_count=modified_count)
    updater = Update20261122(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


@pytest.mark.parametrize('frozen, live', [
    (module.TYPES, CmdbType.COLLECTION),
    (module.SPECIAL_TYPE, TypeSchemaKey.SPECIAL_TYPE.value),
    (module.PERSON, SpecialType.PERSON.value),
    (module.FIELDS, TypeSchemaKey.FIELDS.value),
    (module.FIELD_NAME, FieldKey.NAME.value),
    (module.REQUIRED, FieldKey.REQUIRED.value),
    (module.NAME_FIELDS, [PersonField.FIRST_NAME.value, PersonField.LAST_NAME.value]),
], ids=['collection', 'marker-key', 'marker', 'fields-key', 'name-key', 'required-key', 'name-fields'])
def test_the_frozen_literals_still_match_the_code(frozen: object, live: object) -> None:
    """The literals were frozen from the code's own"""
    assert frozen == live


def test_only_a_person_type_still_flagging_a_name_is_matched() -> None:
    """What makes a second run match nothing - and leaves every other Type alone"""
    assert module.TYPES_STILL_REQUIRING == {
        'special_type': 'PERSON',
        'fields': {'$elemMatch': {'name': {'$in': ['first_name', 'last_name']}, 'required': {'$exists': True}}},
    }


def test_only_the_two_name_fields_lose_the_flag() -> None:
    """The positional unset names the two fields through the array filter; no other field is touched"""
    assert module.DROP_REQUIRED == {'$unset': {'fields.$[namefield].required': ''}}
    assert module.NAME_FIELD_FILTERS == [{'namefield.name': {'$in': ['first_name', 'last_name']}}]


def test_the_version_and_description() -> None:
    """Dated like its module"""
    updater, _dbm = _updater(0)

    assert updater.creation_date() == CREATION_DATE
    assert 'first and last name' in updater.description()


@pytest.mark.parametrize('modified_count', [1, 0], ids=['flagged', 'nothing-to-do'])
def test_drops_the_flags_and_bumps_the_version(modified_count: int) -> None:
    """One update on the Types; the version moves whether or not there was something to drop"""
    updater, dbm = _updater(modified_count)

    updater.start_update()

    dbm.update_many_raw.assert_called_once_with(module.TYPES, DATABASE_NAME, module.TYPES_STILL_REQUIRING,
                                                module.DROP_REQUIRED, array_filters=module.NAME_FIELD_FILTERS)
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
