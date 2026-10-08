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
Integration tests for cmdb.database.updater.versions.updater_20261009 against a real MongoDB

Seeds webhooks without an owner, with one, and with an explicit null, plus a second admin-group user, runs the
migration, and asserts:

  - every webhook without the key gets the lowest-numbered ACTIVE admin-group user; nothing else of it changes
  - a webhook that already has an owner (or a recorded null) is left alone
  - a deactivated admin is passed over; with no active admin at all nothing is written
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261009 import Update20261009
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.user_model import CmdbUser
from cmdb.models.webhook_model.cmdb_webhook_model import CmdbWebhook
# -------------------------------------------------------------------------------------------------------------------- #

SEEDED_ADMIN_ID: int = 1
SECOND_ADMIN_ID: int = 98401
EARLIER_OWNER_ID: int = 98402

OWNERLESS_ID: int = 98411
SECOND_OWNERLESS_ID: int = 98412
OWNED_ID: int = 98413
NULL_OWNER_ID: int = 98414
ALL_WEBHOOK_IDS: list[int] = [OWNERLESS_ID, SECOND_OWNERLESS_ID, OWNED_ID, NULL_OWNER_ID]


def _webhook(public_id: int, **owner: Any) -> dict[str, Any]:
    """A stored webhook, with whatever owner key it was written with"""
    return {'public_id': public_id, 'name': f'Hook {public_id}', 'url': f'https://h{public_id}.test/hook',
            'event_types': ['CREATE'], 'active': True, **owner}


@pytest.fixture(name='collections', autouse=True)
def fixture_collections(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded webhooks and the second admin - purged after, and the seeded admin active again"""
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)
    webhooks = database_manager.get_collection(CmdbWebhook.COLLECTION, database_name)

    def _purge() -> None:
        users.delete_many({'public_id': SECOND_ADMIN_ID})
        webhooks.delete_many({'public_id': {'$in': ALL_WEBHOOK_IDS}})
        users.update_one({'public_id': SEEDED_ADMIN_ID}, {'$set': {'active': True}})

    _purge()
    users.insert_one({'public_id': SECOND_ADMIN_ID, 'user_name': 'second-admin', 'active': True,
                      'group_id': ADMIN_GROUP_ID})
    webhooks.insert_many([
        _webhook(OWNERLESS_ID), _webhook(SECOND_OWNERLESS_ID), _webhook(OWNED_ID, owner_id=EARLIER_OWNER_ID),
        _webhook(NULL_OWNER_ID, owner_id=None),
    ])
    yield {'users': users, 'webhooks': webhooks}
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261009(database_manager, database_name).start_update()


def _owners(collections: dict[str, Any]) -> dict[int, Any]:
    """The stored owner of each seeded webhook; a missing key reads as the string 'missing'"""
    return {stored['public_id']: stored.get('owner_id', 'missing')
            for stored in collections['webhooks'].find({'public_id': {'$in': ALL_WEBHOOK_IDS}})}


def test_every_ownerless_webhook_gets_the_first_admin(collections, database_manager, database_name) -> None:
    """The lowest-numbered active admin; a recorded owner or a recorded null stays"""
    _run(database_manager, database_name)

    assert _owners(collections) == {
        OWNERLESS_ID: SEEDED_ADMIN_ID, SECOND_OWNERLESS_ID: SEEDED_ADMIN_ID,
        OWNED_ID: EARLIER_OWNER_ID, NULL_OWNER_ID: None,
    }


def test_nothing_else_of_a_webhook_changes(collections, database_manager, database_name) -> None:
    """Only the key is added"""
    before = collections['webhooks'].find_one({'public_id': OWNERLESS_ID}, {'_id': 0})

    _run(database_manager, database_name)

    after = collections['webhooks'].find_one({'public_id': OWNERLESS_ID}, {'_id': 0})
    assert after == {**before, 'owner_id': SEEDED_ADMIN_ID}


def test_a_deactivated_admin_is_passed_over(collections, database_manager, database_name) -> None:
    """The next active admin-group user becomes the owner"""
    collections['users'].update_one({'public_id': SEEDED_ADMIN_ID}, {'$set': {'active': False}})

    _run(database_manager, database_name)

    assert _owners(collections)[OWNERLESS_ID] == SECOND_ADMIN_ID


def test_without_an_active_admin_nothing_is_written(collections, database_manager, database_name) -> None:
    """The webhooks stay ownerless - and deliver nothing until saved again"""
    collections['users'].update_one({'public_id': SEEDED_ADMIN_ID}, {'$set': {'active': False}})
    collections['users'].delete_one({'public_id': SECOND_ADMIN_ID})

    _run(database_manager, database_name)

    assert _owners(collections)[OWNERLESS_ID] == 'missing'


def test_a_second_run_changes_nothing(collections, database_manager, database_name) -> None:
    """Also after the first admin was deactivated in between: an owner once written is not moved"""
    _run(database_manager, database_name)
    first = _owners(collections)
    collections['users'].update_one({'public_id': SEEDED_ADMIN_ID}, {'$set': {'active': False}})

    _run(database_manager, database_name)

    assert _owners(collections) == first
