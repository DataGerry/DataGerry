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
Unit tests for cmdb.database.updater.versions.updater_20261009

The migration makes the first active admin-group user the owner of every stored webhook without one. Its run against
real collections is its own integration test; this module owns the frozen literals, the shape of the read and the
write, the run without an admin, and the failure tail
"""
# pylint: disable=no-member  # the database manager is a MagicMock, so find / update_many_raw carry call_args
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.updater.versions import updater_20261009 as module
from cmdb.database.updater.versions.updater_20261009 import Update20261009
from cmdb.errors.updater import UpdaterException
from cmdb.interface.rest_api.routes.webhook_routes.webhook_constants import WebhookKey
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.models.user_model.cmdb_user_key_enum import CmdbUserKey
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
# -------------------------------------------------------------------------------------------------------------------- #

CREATION_DATE: int = 20261009
DATABASE_NAME: str = 'cmdb-unit'
ADMIN_USER_ID: int = 7


def _build_stubbed_updater(admins: list[dict[str, Any]]) -> Any:
    """The updater with a stubbed database manager, bypassing the base class's wiring"""
    updater = Update20261009.__new__(Update20261009)
    updater.dbm = MagicMock()
    updater.dbm.find.return_value = iter(admins)
    updater.db_name = DATABASE_NAME
    updater.increase_updater_version = MagicMock()

    return updater


@pytest.mark.parametrize('frozen, live', [
    (module.WEBHOOK_COLLECTION, CmdbWebhook.COLLECTION),
    (module.USER_COLLECTION, CmdbUser.COLLECTION),
    (module.OWNER_FIELD, WebhookKey.OWNER_ID.value),
    (module.GROUP_FIELD, CmdbUserKey.GROUP_ID.value),
    (module.ACTIVE_FIELD, CmdbUserKey.ACTIVE.value),
    (module.ADMIN_GROUP_ID, ADMIN_GROUP_ID),
], ids=['webhooks', 'users', 'owner', 'group', 'active', 'admin-group'])
def test_a_frozen_literal_names_what_the_code_names_today(frozen: Any, live: Any) -> None:
    """Frozen on purpose - and right when it shipped"""
    assert frozen == live


def test_reads_the_lowest_numbered_active_admin() -> None:
    """One user, sorted by public_id, active members of group 1 only"""
    updater = _build_stubbed_updater([{'public_id': ADMIN_USER_ID}])

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.find.call_args.kwargs
    assert kwargs['collection'] == CmdbUser.COLLECTION
    assert kwargs['filter'] == {'group_id': ADMIN_GROUP_ID, 'active': True}
    assert kwargs['sort'] == [('public_id', 1)]
    assert kwargs['limit'] == 1


def test_stamps_the_admin_on_every_ownerless_webhook_and_bumps_the_version() -> None:
    """Only a webhook without the key is touched, so a second run changes nothing"""
    updater = _build_stubbed_updater([{'public_id': ADMIN_USER_ID}])

    updater.start_update()

    kwargs: dict[str, Any] = updater.dbm.update_many_raw.call_args.kwargs
    assert kwargs['collection'] == CmdbWebhook.COLLECTION
    assert kwargs['filter_query'] == {'owner_id': {'$exists': False}}
    assert kwargs['update'] == {'$set': {'owner_id': ADMIN_USER_ID}}
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)


def test_without_an_admin_writes_nothing_and_still_bumps_the_version(caplog: pytest.LogCaptureFixture) -> None:
    """The webhooks stay ownerless and deliver nothing; the run says so"""
    updater = _build_stubbed_updater([])

    updater.start_update()

    updater.dbm.update_many_raw.assert_not_called()
    updater.increase_updater_version.assert_called_once_with(CREATION_DATE)
    assert DATABASE_NAME in caplog.text


@pytest.mark.parametrize('failing', ['find', 'update_many_raw'])
def test_a_failed_step_is_wrapped_with_the_error_itself_and_leaves_the_version(failing: str) -> None:
    """The next start runs the whole migration again"""
    updater = _build_stubbed_updater([{'public_id': ADMIN_USER_ID}])
    error = RuntimeError('down')
    getattr(updater.dbm, failing).side_effect = error

    with pytest.raises(UpdaterException) as exc_info:
        updater.start_update()

    assert exc_info.value.__cause__ is error
    assert exc_info.value.args[0] is error
    updater.increase_updater_version.assert_not_called()


def test_the_description_names_the_owner() -> None:
    """The line the updater log prints"""
    assert 'owner' in Update20261009.__new__(Update20261009).description()
