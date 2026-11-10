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
Integration test for cmdb.database.updater.versions.updater_20261111 against a real MongoDB

Seeds a Threat whose source is an option of another list, a ControlMeasure whose source is ``true``, a Risk whose
category is an unknown id - next to a Vulnerability, a ControlMeasure and a Risk holding options of their own lists -
runs the migration twice and reads them back: the dirty values are null, the clean ones untouched, the second run a
no-op
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261111 import Update20261111
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRisk, IsmsThreat, IsmsVulnerability
# -------------------------------------------------------------------------------------------------------------------- #

TV_SOURCE: int = 943901
CM_SOURCE: int = 943902
CATEGORY: int = 943903
MISSING: int = 943909
DIRTY_THREAT: int = 943911
CLEAN_VULNERABILITY: int = 943912
DIRTY_MEASURE: int = 943913
CLEAN_MEASURE: int = 943914
DIRTY_RISK: int = 943915
CLEAN_RISK: int = 943916

SEEDED: dict[str, list[int]] = {
    CmdbExtendableOption.COLLECTION: [TV_SOURCE, CM_SOURCE, CATEGORY],
    IsmsThreat.COLLECTION: [DIRTY_THREAT],
    IsmsVulnerability.COLLECTION: [CLEAN_VULNERABILITY],
    IsmsControlMeasure.COLLECTION: [DIRTY_MEASURE, CLEAN_MEASURE],
    IsmsRisk.COLLECTION: [DIRTY_RISK, CLEAN_RISK],
}


@pytest.fixture(name='read')
def fixture_read(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded documents, removed afterwards; answers a reader of one stored value"""
    def _collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        for name, public_ids in SEEDED.items():
            _collection(name).delete_many({'public_id': {'$in': public_ids}})

    _purge()
    _collection(CmdbExtendableOption.COLLECTION).insert_many([
        {'public_id': TV_SOURCE, 'value': 'Integration tv 943901',
         'option_type': OptionType.THREAT_VULNERABILITY.value},
        {'public_id': CM_SOURCE, 'value': 'Integration cm 943902', 'option_type': OptionType.CONTROL_MEASURE.value},
        {'public_id': CATEGORY, 'value': 'Integration risk 943903', 'option_type': OptionType.RISK.value},
    ])
    _collection(IsmsThreat.COLLECTION).insert_one({'public_id': DIRTY_THREAT, 'name': 'd', 'source': CM_SOURCE})
    _collection(IsmsVulnerability.COLLECTION).insert_one({'public_id': CLEAN_VULNERABILITY, 'name': 'c',
                                                          'source': TV_SOURCE})
    _collection(IsmsControlMeasure.COLLECTION).insert_many([
        {'public_id': DIRTY_MEASURE, 'title': 'd', 'source': True},
        {'public_id': CLEAN_MEASURE, 'title': 'c', 'source': CM_SOURCE},
    ])
    _collection(IsmsRisk.COLLECTION).insert_many([
        {'public_id': DIRTY_RISK, 'name': 'd', 'category_id': MISSING},
        {'public_id': CLEAN_RISK, 'name': 'c', 'category_id': CATEGORY},
    ])

    def _read(name: str, public_id: int, key: str) -> Any:
        return _collection(name).find_one({'public_id': public_id})[key]

    yield _read
    _purge()


def _values(read: Any) -> list[Any]:
    """Every seeded value"""
    return [read(IsmsThreat.COLLECTION, DIRTY_THREAT, 'source'),
            read(IsmsVulnerability.COLLECTION, CLEAN_VULNERABILITY, 'source'),
            read(IsmsControlMeasure.COLLECTION, DIRTY_MEASURE, 'source'),
            read(IsmsControlMeasure.COLLECTION, CLEAN_MEASURE, 'source'),
            read(IsmsRisk.COLLECTION, DIRTY_RISK, 'category_id'),
            read(IsmsRisk.COLLECTION, CLEAN_RISK, 'category_id')]


def test_the_migration_nulls_the_out_of_list_values_and_is_rerun_safe(database_manager: MongoDatabaseManager,
                                                                     database_name: str, read: Any) -> None:
    """Dirty ones null, clean ones kept, the second run a no-op"""
    Update20261111(database_manager, database_name).start_update()

    assert _values(read) == [None, TV_SOURCE, None, CM_SOURCE, None, CATEGORY]

    Update20261111(database_manager, database_name).start_update()

    assert _values(read) == [None, TV_SOURCE, None, CM_SOURCE, None, CATEGORY]
