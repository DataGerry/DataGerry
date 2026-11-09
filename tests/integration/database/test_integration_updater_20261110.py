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
Integration test for cmdb.database.updater.versions.updater_20261110 against a real MongoDB

Seeds what the old writes let through - a Risk whose lists hold a string, a boolean, an unknown id and a repeat; an
ImpactCategory describing ``true``, an unknown Impact and one Impact twice - next to a clean Risk and category, runs
the migration twice and reads them back: the dirty ones keep only the stored ids (the first of each repeat), the clean
ones are untouched, and the second run changes nothing
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261110 import Update20261110
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsThreat,
    IsmsVulnerability,
)
# -------------------------------------------------------------------------------------------------------------------- #

THREAT: int = 943801
VULNERABILITY: int = 943802
GOAL: int = 943803
IMPACT: int = 943804
MISSING: int = 943809
DIRTY_RISK: int = 943811
CLEAN_RISK: int = 943812
DIRTY_CATEGORY: int = 943821
CLEAN_CATEGORY: int = 943822
DESCRIPTION: dict[str, Any] = {'impact_id': IMPACT, 'value': 'first'}

SEEDED: dict[str, list[int]] = {
    IsmsThreat.COLLECTION: [THREAT],
    IsmsVulnerability.COLLECTION: [VULNERABILITY],
    IsmsProtectionGoal.COLLECTION: [GOAL],
    IsmsImpact.COLLECTION: [IMPACT],
    IsmsRisk.COLLECTION: [DIRTY_RISK, CLEAN_RISK],
    IsmsImpactCategory.COLLECTION: [DIRTY_CATEGORY, CLEAN_CATEGORY],
}


@pytest.fixture(name='read')
def fixture_read(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The seeded documents, removed afterwards; answers a reader of one stored document"""
    def _collection(name: str) -> Any:
        return database_manager.get_collection(name, database_name)

    def _purge() -> None:
        for name, public_ids in SEEDED.items():
            _collection(name).delete_many({'public_id': {'$in': public_ids}})

    _purge()
    _collection(IsmsThreat.COLLECTION).insert_one({'public_id': THREAT, 'name': 'Integration threat 943801'})
    _collection(IsmsVulnerability.COLLECTION).insert_one({'public_id': VULNERABILITY, 'name': 'Integration vuln'})
    _collection(IsmsProtectionGoal.COLLECTION).insert_one({'public_id': GOAL, 'name': 'Integration goal 943803'})
    _collection(IsmsImpact.COLLECTION).insert_one({'public_id': IMPACT, 'name': 'Integration impact'})
    _collection(IsmsRisk.COLLECTION).insert_many([
        {'public_id': DIRTY_RISK, 'name': 'dirty', 'threats': ['x', True, MISSING, THREAT, THREAT],
         'vulnerabilities': [VULNERABILITY], 'protection_goals': [{'a': 1}, GOAL]},
        {'public_id': CLEAN_RISK, 'name': 'clean', 'threats': [THREAT], 'vulnerabilities': [],
         'protection_goals': [GOAL]},
    ])
    _collection(IsmsImpactCategory.COLLECTION).insert_many([
        {'public_id': DIRTY_CATEGORY, 'name': 'dirty', 'impact_descriptions': [
            {'impact_id': True, 'value': 'x'}, DESCRIPTION, {'impact_id': MISSING, 'value': 'y'},
            {'impact_id': IMPACT, 'value': 'second'}]},
        {'public_id': CLEAN_CATEGORY, 'name': 'clean', 'impact_descriptions': [DESCRIPTION]},
    ])

    yield lambda name, public_id: _collection(name).find_one({'public_id': public_id}, {'_id': 0})

    _purge()


def _snapshot(read: Any) -> list[dict[str, Any]]:
    """Every seeded Risk and category as stored"""
    return [read(name, public_id) for name in (IsmsRisk.COLLECTION, IsmsImpactCategory.COLLECTION)
            for public_id in SEEDED[name]]


def test_the_migration_cleans_the_dirty_lists_and_is_rerun_safe(database_manager: MongoDatabaseManager,
                                                                  database_name: str, read: Any) -> None:
    """Dirty ones cleaned, clean ones untouched, the second run a no-op"""
    clean_before: list[dict[str, Any]] = [read(IsmsRisk.COLLECTION, CLEAN_RISK),
                                          read(IsmsImpactCategory.COLLECTION, CLEAN_CATEGORY)]

    Update20261110(database_manager, database_name).start_update()

    risk: dict[str, Any] = read(IsmsRisk.COLLECTION, DIRTY_RISK)
    assert (risk['threats'], risk['vulnerabilities'], risk['protection_goals']) == ([THREAT], [VULNERABILITY], [GOAL])
    assert read(IsmsImpactCategory.COLLECTION, DIRTY_CATEGORY)['impact_descriptions'] == [DESCRIPTION]
    assert [read(IsmsRisk.COLLECTION, CLEAN_RISK), read(IsmsImpactCategory.COLLECTION, CLEAN_CATEGORY)] == clean_before

    after_first_run: list[dict[str, Any]] = _snapshot(read)

    Update20261110(database_manager, database_name).start_update()

    assert _snapshot(read) == after_first_run
