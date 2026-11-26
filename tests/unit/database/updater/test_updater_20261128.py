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

# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for cmdb.database.updater.versions.updater_20261128

The migration computes every stored object's scope block. Pinned here: the frozen literals against the code's own,
the batching (every id handed to one refresh per batch, the last partial one too), the version stamp and the failure
tail. Its run against a real database - the blocks, a double run, a fresh database - is the integration test's
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database.updater.versions import updater_20261128 as module
from cmdb.database.updater.versions.updater_20261128 import Update20261128
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

VERSION: int = 20261128
STORED_OBJECTS: int = 2500


def test_the_frozen_literals_match_the_code() -> None:
    """The collection and the key it reads"""
    assert (module.OBJECTS, module.PUBLIC_ID) == (CmdbObject.COLLECTION, CmdbObjectKey.PUBLIC_ID.value)


def _update(documents: Any) -> tuple[Update20261128, MagicMock]:
    """An update on a stood-in database manager, its refresh stood in"""
    dbm = MagicMock()
    dbm.find.return_value = documents
    update = Update20261128(dbm, 'db')
    update.increase_updater_version = MagicMock()
    refresh = MagicMock(return_value=1)

    return update, refresh


def test_every_object_is_refreshed_in_batches() -> None:
    """Two full batches and the rest; the version stamped after them"""
    update, refresh = _update([{'public_id': public_id} for public_id in range(1, STORED_OBJECTS + 1)])

    with patch.object(module.ObjectScopeBlocks, 'refresh', refresh):
        update.start_update()

    batches = [call.args[0] for call in refresh.call_args_list]
    assert [len(batch) for batch in batches] == [module.BATCH_SIZE, module.BATCH_SIZE,
                                                 STORED_OBJECTS - 2 * module.BATCH_SIZE]
    assert sum(batches, []) == list(range(1, STORED_OBJECTS + 1))
    update.increase_updater_version.assert_called_once_with(VERSION)


def test_no_object_only_stamps() -> None:
    """One empty refresh, nothing written"""
    update, refresh = _update([])

    with patch.object(module.ObjectScopeBlocks, 'refresh', refresh):
        update.start_update()

    refresh.assert_called_once_with([])
    update.increase_updater_version.assert_called_once_with(VERSION)


def test_a_failure_is_the_updater_exception_carrying_it() -> None:
    """The exception itself, not its text; no stamp"""
    cause = RuntimeError('down')
    update, refresh = _update([{'public_id': 1}])
    refresh.side_effect = cause

    with patch.object(module.ObjectScopeBlocks, 'refresh', refresh), pytest.raises(UpdaterException) as raised:
        update.start_update()

    assert raised.value.args[0] is cause
    update.increase_updater_version.assert_not_called()
