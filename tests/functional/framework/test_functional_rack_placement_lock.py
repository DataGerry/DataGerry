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
Functional tests: the per-rack placement lock on POST /racks/<id>/mounts/, PATCH /racks/<id>/mounts/<mid> and a
rack height shrink through PATCH /objects/<id>

While another request holds a rack's lock, a mount write on that rack waits its attempts and then answers 400
RACK_BUSY, writing nothing; another rack is not affected; a lock whose holder died (older than the TTL) is taken over;
every write leaves the lock released. A height shrink whose rack stays locked still unplaces what no longer fits. The
races themselves run with real threads in tests/integration/framework/test_integration_rack_placement_lock.py
"""
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import SettingsManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY
from cmdb.manager.system_manager.settings_section_lock_constants import SectionLockKey
from cmdb.models.object_model import CmdbObject
from cmdb.models.rack_model import CmdbRackMount, RackArea
from cmdb.models.rack_model.rack_mount_constants import RackMountKind
from cmdb.models.type_model import CmdbType
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.rack_constants import RackField, RackSection
from cmdb.framework.rack.placement_lock import rack_placement_lock_spec
from cmdb.framework.rack.rack_constants import RackPlacementLock
from cmdb.interface.rest_api.routes.rack_routes.rack_route_constants import RackMountRouteError
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

RACK_URL: str = '/racks'
OBJECTS_URL: str = '/objects'
RACK_TYPE_ID: int = 943301
RACK_ID: int = 943310
OTHER_RACK_ID: int = 943311
RACK_HEIGHT: int = 42
LOWERED_HEIGHT: int = 20
HIGH_SLOT: int = 30
SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'
OTHER_HOLDER: str = 'another-request'
OTHER_USER_ID: int = 943399
EXPIRED_AGE: timedelta = timedelta(seconds=RackPlacementLock.TTL_SECONDS + 60)
FAST_HEIGHT_CHANGE_ATTEMPTS: int = 2
RACK_IDS: list[int] = [RACK_ID, OTHER_RACK_ID]


@pytest.fixture(autouse=True)
def _licensed_and_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rack View is licensed with IPAM; the lock's waits are cut to nothing so a refusal is immediate"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)
    monkeypatch.setattr(RackPlacementLock, 'RETRY_WAIT_SECONDS', 0.0)


def _rack(public_id: int) -> dict[str, Any]:
    """A Rack CmdbObject"""
    return {
        'public_id': public_id, 'type_id': RACK_TYPE_ID, 'active': True, 'author_id': SEED_AUTHOR_ID,
        'version': SEED_VERSION, 'creation_time': datetime.now(timezone.utc),
        'fields': [{'type': 'text', 'name': RackField.NAME.value, 'value': f'rack-{public_id}'},
                   {'type': 'number', 'name': RackField.HEIGHT.value, 'value': RACK_HEIGHT}],
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """The Rack type, two racks, no mounts, no locks - around each test"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    mounts = database_manager.get_collection(CmdbRackMount.COLLECTION, database_name)
    settings = database_manager.get_collection(SettingsManager.COLLECTION, database_name)
    sections: list[str] = [rack_placement_lock_spec(rack_id).section for rack_id in RACK_IDS]

    def _purge() -> None:
        types.delete_many({'public_id': RACK_TYPE_ID})
        objects.delete_many({'public_id': {'$in': RACK_IDS}})
        mounts.delete_many({'rack_id': {'$in': RACK_IDS}})
        settings.delete_many({SETTINGS_SECTION_ID_KEY: {'$in': sections}})

    _purge()
    types.insert_one({
        'public_id': RACK_TYPE_ID, 'name': 'rack-lock-type', 'label': 'Rack', 'author_id': SEED_AUTHOR_ID,
        'creation_time': datetime.now(timezone.utc), 'active': True, 'special_type': SpecialType.RACK.value,
        'fields': [{'type': 'text', 'name': RackField.NAME.value, 'label': 'Rackname', 'required': True},
                   {'type': 'number', 'name': RackField.HEIGHT.value, 'label': 'Height', 'required': True}],
        'render_meta': {'icon': 'fa-server', 'sections': [{
            'type': 'section', 'name': RackSection.INFORMATION.value, 'label': 'Information',
            'fields': [RackField.NAME.value, RackField.HEIGHT.value]}], 'summary': {'fields': [RackField.NAME.value]}},
        'acl': {'activated': False, 'groups': {'includes': {}}}, 'version': SEED_VERSION,
    })
    objects.insert_many([_rack(rack_id) for rack_id in RACK_IDS])
    yield
    _purge()


def _hold(database_manager: MongoDatabaseManager, database_name: str, rack_id: int = RACK_ID,
          age: timedelta = timedelta(0)) -> None:
    """Stores the rack's lock as another request holding it, taken `age` ago"""
    database_manager.get_collection(SettingsManager.COLLECTION, database_name).insert_one({
        SETTINGS_SECTION_ID_KEY: rack_placement_lock_spec(rack_id).section, SectionLockKey.HOLDER.value: OTHER_HOLDER,
        SectionLockKey.ACQUIRED_AT.value: datetime.now(timezone.utc) - age, SectionLockKey.USER_ID.value: OTHER_USER_ID,
    })


def _lock(database_manager: MongoDatabaseManager, database_name: str, rack_id: int = RACK_ID) -> dict[str, Any] | None:
    """The rack's lock as stored"""
    return database_manager.get_collection(SettingsManager.COLLECTION, database_name).find_one(
        {SETTINGS_SECTION_ID_KEY: rack_placement_lock_spec(rack_id).section})


