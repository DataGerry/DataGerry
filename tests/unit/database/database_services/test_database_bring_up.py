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
Unit tests for cmdb.database.database_services.database_bring_up

DB-free: `CollectionValidator` and `DatabaseUpdater` are patched at the module path and the database manager is a
MagicMock. Pinned: the decision table (stamp / migrate / nothing), that the data check asks each collection for one
document only, that the validation runs before the stamp is read and nothing follows a failed validation, and that
the on-premise flag reaches the validator
"""
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest

from cmdb.database.database_services import database_bring_up
from cmdb.database.database_services.database_bring_up import (
    DATA_COLLECTIONS,
    bring_database_up_to_date,
    database_holds_data,
    decide_update_action,
)
from cmdb.database.database_services.database_services_constants import UpdateAction
from cmdb.errors.updater import UpdaterException
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.database.database_services.database_bring_up'
DB_NAME: str = 'bring_up_db'
HIGHEST: int = 20261111
BEHIND: int = 20260101


# -------------------------------------------------------------------------------------------------------------------- #
#                                               decide_update_action                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('stored, holds_data, expected', [
    (None, False, UpdateAction.STAMP),
    (None, True, UpdateAction.MIGRATE),
    (BEHIND, False, UpdateAction.MIGRATE),
    (BEHIND, True, UpdateAction.MIGRATE),
    (HIGHEST, False, UpdateAction.NONE),
    (HIGHEST, True, UpdateAction.NONE),
    (0, False, UpdateAction.MIGRATE),
], ids=['unstamped-empty', 'unstamped-with-data', 'behind-empty', 'behind-with-data', 'current-empty',
        'current-with-data', 'zero-is-a-stamp'])
def test_decide_update_action(stored: int | None, holds_data: bool, expected: UpdateAction) -> None:
    """Only a database without a stamp AND without data is stamped; a stamp is never second-guessed by the data"""
    assert decide_update_action(stored, holds_data, HIGHEST) == expected


# -------------------------------------------------------------------------------------------------------------------- #
#                                               database_holds_data                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_data_collections_are_types_and_objects() -> None:
    """What a migration could transform"""
    assert DATA_COLLECTIONS == (CmdbType.COLLECTION, CmdbObject.COLLECTION)


@pytest.mark.parametrize('counts, expected', [((0, 0), False), ((1, 0), True), ((0, 1), True)],
                         ids=['empty', 'a-type', 'an-object'])
def test_database_holds_data(counts: tuple[int, int], expected: bool) -> None:
    """Any type or any object is data"""
    dbm = MagicMock()
    dbm.count.side_effect = lambda collection, *_args, **_kwargs: counts[DATA_COLLECTIONS.index(collection)]

    assert database_holds_data(dbm, DB_NAME) is expected


def test_database_holds_data_asks_for_one_document_per_collection() -> None:
    """An existence check, never a full count - and it stops at the first hit"""
    dbm = MagicMock()
    dbm.count.return_value = 0

    database_holds_data(dbm, DB_NAME)

    assert dbm.count.call_args_list == [call(collection, DB_NAME, {}, limit=1) for collection in DATA_COLLECTIONS]

    dbm.count.reset_mock()
    dbm.count.return_value = 1
    database_holds_data(dbm, DB_NAME)

    assert dbm.count.call_count == 1


# -------------------------------------------------------------------------------------------------------------------- #
#                                             bring_database_up_to_date                                                #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='patched')
def fixture_patched() -> Iterator[tuple[MagicMock, MagicMock]]:
    """The validator and the updater classes, the updater at HIGHEST"""
    with patch(f'{MODULE_PATH}.CollectionValidator') as validator, \
         patch(f'{MODULE_PATH}.DatabaseUpdater') as updater:
        updater.return_value.get_highest_update_version.return_value = HIGHEST
        yield validator, updater


def _bring_up(updater: MagicMock, stored: int | None, holds_data: bool, **kwargs: Any) -> UpdateAction:
    """Runs the bring-up with the stamp and the data as given"""
    updater.return_value.read_stored_update_version.return_value = stored
    dbm = MagicMock()
    dbm.count.return_value = int(holds_data)

    return bring_database_up_to_date(dbm, DB_NAME, **kwargs)


def test_an_unstamped_empty_database_is_stamped_and_not_migrated(patched: tuple[MagicMock, MagicMock]) -> None:
    """A new database - and a first setup that failed after the validator created something - is stamped"""
    _, updater = patched

    assert _bring_up(updater, None, False) == UpdateAction.STAMP
    updater.return_value.set_update_version.assert_called_once_with(HIGHEST)
    updater.return_value.run_updates.assert_not_called()


@pytest.mark.parametrize('stored, holds_data', [(None, True), (BEHIND, False), (BEHIND, True)],
                         ids=['unstamped-with-data', 'behind-empty', 'behind-with-data'])
def test_a_database_with_something_to_migrate_is_migrated_and_not_stamped(
        patched: tuple[MagicMock, MagicMock], stored: int | None, holds_data: bool) -> None:
    """The migrations write their own stamps"""
    _, updater = patched

    assert _bring_up(updater, stored, holds_data) == UpdateAction.MIGRATE
    updater.return_value.run_updates.assert_called_once_with()
    updater.return_value.set_update_version.assert_not_called()


def test_a_current_database_is_left_alone(patched: tuple[MagicMock, MagicMock]) -> None:
    """Validated, nothing else"""
    validator, updater = patched

    assert _bring_up(updater, HIGHEST, True) == UpdateAction.NONE
    validator.return_value.validate_collections.assert_called_once_with()
    updater.return_value.run_updates.assert_not_called()
    updater.return_value.set_update_version.assert_not_called()


def test_the_stamp_is_read_after_the_validation(patched: tuple[MagicMock, MagicMock]) -> None:
    """The decision sees the validated database"""
    validator, updater = patched
    order: list[str] = []
    validator.return_value.validate_collections.side_effect = lambda: order.append('validate')
    updater.return_value.read_stored_update_version.side_effect = lambda: order.append('read') or HIGHEST

    bring_database_up_to_date(MagicMock(), DB_NAME)

    assert order == ['validate', 'read']


def test_a_failed_validation_writes_no_stamp(patched: tuple[MagicMock, MagicMock]) -> None:
    """It raises before anything is decided, so the next run decides again"""
    validator, updater = patched
    validator.return_value.validate_collections.side_effect = UpdaterException('broken')

    with pytest.raises(UpdaterException):
        _bring_up(updater, None, False)

    updater.return_value.set_update_version.assert_not_called()
    updater.return_value.run_updates.assert_not_called()


def test_a_damaged_stamp_raises_and_nothing_is_written(patched: tuple[MagicMock, MagicMock]) -> None:
    """The updater's refusal passes through - a damaged stamp is never overwritten"""
    _, updater = patched
    updater.return_value.read_stored_update_version.side_effect = UpdaterException('damaged')

    with pytest.raises(UpdaterException):
        bring_database_up_to_date(MagicMock(), DB_NAME)

    updater.return_value.set_update_version.assert_not_called()


@pytest.mark.parametrize('kwargs, on_premise', [({}, False), ({'on_premise': True}, True)],
                         ids=['default-tenant', 'on-premise'])
def test_the_on_premise_flag_reaches_the_validator(patched: tuple[MagicMock, MagicMock], kwargs: dict[str, Any],
                                                   on_premise: bool) -> None:
    """It gates the key generation and the default admin user"""
    validator, updater = patched
    dbm = MagicMock()
    updater.return_value.read_stored_update_version.return_value = HIGHEST

    bring_database_up_to_date(dbm, DB_NAME, **kwargs)

    validator.assert_called_once_with(DB_NAME, dbm, on_premise=on_premise)
    updater.assert_called_once_with(dbm, DB_NAME)


def test_the_package_exports_the_bring_up() -> None:
    """Consumers import it from the package"""
    from cmdb.database import database_services  # pylint: disable=import-outside-toplevel

    assert database_services.bring_database_up_to_date is database_bring_up.bring_database_up_to_date
