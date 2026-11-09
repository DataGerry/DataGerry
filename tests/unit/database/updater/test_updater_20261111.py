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
Unit tests for cmdb.database.updater.versions.updater_20261111

The migration nulls every ISMS source and Risk category that is no option of its own list. Its run against a real
database is its own integration test; this module owns the frozen field table, the id rule, the reset rule, the
per-field write, each list read once, the version bump and the failure tail
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261111 as module
from cmdb.database.updater.versions.updater_20261111 import Update20261111, is_public_id, needs_reset
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import IsmsControlMeasure, IsmsRisk, IsmsThreat, IsmsVulnerability
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.isms_model.isms_threat_constants import ThreatKey
from cmdb.models.isms_model.isms_vulnerability_constants import VulnerabilityKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261111
DATABASE_NAME: str = 'cmdb-unit'
DB_FAILURE: str = 'threats gone'
SOURCE: int = 11
CATEGORY: int = 21
OTHER_LIST: int = 31


def test_the_frozen_field_table_matches_the_code() -> None:
    """The collections, keys and lists still mean what the code means today"""
    assert [(field.collection, field.field, field.option_type) for field in module.OPTION_FIELDS] == [
        (IsmsThreat.COLLECTION, ThreatKey.SOURCE.value, OptionType.THREAT_VULNERABILITY.value),
        (IsmsVulnerability.COLLECTION, VulnerabilityKey.SOURCE.value, OptionType.THREAT_VULNERABILITY.value),
        (IsmsControlMeasure.COLLECTION, ControlMeasureKey.SOURCE.value, OptionType.CONTROL_MEASURE.value),
        (IsmsRisk.COLLECTION, RiskKey.CATEGORY_ID.value, OptionType.RISK.value),
    ]
    assert module.OPTIONS_COLLECTION == CmdbExtendableOption.COLLECTION


@pytest.mark.parametrize('value, expected', [(SOURCE, True), (0, False), (True, False), ('11', False)])
def test_the_id_rule(value: Any, expected: bool) -> None:
    """An int from 1; a bool is none"""
    assert is_public_id(value) is expected


@pytest.mark.parametrize('value, expected', [
    (None, False), (SOURCE, False), (OTHER_LIST, True), (0, True), (True, True), ('x', True),
], ids=['null', 'an-option', 'other-list', 'zero', 'true', 'string'])
def test_the_reset_rule(value: Any, expected: bool) -> None:
    """Null and an option of the list stay; anything else is nulled"""
    assert needs_reset(value, {SOURCE}) is expected


def _updater(collections: dict[str, list[dict[str, Any]]],
             options: dict[str, list[int]]) -> tuple[Update20261111, MagicMock]:
    """The migration over a mocked database manager: option reads answer per list, other reads per collection"""
    dbm = MagicMock()

    def _find(**kwargs: Any) -> Any:
        if kwargs['collection'] == CmdbExtendableOption.COLLECTION:
            return iter([{'public_id': public_id} for public_id in options.get(kwargs['filter']['option_type'], [])])
        return iter(collections.get(kwargs['collection'], []))

    dbm.find.side_effect = _find
    updater = Update20261111(dbm, DATABASE_NAME)
    updater.increase_updater_version = MagicMock()

    return updater, dbm


OPTIONS: dict[str, list[int]] = {
    OptionType.THREAT_VULNERABILITY.value: [SOURCE], OptionType.CONTROL_MEASURE.value: [SOURCE],
    OptionType.RISK.value: [CATEGORY],
}


def test_the_version_and_description() -> None:
    """The date it is registered under"""
    updater, _dbm = _updater({}, {})

    assert updater.creation_date() == CREATION_DATE
    assert updater.description()


def test_out_of_list_values_are_nulled_field_by_field_and_each_list_read_once() -> None:
    """A Vulnerability shares the Threat list's read"""
    updater, dbm = _updater({
        IsmsThreat.COLLECTION: [{'_id': 't1', 'public_id': 1, 'source': OTHER_LIST},
                                {'_id': 't2', 'public_id': 2, 'source': SOURCE}],
        IsmsVulnerability.COLLECTION: [{'_id': 'v1', 'public_id': 3, 'source': True}],
        IsmsRisk.COLLECTION: [{'_id': 'r1', 'public_id': 4, 'category_id': SOURCE}],
    }, OPTIONS)

    updater.start_update()

    writes: dict[str, Any] = {call.args[0]: call.args[2] for call in dbm.bulk_write.call_args_list}
    # pylint: disable-next=protected-access
    assert {collection: [(op._filter, op._doc) for op in ops] for collection, ops in writes.items()} == {
        IsmsThreat.COLLECTION: [({'_id': 't1'}, {'$set': {'source': None}})],
        IsmsVulnerability.COLLECTION: [({'_id': 'v1'}, {'$set': {'source': None}})],
        IsmsRisk.COLLECTION: [({'_id': 'r1'}, {'$set': {'category_id': None}})],
    }
    option_reads: list[Any] = [call.kwargs['filter']['option_type'] for call in dbm.find.call_args_list
                               if call.kwargs['collection'] == CmdbExtendableOption.COLLECTION]
    assert option_reads == [OptionType.THREAT_VULNERABILITY.value, OptionType.CONTROL_MEASURE.value,
                            OptionType.RISK.value]
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_clean_database_writes_nothing_and_still_bumps() -> None:
    """The second run"""
    updater, dbm = _updater({IsmsThreat.COLLECTION: [{'_id': 't', 'source': SOURCE}]}, OPTIONS)

    updater.start_update()

    dbm.bulk_write.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_a_failing_write_is_the_updater_exception_carrying_the_error() -> None:
    """The exception itself, not its text; the version is not bumped"""
    updater, dbm = _updater({IsmsThreat.COLLECTION: [{'_id': 't', 'source': OTHER_LIST}]}, OPTIONS)
    failure = RuntimeError(DB_FAILURE)
    dbm.bulk_write.side_effect = failure

    with pytest.raises(UpdaterException) as raised:
        updater.start_update()

    assert raised.value.args[0] is failure
    updater.increase_updater_version.assert_not_called()