def _mounts(database_manager: MongoDatabaseManager, database_name: str) -> list[dict[str, Any]]:
    """The rack's stored rows"""
    return list(database_manager.get_collection(CmdbRackMount.COLLECTION, database_name).find(
        {'rack_id': RACK_ID}, {'_id': 0}))


def _block(rest_api, rack_id: int = RACK_ID, start_slot: int = 10, height: int = 2):
    """POSTs a blocker row into a U range"""
    return rest_api.post(f'{RACK_URL}/{rack_id}/mounts/', json={
        'kind': RackMountKind.BLOCKER.value, 'area': RackArea.FRONT.value, 'start_slot': start_slot, 'height': height,
    })


def _busy(rack_id: int = RACK_ID) -> str:
    """The 400 a busy rack answers"""
    return RackMountRouteError.RACK_BUSY.format(rack_id=rack_id)


class TestABusyRack:
    """Another request holds the rack's lock"""

    def test_a_post_is_refused_and_writes_nothing(self, rest_api, database_manager, database_name) -> None:
        """400 RACK_BUSY after its attempts; no row; the other request's lock untouched"""
        _hold(database_manager, database_name)

        response = _block(rest_api)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _busy()
        assert not _mounts(database_manager, database_name)
        assert _lock(database_manager, database_name)[SectionLockKey.HOLDER.value] == OTHER_HOLDER

    def test_a_patch_is_refused_and_changes_nothing(self, rest_api, database_manager, database_name) -> None:
        """The re-placement waits for the same lock"""
        mount_id: int = _block(rest_api).get_json()['result_id']
        _hold(database_manager, database_name)

        response = rest_api.patch(f'{RACK_URL}/{RACK_ID}/mounts/{mount_id}', json={'start_slot': 20})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == _busy()
        assert _mounts(database_manager, database_name)[0]['start_slot'] == 10

    def test_another_rack_is_not_affected(self, rest_api, database_manager, database_name) -> None:
        """The lock is per rack"""
        _hold(database_manager, database_name, OTHER_RACK_ID)

        assert _block(rest_api).status_code == HTTPStatus.CREATED

    def test_a_lock_whose_holder_died_is_taken_over(self, rest_api, database_manager, database_name) -> None:
        """Older than the TTL: the write goes through and frees the rack after itself"""
        _hold(database_manager, database_name, age=EXPIRED_AGE)

        assert _block(rest_api).status_code == HTTPStatus.CREATED
        assert _lock(database_manager, database_name) is None


class TestTheLockIsReleased:
    """Every write frees the rack again, whatever it answered"""

    def test_after_a_placement(self, rest_api, database_manager, database_name) -> None:
        """201, and no lock left"""
        assert _block(rest_api).status_code == HTTPStatus.CREATED
        assert _lock(database_manager, database_name) is None

    def test_after_a_refused_placement(self, rest_api, database_manager, database_name) -> None:
        """The overlap 400 inside the lock releases it too"""
        _block(rest_api)

        assert _block(rest_api, start_slot=11).status_code == HTTPStatus.BAD_REQUEST
        assert _lock(database_manager, database_name) is None

    def test_after_a_rack_that_does_not_exist(self, rest_api, database_manager, database_name) -> None:
        """A 404 from inside the lock leaves nothing behind"""
        missing_rack: int = RACK_ID + 1000

        assert _block(rest_api, rack_id=missing_rack).status_code == HTTPStatus.NOT_FOUND
        assert _lock(database_manager, database_name, missing_rack) is None


class TestAHeightShrink:
    """The shrink clean-up holds the same lock - and runs anyway when the rack stays locked"""

    def _lower(self, rest_api) -> Any:
        """PATCHes the rack down to LOWERED_HEIGHT"""
        return rest_api.patch(f'{OBJECTS_URL}/{RACK_ID}',
                              json={'fields': [{'name': RackField.HEIGHT.value, 'value': LOWERED_HEIGHT}]})

    def test_a_shrink_unplaces_and_frees_the_rack(self, rest_api, database_manager, database_name) -> None:
        """The row at U30 lands in UNASSIGNED; no lock left"""
        _block(rest_api, start_slot=HIGH_SLOT)

        assert self._lower(rest_api).status_code == HTTPStatus.ACCEPTED
        assert _mounts(database_manager, database_name)[0]['area'] == RackArea.UNASSIGNED.value
        assert _lock(database_manager, database_name) is None

    def test_a_rack_that_stays_locked_is_still_cleaned_up(
            self, rest_api, database_manager, database_name, monkeypatch: pytest.MonkeyPatch,
            caplog: pytest.LogCaptureFixture) -> None:
        """The new height is stored, so the clean-up runs without the lock and logs it"""
        monkeypatch.setattr(RackPlacementLock, 'HEIGHT_CHANGE_ATTEMPTS', FAST_HEIGHT_CHANGE_ATTEMPTS)
        _block(rest_api, start_slot=HIGH_SLOT)
        _hold(database_manager, database_name)

        assert self._lower(rest_api).status_code == HTTPStatus.ACCEPTED
        assert _mounts(database_manager, database_name)[0]['area'] == RackArea.UNASSIGNED.value
        assert 'stayed locked - unplacing without the lock' in caplog.text
        assert _lock(database_manager, database_name)[SectionLockKey.HOLDER.value] == OTHER_HOLDER
