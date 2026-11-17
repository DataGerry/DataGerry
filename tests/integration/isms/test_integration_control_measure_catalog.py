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
Integration tests of the catalog methods of ControlMeasureManager against a real MongoDB

Pinned: a catalog's controls are read trimmed and only that catalog's; the bulk update sets the given keys of each
control and leaves every other key - and every other control - alone; the count per catalog leaves out a control
without a catalog, whether the key is missing, null or blank
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.models.isms_model import IsmsControlMeasure
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
# -------------------------------------------------------------------------------------------------------------------- #

CATALOG_ID: str = 'test-catalog-manager'
OTHER_CATALOG_ID: str = 'test-catalog-manager-other'

CATALOG_A1: int = 98601
CATALOG_A2: int = 98602
OTHER_B1: int = 98603
MANUAL_MISSING: int = 98604
MANUAL_NULL: int = 98605
MANUAL_BLANK: int = 98606
ALL_IDS: list[int] = [CATALOG_A1, CATALOG_A2, OTHER_B1, MANUAL_MISSING, MANUAL_NULL, MANUAL_BLANK]

ANSWERED_REASON: str = 'kept by the ISMS team'


MISSING: object = object()


def _control(public_id: int, identifier: str, catalog: Any) -> dict[str, Any]:
    """A stored control; ``MISSING`` leaves the catalog key out, any other value is stored as it is"""
    document: dict[str, Any] = {
        ControlMeasureKey.PUBLIC_ID.value: public_id,
        ControlMeasureKey.IDENTIFIER.value: identifier,
        ControlMeasureKey.TITLE.value: f'Title {identifier}',
        ControlMeasureKey.REASON.value: ANSWERED_REASON,
    }

    if catalog is not MISSING:
        document[ControlMeasureKey.CATALOG_ID.value] = catalog

    return document


@pytest.fixture(name='controls')
def fixture_controls(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded controls of two catalogs and three manual ones, removed before and after"""
    collection = database_manager.get_collection(IsmsControlMeasure.COLLECTION, database_name)
    collection.delete_many({ControlMeasureKey.PUBLIC_ID.value: {'$in': ALL_IDS}})
    collection.insert_many([
        _control(CATALOG_A1, 'A.1', CATALOG_ID),
        _control(CATALOG_A2, 'A.2', CATALOG_ID),
        _control(OTHER_B1, 'B.1', OTHER_CATALOG_ID),
        _control(MANUAL_MISSING, 'M.1', MISSING),
        _control(MANUAL_NULL, 'M.2', None),
        _control(MANUAL_BLANK, 'M.3', ''),
    ])

    yield collection

    collection.delete_many({ControlMeasureKey.PUBLIC_ID.value: {'$in': ALL_IDS}})


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> ControlMeasureManager:
    """A ControlMeasureManager on the test database"""
    return ControlMeasureManager(database_manager, database_name)


def test_a_catalogs_controls_are_read_trimmed(manager: ControlMeasureManager, controls: Any) -> None:
    """Only that catalog's controls, with public_id, identifier and the asked keys"""
    del controls

    read = manager.get_catalog_controls(CATALOG_ID, (ControlMeasureKey.TITLE.value,))

    assert sorted(read, key=lambda doc: doc[ControlMeasureKey.PUBLIC_ID.value]) == [
        {ControlMeasureKey.PUBLIC_ID.value: CATALOG_A1, ControlMeasureKey.IDENTIFIER.value: 'A.1',
         ControlMeasureKey.TITLE.value: 'Title A.1'},
        {ControlMeasureKey.PUBLIC_ID.value: CATALOG_A2, ControlMeasureKey.IDENTIFIER.value: 'A.2',
         ControlMeasureKey.TITLE.value: 'Title A.2'},
    ]


def test_the_bulk_update_sets_only_the_given_keys(manager: ControlMeasureManager, controls: Any) -> None:
    """Each control gets its own changes; its other keys and the controls not named stay"""
    modified = manager.update_catalog_fields([
        (CATALOG_A1, {ControlMeasureKey.TITLE.value: 'New A.1'}),
        (CATALOG_A2, {ControlMeasureKey.CHAPTER.value: 'Chapter 2'}),
    ])

    stored = {doc[ControlMeasureKey.PUBLIC_ID.value]: doc
              for doc in controls.find({ControlMeasureKey.PUBLIC_ID.value: {'$in': ALL_IDS}})}

    assert modified == 2
    assert stored[CATALOG_A1][ControlMeasureKey.TITLE.value] == 'New A.1'
    assert stored[CATALOG_A2][ControlMeasureKey.CHAPTER.value] == 'Chapter 2'
    assert stored[CATALOG_A2][ControlMeasureKey.TITLE.value] == 'Title A.2'
    assert all(doc[ControlMeasureKey.REASON.value] == ANSWERED_REASON for doc in stored.values())
    assert stored[OTHER_B1][ControlMeasureKey.TITLE.value] == 'Title B.1'


def test_the_count_leaves_out_controls_without_a_catalog(manager: ControlMeasureManager, controls: Any) -> None:
    """Missing, null and blank catalog ids are no catalog"""
    del controls

    counts = manager.count_controls_per_catalog()

    assert (counts[CATALOG_ID], counts[OTHER_CATALOG_ID]) == (2, 1)
    assert None not in counts and '' not in counts
