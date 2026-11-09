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
Unit tests for cmdb.database.updater.versions.updater_20261110

The migration drops a Risk's and an ImpactCategory's id list items that name nothing stored or repeat. Its run
against a real database is its own integration test; this module owns the frozen literals, the id rule, the kept
items, the per-document ``$set``, the version bump and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261110 as module
from cmdb.database.updater.versions.updater_20261110 import (
    StoredIds,
    Update20261110,
    category_changes,
    is_public_id,
    kept_ids,
    risk_changes,
)
from cmdb.models.isms_model import (
    IsmsImpact,
    IsmsImpactCategory,
    IsmsProtectionGoal,
    IsmsRisk,
    IsmsThreat,
    IsmsVulnerability,
)
from cmdb.models.isms_model.isms_impact_category_constants import ImpactCategoryKey, ImpactDescriptionKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261110
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'risks gone'
THREAT: int = 11
OTHER_THREAT: int = 12
VULNERABILITY: int = 21
GOAL: int = 31
IMPACT: int = 41
OTHER_IMPACT: int = 42
MISSING: int = 99
STORED: StoredIds = StoredIds(threats={THREAT, OTHER_THREAT}, vulnerabilities={VULNERABILITY},
                              protection_goals={GOAL}, impacts={IMPACT, OTHER_IMPACT})


@pytest.mark.parametrize('frozen, live', [
    (module.RISKS_COLLECTION, IsmsRisk.COLLECTION),
    (module.IMPACT_CATEGORIES_COLLECTION, IsmsImpactCategory.COLLECTION),
    (module.THREATS_COLLECTION, IsmsThreat.COLLECTION),
    (module.VULNERABILITIES_COLLECTION, IsmsVulnerability.COLLECTION),
    (module.PROTECTION_GOALS_COLLECTION, IsmsProtectionGoal.COLLECTION),
    (module.IMPACTS_COLLECTION, IsmsImpact.COLLECTION),
    (module.PUBLIC_ID_FIELD, RiskKey.PUBLIC_ID.value),
    (module.THREATS_FIELD, RiskKey.THREATS.value),
    (module.VULNERABILITIES_FIELD, RiskKey.VULNERABILITIES.value),
    (module.PROTECTION_GOALS_FIELD, RiskKey.PROTECTION_GOALS.value),
    (module.IMPACT_DESCRIPTIONS_FIELD, ImpactCategoryKey.IMPACT_DESCRIPTIONS.value),
    (module.IMPACT_ID_FIELD, ImpactDescriptionKey.IMPACT_ID.value),
])
def test_the_frozen_literals_still_match_the_code(frozen: str, live: str) -> None:
    """The migration's copies of the names still mean what the code means today"""
    assert frozen == live


@pytest.mark.parametrize('value, expected', [
    (THREAT, True), (0, False), (-1, False), (True, False), ('11', False), (1.5, False), (None, False),
])
def test_the_id_rule(value: Any, expected: bool) -> None:
    """An int from 1; a bool is none"""
    assert is_public_id(value) is expected


def test_kept_ids_keep_the_stored_ones_once_in_order() -> None:
    """Junk, unknown and repeated items go"""
    assert kept_ids([OTHER_THREAT, 'x', True, MISSING, THREAT, OTHER_THREAT, {'a': 1}], STORED.threats) == [
        OTHER_THREAT, THREAT,
    ]


class TestRiskChanges:
    """The $set of one stored Risk"""

    def test_only_the_lists_that_change_are_set(self) -> None:
        """A clean list is not rewritten"""
        risk: dict[str, Any] = {'threats': [THREAT, THREAT], 'vulnerabilities': [VULNERABILITY],
                                'protection_goals': [GOAL, MISSING]}

        assert risk_changes(risk, STORED) == {'threats': [THREAT], 'protection_goals': [GOAL]}

    def test_a_clean_risk_has_no_changes(self) -> None:
        """The second run"""
        assert not risk_changes({'threats': [THREAT], 'vulnerabilities': [], 'protection_goals': [GOAL]}, STORED)

    def test_a_list_that_is_no_list_is_left_alone(self) -> None:
        """Nothing to clean"""
        assert not risk_changes({'threats': None, 'vulnerabilities': 'x'}, STORED)


