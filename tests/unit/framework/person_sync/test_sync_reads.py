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
Unit tests for cmdb.framework.person_sync.sync_reads - which objects are synced persons
"""
from unittest.mock import MagicMock

from cmdb.framework.person_sync.sync_reads import synced_person_ids
# -------------------------------------------------------------------------------------------------------------------- #


def test_one_query_on_the_int_ids() -> None:
    """Anything but an int is no object id; the answer is the found ids"""
    objects = MagicMock()
    objects.find.return_value = [{'public_id': 3}]

    assert synced_person_ids(objects, {3, 1, 'x', None}) == {3}

    objects.find.assert_called_once_with(
        criteria={'public_id': {'$in': [1, 3]}, 'system_ref.kind': 'user'}, projection={'public_id': 1})


def test_no_id_no_query() -> None:
    """Nothing to judge"""
    objects = MagicMock()

    assert synced_person_ids(objects, {'x'}) == set()

    objects.find.assert_not_called()
