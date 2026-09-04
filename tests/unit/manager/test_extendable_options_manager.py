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
Unit tests for cmdb.manager.extendable_options_manager

DB-free: the manager is built against a mocked MongoDatabaseManager, which its __init__ only stores.
Everything but ``get_option_values`` is inherited from GenericManager and covered once in
test_generic_manager.py, so what is tested here is the binding plus that one read - the snapshot the
CABLE blueprint is seeded from
"""
from typing import Any

from unittest.mock import MagicMock

import pytest

from cmdb.manager import ExtendableOptionsManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.manager.manager_provider_model.manager_provider import ManagerProvider
from cmdb.models.extendable_option_model import (
    CmdbExtendableOption,
    ExtendableOptionKey,
    OptionType,
)
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.extendable_options_manager import (
    EXTENDABLE_OPTIONS_MANAGER_ERRORS,
    ExtendableOptionsManagerGetError,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_NAME: str = 'testdb'


@pytest.fixture(name='manager')
def fixture_manager() -> ExtendableOptionsManager:
    """An ExtendableOptionsManager over a mocked database manager (its __init__ performs no I/O)"""
    return ExtendableOptionsManager(MagicMock(name='dbm'), DB_NAME)


def _option(public_id: int, value: Any) -> dict[str, Any]:
    """A stored CmdbExtendableOption document"""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
    }


class TestTheBinding:
    """What the manager is bound to."""

    def test_is_a_generic_manager(self, manager: ExtendableOptionsManager) -> None:
        """The CRUD is plain, so the shared implementation covers it"""
        assert isinstance(manager, GenericManager)

    def test_stores_extendable_options(self, manager: ExtendableOptionsManager) -> None:
        """The model decides both the collection and how documents are (de)serialised"""
        assert manager.model is CmdbExtendableOption
        assert manager.collection == CmdbExtendableOption.COLLECTION

    def test_uses_its_own_exception_map(self, manager: ExtendableOptionsManager) -> None:
        """A failure has to surface as this manager's error, not another domain's"""
        assert manager.exceptions is EXTENDABLE_OPTIONS_MANAGER_ERRORS

    def test_the_provider_resolves_the_manager_type(self) -> None:
        """A ManagerType missing from the provider map raises BaseManagerInitError at request time"""
        # pylint: disable=protected-access
        assert ManagerProvider._ManagerProvider__get_manager_class(
            ManagerType.EXTENDABLE_OPTIONS) is ExtendableOptionsManager


class TestGetOptionValues:
    """The snapshot a consumer that cannot reference the option list is seeded from."""

    def test_reads_only_the_requested_list(self, manager: ExtendableOptionsManager) -> None:
        """A PORT_SPEED value appearing in a cable-type select would be nonsense"""
        manager.find = MagicMock(return_value=[])

        manager.get_option_values(OptionType.CABLE_TYPE.value)

        assert manager.find.call_args.kwargs['criteria'] == {
            ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        }

    def test_orders_by_public_id(self, manager: ExtendableOptionsManager) -> None:
        """
        The predefined values keep the order they were seeded in, customer additions follow

        Sorting by value instead would scramble a deliberately ordered list - the port speeds ship
        ascending, and '100M' sorts before '10G' alphabetically.
        """
        manager.find = MagicMock(return_value=[])

        manager.get_option_values(OptionType.CABLE_TYPE.value)

        assert manager.find.call_args.kwargs['sort'] == [
            (ExtendableOptionKey.PUBLIC_ID.value, CmdbExtendableOption.DAO_ASCENDING),
        ]

    def test_returns_the_plain_values(self, manager: ExtendableOptionsManager) -> None:
        """The caller wants the values, not the documents that carry them"""
        manager.find = MagicMock(return_value=[_option(1, 'Cat6a'), _option(2, 'OM4')])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == ['Cat6a', 'OM4']

    def test_an_empty_list_is_an_empty_result(self, manager: ExtendableOptionsManager) -> None:
        """A customer may have deleted every option of a list; that is not an error"""
        manager.find = MagicMock(return_value=[])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == []

    def test_a_drifted_document_is_skipped_rather_than_serialised(
            self, manager: ExtendableOptionsManager) -> None:
        """
        A non-string value would end up as an option name the frontend can not render

        Skipping it keeps the rest of the list usable instead of failing the whole type creation.
        """
        manager.find = MagicMock(return_value=[_option(1, 'Cat6a'), _option(2, None), _option(3, 7)])

        assert manager.get_option_values(OptionType.CABLE_TYPE.value) == ['Cat6a']

    def test_wraps_a_read_failure(self, manager: ExtendableOptionsManager) -> None:
        """A BaseManager failure surfaces as the manager's own error type"""
        manager.find = MagicMock(side_effect=BaseManagerGetError('boom'))

        with pytest.raises(ExtendableOptionsManagerGetError):
            manager.get_option_values(OptionType.CABLE_TYPE.value)
