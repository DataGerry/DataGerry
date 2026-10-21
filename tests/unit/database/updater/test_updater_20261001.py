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
Unit tests for cmdb.database.updater.versions.updater_20261001

The migration rewrites every CmdbType's non-boolean ``acl.activated`` to the boolean the single read decides on.
Pinned: the selection (neither a boolean nor null - what makes a re-run a no-op), the reading (Python
truthiness, the single read's), one write per reading restricted to the selected ids, nothing written when
nothing is selected, and the failure tail. The double run against a real collection is the integration tier's
"""
from typing import Any

import pytest

from cmdb.errors.updater import UpdaterException
from cmdb.database.updater.versions.updater_20261001 import (
    ACL_ACTIVATED_PATH,
    NON_BOOLEAN_ACTIVATED_CRITERIA,
    Update20261001,
    ids_by_reading,
)
from cmdb.database.database_services.database_updater import DatabaseUpdater
from cmdb.models.type_model import TypeSchemaKey
from tests.unit.database.updater.test_updater_version_bump_contract import build_stubbed_updater
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261001
PUBLIC_ID_KEY: str = TypeSchemaKey.PUBLIC_ID.value


def _stored(public_id: int, activated: Any) -> dict[str, Any]:
    """A selected type, projected the way the updater reads it"""
    return {PUBLIC_ID_KEY: public_id, TypeSchemaKey.ACL.value: {'activated': activated}}


def _updater(documents: list[dict[str, Any]]) -> Any:
    """The updater with stubbed managers whose type read answers the given documents"""
    updater = build_stubbed_updater(Update20261001)
    updater.types_manager.find.return_value = documents

    return updater


class TestIdsByReading:
    """The boolean each stored value reads as is the single read's: Python truthiness"""

    @pytest.mark.parametrize('stored, reading', [
        ('yes', True), ('false', True), (1, True), ([0], True), (0, False), ('', False), ([], False), ({}, False),
    ])
    def test_each_value_is_grouped_by_its_truthiness(self, stored: Any, reading: bool) -> None:
        """`"false"` is a non-empty string, so the single read already treats it as on - and keeps doing so"""
        grouped = ids_by_reading([_stored(7, stored)])

        assert grouped[reading] == [7]
        assert grouped[not reading] == []

    def test_the_ids_are_sorted_per_reading(self) -> None:
        """A stable order, so the writes do not depend on the read order"""
        grouped = ids_by_reading([_stored(9, 'yes'), _stored(3, 0), _stored(4, 'on'), _stored(1, '')])

        assert grouped == {True: [4, 9], False: [1, 3]}


class TestStartUpdate:
    """One read, then one write per reading, then the version"""

    def test_only_non_boolean_non_null_flags_are_selected(self) -> None:
        """A boolean is settled, and null reads as off in both readers - neither is rewritten"""
        updater = _updater([])

        updater.start_update()

        assert updater.types_manager.find.call_args.kwargs['criteria'] == NON_BOOLEAN_ACTIVATED_CRITERIA
        assert NON_BOOLEAN_ACTIVATED_CRITERIA == {
            ACL_ACTIVATED_PATH: {'$exists': True, '$not': {'$type': ['bool', 'null']}},
        }

    def test_each_reading_is_written_to_its_own_ids(self) -> None:
        """Restricted to the selected ids AND still to a non-boolean flag, so a concurrent fix is not overwritten"""
        updater = _updater([_stored(5, 'yes'), _stored(6, 0)])

        updater.start_update()

        calls = [call.kwargs for call in updater.types_manager.update_many.call_args_list]
        assert calls == [
            {'criteria': {PUBLIC_ID_KEY: {'$in': [5]}, **NON_BOOLEAN_ACTIVATED_CRITERIA},
             'update': {ACL_ACTIVATED_PATH: True}},
            {'criteria': {PUBLIC_ID_KEY: {'$in': [6]}, **NON_BOOLEAN_ACTIVATED_CRITERIA},
             'update': {ACL_ACTIVATED_PATH: False}},
        ]

    def test_nothing_is_written_when_nothing_is_selected(self) -> None:
        """A database that never held a non-boolean flag - or a second run - writes nothing"""
        updater = _updater([])

        updater.start_update()

        updater.types_manager.update_many.assert_not_called()
        updater.increase_updater_version.assert_called_once_with(CREATION_DATE)

    def test_the_objects_are_not_touched(self) -> None:
        """The flag lives on the type"""
        updater = _updater([_stored(5, 'yes')])

        updater.start_update()

        updater.objects_manager.update_many.assert_not_called()

    def test_the_version_is_bumped_after_the_writes(self) -> None:
        """A failure leaves the version alone, so the next start runs the migration again"""
        updater = _updater([_stored(5, 'yes')])
        updater.types_manager.update_many.side_effect = RuntimeError('write failed')

        with pytest.raises(UpdaterException) as caught:
            updater.start_update()

        updater.increase_updater_version.assert_not_called()
        assert isinstance(caught.value.__cause__, RuntimeError)

    def test_a_failed_read_is_an_updater_exception(self) -> None:
        """The read is inside the same failure tail"""
        updater = _updater([])
        updater.types_manager.find.side_effect = RuntimeError('read failed')

        with pytest.raises(UpdaterException):
            updater.start_update()

        updater.increase_updater_version.assert_not_called()


def test_the_contract_metadata() -> None:
    """The date in the name, a description, and a registry entry"""
    updater = Update20261001.__new__(Update20261001)

    assert updater.creation_date() == CREATION_DATE
    assert updater.description().strip()
    assert CREATION_DATE in DatabaseUpdater.__UPDATE_VERSIONS__