class TestCategoryChanges:
    """The $set of one stored ImpactCategory"""

    def test_invalid_unknown_and_repeated_descriptions_go(self) -> None:
        """The first description of an Impact is kept"""
        first: dict[str, Any] = {'impact_id': IMPACT, 'value': 'first'}
        other: dict[str, Any] = {'impact_id': OTHER_IMPACT, 'value': 'other'}
        category: dict[str, Any] = {'impact_descriptions': [
            first, {'impact_id': True, 'value': 'x'}, {'impact_id': MISSING, 'value': 'y'},
            {'impact_id': IMPACT, 'value': 'second'}, 'junk', other,
        ]}

        assert category_changes(category, STORED) == {'impact_descriptions': [first, other]}

    def test_a_clean_category_has_no_changes(self) -> None:
        """The second run"""
        assert not category_changes({'impact_descriptions': [{'impact_id': IMPACT, 'value': 'v'}]}, STORED)

    def test_descriptions_that_are_no_list_are_left_alone(self) -> None:
        """Nothing to clean"""
        assert not category_changes({'impact_descriptions': None}, STORED)


def _updater(collections: dict[str, list[dict[str, Any]]]) -> tuple[Update20261110, MagicMock]:
    """The migration over a mocked database manager answering each collection's documents"""
    dbm = MagicMock()
    dbm.find.side_effect = lambda **kwargs: iter(collections.get(kwargs['collection'], []))
    updater = Update20261110(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


def _stored() -> dict[str, list[dict[str, Any]]]:
    """What the referenced collections hold"""
    return {
        IsmsThreat.COLLECTION: [{'public_id': THREAT}],
        IsmsVulnerability.COLLECTION: [{'public_id': VULNERABILITY}],
        IsmsProtectionGoal.COLLECTION: [{'public_id': GOAL}],
        IsmsImpact.COLLECTION: [{'public_id': IMPACT}, {'public_id': True}],
    }


def test_the_version_and_description() -> None:
    """The date it is registered under"""
    updater, _dbm = _updater({})

    assert updater.creation_date() == CREATION_DATE
    assert updater.description()


def test_out_of_line_documents_are_rewritten_in_one_write_each_then_the_version() -> None:
    """The clean ones are left out"""
    updater, dbm = _updater({
        **_stored(),
        IsmsRisk.COLLECTION: [{'_id': 'a', 'public_id': 1, 'threats': [THREAT, MISSING]},
                              {'_id': 'b', 'public_id': 2, 'threats': [THREAT]}],
        IsmsImpactCategory.COLLECTION: [{'_id': 'c', 'public_id': 3,
                                         'impact_descriptions': [{'impact_id': MISSING, 'value': 'v'}]}],
    })

    updater.start_update()

    writes: dict[str, Any] = {call.args[0]: call.args[2] for call in dbm.bulk_write.call_args_list}
    # pylint: disable-next=protected-access
    assert [(op._filter, op._doc) for op in writes[IsmsRisk.COLLECTION]] == [
        ({'_id': 'a'}, {'$set': {'threats': [THREAT]}}),
    ]
    # pylint: disable-next=protected-access
    assert [(op._filter, op._doc) for op in writes[IsmsImpactCategory.COLLECTION]] == [
        ({'_id': 'c'}, {'$set': {'impact_descriptions': []}}),
    ]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_stored_boolean_id_counts_as_nothing() -> None:
    """A collection's own junk public_id is no id a reference may keep"""
    updater, _dbm = _updater(_stored())

    assert updater.read_ids(IsmsImpact.COLLECTION) == {IMPACT}


def test_a_clean_database_writes_nothing_and_still_bumps() -> None:
    """The second run"""
    updater, dbm = _updater(_stored())

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failing_write_is_the_updater_exception_carrying_the_error() -> None:
    """The exception itself, not its text; the version is not bumped"""
    updater, dbm = _updater({**_stored(), IsmsRisk.COLLECTION: [{'_id': 'a', 'threats': [MISSING]}]})
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
