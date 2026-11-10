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
Integration tests for RiskAssessmentManager.get_missing_assessed_ids against a real MongoDB

The read the three RiskAssessment writes refuse an assessed object by: one projected ``$in`` over the objects or the
groups. An object of a denied type counts as missing - the same answer as an absent one - and a group is judged by
existence alone, the denied types ignored. An object id and a group id that share a number are told apart by the
reference type.
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.models.object_group_model import CmdbObjectGroup, ObjectReferenceType
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

OPEN_TYPE_ID: int = 943501
DENIED_TYPE_ID: int = 943502
OPEN_OBJECT_ID: int = 943511
HIDDEN_OBJECT_ID: int = 943512
MISSING_ID: int = 943519
GROUP_ID: int = 943521
SEEDED: dict[str, list[int]] = {
    CmdbObject.COLLECTION: [OPEN_OBJECT_ID, HIDDEN_OBJECT_ID],
    CmdbObjectGroup.COLLECTION: [GROUP_ID],
}


@pytest.fixture(name='manager')
def fixture_manager(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[RiskAssessmentManager]:
    """Two objects (one of the denied type) and a group; removed again"""
    def _purge() -> None:
        for collection, public_ids in SEEDED.items():
            database_manager.get_collection(collection, database_name).delete_many({'public_id': {'$in': public_ids}})

    _purge()
    database_manager.get_collection(CmdbObject.COLLECTION, database_name).insert_many([
        {'public_id': OPEN_OBJECT_ID, 'type_id': OPEN_TYPE_ID},
        {'public_id': HIDDEN_OBJECT_ID, 'type_id': DENIED_TYPE_ID},
    ])
    database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name).insert_one(
        {'public_id': GROUP_ID, 'name': 'Integration assessed group'})

    yield RiskAssessmentManager(database_manager)

    _purge()


@pytest.mark.parametrize('denied, missing', [
    ([], {MISSING_ID}),
    ([DENIED_TYPE_ID], {HIDDEN_OBJECT_ID, MISSING_ID}),
], ids=['nothing-denied', 'one-type-denied'])
def test_an_object_of_a_denied_type_counts_as_missing(manager: RiskAssessmentManager, denied: list[int],
                                                      missing: set[int]) -> None:
    """The open object never, the absent one always"""
    assert manager.get_missing_assessed_ids(
        ObjectReferenceType.OBJECT, {OPEN_OBJECT_ID, HIDDEN_OBJECT_ID, MISSING_ID}, denied,
    ) == missing


def test_a_group_is_judged_by_existence(manager: RiskAssessmentManager) -> None:
    """The denied types do not touch it"""
    assert manager.get_missing_assessed_ids(
        ObjectReferenceType.OBJECT_GROUP, {GROUP_ID, MISSING_ID}, [DENIED_TYPE_ID],
    ) == {MISSING_ID}


@pytest.mark.parametrize('reference_type, public_id', [
    (ObjectReferenceType.OBJECT_GROUP, OPEN_OBJECT_ID),
    (ObjectReferenceType.OBJECT, GROUP_ID),
], ids=['object-id-as-group', 'group-id-as-object'])
def test_the_reference_type_picks_the_collection(manager: RiskAssessmentManager, reference_type: Any,
                                                 public_id: int) -> None:
    """An object's id names no group, and the other way round"""
    assert manager.get_missing_assessed_ids(reference_type, {public_id}, []) == {public_id}
