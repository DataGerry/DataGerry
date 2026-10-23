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
Integration tests of the IsmsRiskMatrix seeding across boot passes, against a real MongoDB

The predefined-data seeders run on every boot pass (``CollectionValidator.init_framework_collections``), so the
risk matrix seeder must insert the empty default only when the singleton is missing. Pinned on a scratch database
of its own: the first boot seeds the empty default once; a configured matrix - cells, unit - survives further boots
unchanged; a singleton that went missing is seeded again; and however many boots run, there is one singleton
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.database.predefined_data.isms_data.isms_risk_matrix_data import get_default_risk_matrix
from cmdb.models.isms_model import IsmsRiskMatrix
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
# -------------------------------------------------------------------------------------------------------------------- #

SCRATCH_SUFFIX: str = '-risk-matrix-seed'
PUBLIC_ID_KEY: str = 'public_id'
MONGO_ID_KEY: str = '_id'
MATRIX_KEY: str = 'risk_matrix'
UNIT_KEY: str = 'matrix_unit'
CONFIGURED_UNIT: str = 'EUR'
CONFIGURED_CELLS: list[dict[str, Any]] = [
    {'row': 0, 'column': 0, 'impact_id': 11, 'likelihood_id': 21, 'risk_class_id': 31, 'calculated_value': 1.0},
    {'row': 0, 'column': 1, 'impact_id': 11, 'likelihood_id': 22, 'risk_class_id': 32, 'calculated_value': 2.0},
]
BOOT_COUNT: int = 3


@pytest.fixture(name='scratch')
def fixture_scratch(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[str]:
    """An empty scratch database, dropped before and after"""
    scratch: str = f'{database_name}{SCRATCH_SUFFIX}'
    client = database_manager.connector.client
    client.drop_database(scratch)

    yield scratch

    client.drop_database(scratch)


def _boot(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One boot pass of the framework collections - what every startup runs"""
    CollectionValidator(scratch, database_manager).init_framework_collections()


def _matrices(database_manager: MongoDatabaseManager, scratch: str) -> list[dict[str, Any]]:
    """Every stored risk matrix, without `_id`"""
    return list(database_manager.get_collection(IsmsRiskMatrix.COLLECTION, scratch).find({}, {MONGO_ID_KEY: 0}))


def _configure(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """What configuring the matrix in the ISMS screens leaves in the singleton"""
    database_manager.get_collection(IsmsRiskMatrix.COLLECTION, scratch).update_one(
        {PUBLIC_ID_KEY: RISK_MATRIX_PUBLIC_ID}, {'$set': {MATRIX_KEY: CONFIGURED_CELLS, UNIT_KEY: CONFIGURED_UNIT}},
    )


def test_the_first_boot_seeds_the_empty_default(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """One singleton, exactly the default"""
    _boot(database_manager, scratch)

    assert _matrices(database_manager, scratch) == [get_default_risk_matrix()]


def test_a_configured_matrix_survives_a_restart(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Its cells and its unit are kept as configured"""
    _boot(database_manager, scratch)
    _configure(database_manager, scratch)

    _boot(database_manager, scratch)

    assert _matrices(database_manager, scratch) == [{
        PUBLIC_ID_KEY: RISK_MATRIX_PUBLIC_ID, MATRIX_KEY: CONFIGURED_CELLS, UNIT_KEY: CONFIGURED_UNIT,
    }]


def test_a_configured_matrix_survives_every_restart(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """Not only the next boot - and still one singleton"""
    _boot(database_manager, scratch)
    _configure(database_manager, scratch)

    for _ in range(BOOT_COUNT):
        _boot(database_manager, scratch)

    matrices: list[dict[str, Any]] = _matrices(database_manager, scratch)
    assert len(matrices) == 1
    assert (matrices[0][MATRIX_KEY], matrices[0][UNIT_KEY]) == (CONFIGURED_CELLS, CONFIGURED_UNIT)


def test_a_missing_singleton_is_seeded_again(database_manager: MongoDatabaseManager, scratch: str) -> None:
    """The collection exists but the matrix is gone - the next boot restores the empty default"""
    _boot(database_manager, scratch)
    database_manager.get_collection(IsmsRiskMatrix.COLLECTION, scratch).delete_many({})

    _boot(database_manager, scratch)

    assert _matrices(database_manager, scratch) == [get_default_risk_matrix()]
