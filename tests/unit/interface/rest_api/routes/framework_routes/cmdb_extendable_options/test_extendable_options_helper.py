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
Unit tests for the CmdbExtendableOption route helper

Pure tests: ManagerProvider.get_manager is patched to hand out one manager mock whose dbm counts a
configured number of documents per collection, so only the option_type -> referencing-collection
routing (and the OR-ing within a type) is exercised - no Mongo. The routing itself lives in
cmdb.framework.extendable_options and has its own suite; what is tested here is that the helper
hands it the option's own option_type and public_id and the manager's database. The
THREAT_VULNERABILITY vulnerability-only case is the regression guard for the duplicate-``if`` bug
that once left the vulnerability check unreachable.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.models.extendable_option_model import OptionType, ExtendableOptionKey
from cmdb.models.isms_model.isms_threat import IsmsThreat
from cmdb.models.isms_model.isms_vulnerability import IsmsVulnerability
from cmdb.models.isms_model.isms_risk import IsmsRisk
from cmdb.models.isms_model.isms_control_measure import IsmsControlMeasure
from cmdb.models.isms_model.isms_risk_assessment import IsmsRiskAssessment
from cmdb.models.isms_model.isms_control_measure_assignment import IsmsControlMeasureAssignment
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.port_model import CmdbPort
from cmdb.models.port_connection_model import CmdbPortConnection
from cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_helper import (
    is_extendable_option_used,
    option_value_exists,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_helper'

PUBLIC_ID: int = 7
DB_NAME: str = 'testdb'


def _option(option_type: str) -> dict[str, Any]:
    """Builds a CmdbExtendableOption doc of the given option_type."""
    return {'public_id': PUBLIC_ID, 'option_type': option_type, 'value': 'v', 'predefined': False}


def _run(option_type: str, counts_by_collection: dict[str, int]) -> tuple[bool, MagicMock]:
    """Runs is_extendable_option_used with the manager's dbm counting per collection."""
    manager = MagicMock(name='extendable_options_manager')
    manager.db_name = DB_NAME
    manager.dbm.count.side_effect = lambda collection, _db, _criteria, limit=None: (
        counts_by_collection.get(collection, 0)
    )

    with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', return_value=manager):
        return is_extendable_option_used(_option(option_type), MagicMock()), manager


# -------------------------------------------------------------------------------------------------------------------- #
#                                            THREAT_VULNERABILITY                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_threat_vulnerability_used_by_threat() -> None:
    """A THREAT_VULNERABILITY option referenced by a threat is in use."""
    used, _ = _run(OptionType.THREAT_VULNERABILITY, {IsmsThreat.COLLECTION: 1})

    assert used is True


def test_threat_vulnerability_used_by_vulnerability_only() -> None:
    """A THREAT_VULNERABILITY option referenced ONLY by a vulnerability is in use (regression for the
    duplicate-if bug that made the vulnerability check unreachable)."""
    used, _ = _run(OptionType.THREAT_VULNERABILITY, {IsmsVulnerability.COLLECTION: 1})

    assert used is True


def test_threat_vulnerability_unused() -> None:
    """A THREAT_VULNERABILITY option referenced by neither is not in use."""
    used, _ = _run(OptionType.THREAT_VULNERABILITY, {})

    assert used is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                            other option types                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_object_group_used() -> None:
    """An OBJECT_GROUP option referenced by an object group is in use."""
    used, _ = _run(OptionType.OBJECT_GROUP, {CmdbObjectGroup.COLLECTION: 1})

    assert used is True


def test_control_measure_used() -> None:
    """A CONTROL_MEASURE option referenced by a control measure is in use."""
    used, _ = _run(OptionType.CONTROL_MEASURE, {IsmsControlMeasure.COLLECTION: 1})

    assert used is True


def test_risk_used() -> None:
    """A RISK option referenced by a risk is in use."""
    used, _ = _run(OptionType.RISK, {IsmsRisk.COLLECTION: 1})

    assert used is True


@pytest.mark.parametrize('used_collection', [
    IsmsControlMeasure.COLLECTION,
    IsmsRiskAssessment.COLLECTION,
    IsmsControlMeasureAssignment.COLLECTION,
])
def test_implementation_state_used_by_any_referencing_collection(used_collection: str) -> None:
    """An IMPLEMENTATION_STATE option is in use when ANY of its three referencing collections matches."""
    used, _ = _run(OptionType.IMPLEMENTATION_STATE, {used_collection: 1})

    assert used is True


def test_implementation_state_unused() -> None:
    """An IMPLEMENTATION_STATE option referenced by none of the three collections is not in use."""
    used, _ = _run(OptionType.IMPLEMENTATION_STATE, {})

    assert used is False


def test_unrecognised_option_type_is_not_used() -> None:
    """An unrecognised option_type resolves to not-in-use without querying anything."""
    used, manager = _run('SOMETHING_ELSE', {})

    assert used is False
    manager.dbm.count.assert_not_called()


def test_a_port_option_is_checked_against_the_ports_collection() -> None:
    """A PORT_STATUS option in use by a port must not be deletable (registered in step 3)."""
    used, _ = _run(OptionType.PORT_STATUS, {CmdbPort.COLLECTION: 1})

    assert used is True


def test_a_cable_type_in_use_by_a_connection_is_not_deletable() -> None:
    """A cable type a connection still holds must not be removable out from under it."""
    used, _ = _run(OptionType.CABLE_TYPE, {CmdbPortConnection.COLLECTION: 1})

    assert used is True


def test_an_unused_cable_type_is_deletable() -> None:
    """The other half: a cable type nothing holds may be removed."""
    used, _ = _run(OptionType.CABLE_TYPE, {})

    assert used is False


def test_the_option_id_and_the_managers_database_are_used() -> None:
    """The count runs against the manager's database, filtered on the option's own public_id."""
    _, manager = _run(OptionType.RISK, {})

    collection, db_name, criteria = manager.dbm.count.call_args.args

    assert collection == IsmsRisk.COLLECTION
    assert db_name == DB_NAME
    assert criteria == {'category_id': PUBLIC_ID}


def test_existence_check_is_counted_with_a_limit() -> None:
    """The in-use check only needs one match, so the count is capped and the server can stop early."""
    _, manager = _run(OptionType.RISK, {})

    assert manager.dbm.count.call_args.kwargs['limit'] == 1


class TestOptionValueExists:
    """option_value_exists reflects get_one_by and adds the self-exclusion filter when given exclude_id."""

    def test_true_when_match_found(self) -> None:
        """A matching option makes the check return True."""
        manager = MagicMock()
        manager.get_one_by.return_value = {'public_id': 5}

        assert option_value_exists(manager, 'value', OptionType.RISK.value) is True

    def test_false_when_no_match(self) -> None:
        """No matching option makes the check return False."""
        manager = MagicMock()
        manager.get_one_by.return_value = None

        assert option_value_exists(manager, 'value', OptionType.RISK.value) is False

    def test_without_exclude_id_has_no_public_id_filter(self) -> None:
        """Without exclude_id the criteria only filters on value + option_type."""
        manager = MagicMock()
        manager.get_one_by.return_value = None

        option_value_exists(manager, 'value', OptionType.RISK.value)

        criteria = manager.get_one_by.call_args.args[0]
        assert ExtendableOptionKey.PUBLIC_ID not in criteria

    def test_with_exclude_id_adds_ne_filter(self) -> None:
        """With exclude_id the criteria excludes that public_id via $ne (self-exclusion)."""
        manager = MagicMock()
        manager.get_one_by.return_value = None

        option_value_exists(manager, 'value', OptionType.RISK.value, exclude_id=7)

        criteria = manager.get_one_by.call_args.args[0]
        assert criteria[ExtendableOptionKey.PUBLIC_ID] == {'$ne': 7}
