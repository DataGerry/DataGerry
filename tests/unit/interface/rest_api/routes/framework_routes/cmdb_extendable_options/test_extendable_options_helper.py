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
Unit tests for the CmdbExtendableOption route helper ``is_extendable_option_used``

Pure tests: ManagerProvider.get_manager is patched to hand out per-ManagerType mocks whose
count_documents returns a configured value, so only the option_type -> referencing-collection
routing (and the OR-ing within a type) is exercised - no Mongo. The THREAT_VULNERABILITY
vulnerability-only case is the regression guard for the duplicate-``if`` bug that left the
vulnerability check unreachable.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.extendable_option_model import OptionType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_constants import (
    ExtendableOptionKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_helper import (
    is_extendable_option_used,
    option_value_exists,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_extendable_options.extendable_options_helper'

PUBLIC_ID: int = 7


def _option(option_type: str) -> dict[str, Any]:
    """Builds a CmdbExtendableOption doc of the given option_type."""
    return {'public_id': PUBLIC_ID, 'option_type': option_type, 'value': 'v', 'predefined': False}


def _provider(counts_by_type: dict[ManagerType, int]):
    """A ManagerProvider.get_manager replacement handing out per-type mocks with a fixed count."""
    managers: dict[ManagerType, MagicMock] = {}

    def _get_manager(manager_type: ManagerType, _request_user: Any) -> MagicMock:
        if manager_type not in managers:
            manager = MagicMock(name=str(manager_type))
            manager.count_documents.return_value = counts_by_type.get(manager_type, 0)
            managers[manager_type] = manager

        return managers[manager_type]

    return _get_manager


def _run(option_type: str, counts_by_type: dict[ManagerType, int]) -> bool:
    """Runs is_extendable_option_used with the provider patched to the given per-type counts."""
    with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=_provider(counts_by_type)):
        return is_extendable_option_used(_option(option_type), MagicMock())


# -------------------------------------------------------------------------------------------------------------------- #
#                                            THREAT_VULNERABILITY                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_threat_vulnerability_used_by_threat() -> None:
    """A THREAT_VULNERABILITY option referenced by a threat is in use."""
    assert _run(OptionType.THREAT_VULNERABILITY, {ManagerType.THREAT: 1, ManagerType.VULNERABILITY: 0}) is True


def test_threat_vulnerability_used_by_vulnerability_only() -> None:
    """A THREAT_VULNERABILITY option referenced ONLY by a vulnerability is in use (regression for the
    duplicate-if bug that made the vulnerability check unreachable)."""
    assert _run(OptionType.THREAT_VULNERABILITY, {ManagerType.THREAT: 0, ManagerType.VULNERABILITY: 1}) is True


def test_threat_vulnerability_unused() -> None:
    """A THREAT_VULNERABILITY option referenced by neither is not in use."""
    assert _run(OptionType.THREAT_VULNERABILITY, {ManagerType.THREAT: 0, ManagerType.VULNERABILITY: 0}) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                            other option types                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_object_group_used() -> None:
    """An OBJECT_GROUP option referenced by an object group is in use."""
    assert _run(OptionType.OBJECT_GROUP, {ManagerType.OBJECT_GROUP: 1}) is True


def test_control_measure_used() -> None:
    """A CONTROL_MEASURE option referenced by a control measure is in use."""
    assert _run(OptionType.CONTROL_MEASURE, {ManagerType.CONTROL_MEASURE: 1}) is True


def test_risk_used() -> None:
    """A RISK option referenced by a risk is in use."""
    assert _run(OptionType.RISK, {ManagerType.RISK: 1}) is True


@pytest.mark.parametrize('used_type', [
    ManagerType.CONTROL_MEASURE,
    ManagerType.RISK_ASSESSMENT,
    ManagerType.CONTROL_MEASURE_ASSIGNMENT,
])
def test_implementation_state_used_by_any_referencing_collection(used_type: ManagerType) -> None:
    """An IMPLEMENTATION_STATE option is in use when ANY of its three referencing collections matches."""
    assert _run(OptionType.IMPLEMENTATION_STATE, {used_type: 1}) is True


def test_implementation_state_unused() -> None:
    """An IMPLEMENTATION_STATE option referenced by none of the three collections is not in use."""
    assert _run(OptionType.IMPLEMENTATION_STATE, {}) is False


def test_unrecognised_option_type_is_not_used() -> None:
    """An unrecognised option_type resolves to not-in-use."""
    assert _run('SOMETHING_ELSE', {}) is False


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
