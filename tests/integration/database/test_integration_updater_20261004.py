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
Integration tests for cmdb.database.updater.versions.updater_20261004 against a real MongoDB

Seeds CI-Explorer profiles with and without the new ``with_port_connections`` toggle, runs the migration,
and asserts:

  - a profile without the toggle gains it, at its default (true)
  - a profile that already holds it - false included - is left alone
  - the other two toggles are never touched, even where they differ from the new defaults
  - a second run changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.updater.versions.updater_20261004 import Update20261004
from cmdb.models.ci_explorer_model import CiExplorerProfileKey, CmdbCiExplorerProfile
# -------------------------------------------------------------------------------------------------------------------- #

LACKING_ID: int = 97801
HOLDING_FALSE_ID: int = 97802
HOLDING_TRUE_ID: int = 97803
ALL_IDS: list[int] = [LACKING_ID, HOLDING_FALSE_ID, HOLDING_TRUE_ID]

PUBLIC_ID: str = CiExplorerProfileKey.PUBLIC_ID.value
WITH_LOCATIONS: str = CiExplorerProfileKey.WITH_LOCATIONS.value
WITH_IPAM: str = CiExplorerProfileKey.WITH_IPAM_RELATIONS.value
WITH_PORTS: str = CiExplorerProfileKey.WITH_PORT_CONNECTIONS.value


def _profile_doc(public_id: int, **toggles: Any) -> dict[str, Any]:
    """A stored profile written before the third toggle: locations on, IPAM off (the old defaults)"""
    return {
        PUBLIC_ID: public_id, CiExplorerProfileKey.NAME.value: f'profile-{public_id}',
        CiExplorerProfileKey.TYPES_FILTER.value: [], CiExplorerProfileKey.RELATIONS_FILTER.value: [],
        WITH_LOCATIONS: True, WITH_IPAM: False, **toggles,
    }


@pytest.fixture(name='profiles', autouse=True)
def fixture_profiles(database_manager: MongoDatabaseManager, database_name: str):
    """The seeded profiles, purged before and after"""
    collection = database_manager.get_collection(CmdbCiExplorerProfile.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({PUBLIC_ID: {'$in': ALL_IDS}})

    _purge()
    collection.insert_many([
        _profile_doc(LACKING_ID),
        _profile_doc(HOLDING_FALSE_ID, **{WITH_PORTS: False}),
        _profile_doc(HOLDING_TRUE_ID, **{WITH_PORTS: True}),
    ])
    yield collection
    _purge()


def _run(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One run of the migration"""
    Update20261004(database_manager, database_name).start_update()


def _stored(profiles, public_id: int) -> dict[str, Any]:
    """One stored profile"""
    return profiles.find_one({PUBLIC_ID: public_id})


def test_a_profile_without_the_toggle_gains_its_default(database_manager, database_name, profiles) -> None:
    """True - what the model already read it as"""
    _run(database_manager, database_name)

    assert _stored(profiles, LACKING_ID)[WITH_PORTS] is True


@pytest.mark.parametrize('public_id, value', [(HOLDING_FALSE_ID, False), (HOLDING_TRUE_ID, True)],
                         ids=['false', 'true'])
def test_a_stored_toggle_is_left_alone(database_manager, database_name, profiles, public_id: int, value: bool) -> None:
    """A profile that already says something keeps saying it"""
    _run(database_manager, database_name)

    assert _stored(profiles, public_id)[WITH_PORTS] is value


def test_the_other_toggles_are_not_touched(database_manager, database_name, profiles) -> None:
    """The stored IPAM toggle stays false, though the default is now true"""
    _run(database_manager, database_name)

    stored = _stored(profiles, LACKING_ID)
    assert (stored[WITH_LOCATIONS], stored[WITH_IPAM]) == (True, False)


def test_a_second_run_changes_nothing(database_manager, database_name, profiles) -> None:
    """Re-run safe"""
    _run(database_manager, database_name)
    first = {public_id: _stored(profiles, public_id) for public_id in ALL_IDS}

    _run(database_manager, database_name)

    assert {public_id: _stored(profiles, public_id) for public_id in ALL_IDS} == first


def test_the_model_reads_the_same_before_and_after(database_manager, database_name, profiles) -> None:
    """The migration changes nothing a client sees: the model filled the missing toggle in already"""
    before = CmdbCiExplorerProfile.to_json(CmdbCiExplorerProfile.from_data(_stored(profiles, LACKING_ID)))

    _run(database_manager, database_name)

    assert CmdbCiExplorerProfile.to_json(CmdbCiExplorerProfile.from_data(_stored(profiles, LACKING_ID))) == before
