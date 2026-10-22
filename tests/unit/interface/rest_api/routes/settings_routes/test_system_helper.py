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
Unit tests for cmdb.interface.rest_api.routes.settings_routes.system_helper

``build_system_information``: on premise every key, in cloud mode only the build and the tenant's database
version. ``read_db_version``: the recorded version; a missing section, a missing version and a failed read are
``UNKNOWN_DB_VERSION``; any other error is raised. ``read_host_name``: the machine's name on premise, None in cloud
mode and when it cannot be resolved. ``build_deployment_information``: the four keys of the deployment route
"""
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb import __title__, __version__
from cmdb.security.license.license_constants import FINGERPRINT_FALLBACK
from cmdb.interface.rest_api.routes.settings_routes.system_constants import (
    UNKNOWN_DB_VERSION,
    UPDATER_SETTINGS_SECTION,
    DeploymentInfoKey,
    DeploymentKind,
    SystemInfoKey,
)
from cmdb.interface.rest_api.routes.settings_routes.system_helper import (
    build_deployment_information,
    build_system_information,
    read_db_version,
    read_host_name,
)

from cmdb.errors.database import DocumentGetError
# -------------------------------------------------------------------------------------------------------------------- #

DB_VERSION: int = 20261008
HELPER_PATH: str = 'cmdb.interface.rest_api.routes.settings_routes.system_helper'
HOST_NAME: str = 'cmdb-host-01'
HOST_KEYS: set[str] = {SystemInfoKey.RUNTIME.value, SystemInfoKey.STARTING_PARAMETERS.value}


class TestBuildSystemInformation:
    """What a deployment may show"""

    def test_on_premise_answers_every_key(self) -> None:
        """The build, the version, the uptime and the command line"""
        information = build_system_information(DB_VERSION, cloud_mode=False)

        assert set(information) == {key.value for key in SystemInfoKey}
        assert information[SystemInfoKey.TITLE.value] == __title__
        assert information[SystemInfoKey.VERSION.value] == __version__
        assert information[SystemInfoKey.DB_VERSION.value] == DB_VERSION
        assert information[SystemInfoKey.STARTING_PARAMETERS.value] == sys.argv
        assert information[SystemInfoKey.RUNTIME.value] >= 0

    def test_cloud_mode_leaves_the_host_process_out(self) -> None:
        """The uptime and the command line belong to the host every tenant shares"""
        information = build_system_information(DB_VERSION, cloud_mode=True)

        assert not HOST_KEYS & set(information)
        assert information == {
            SystemInfoKey.TITLE.value: __title__,
            SystemInfoKey.VERSION.value: __version__,
            SystemInfoKey.DB_VERSION.value: DB_VERSION,
        }


def _settings_manager(section: Any = None, error: Exception | None = None) -> MagicMock:
    """A SettingsManager stand-in answering ``section``, or raising ``error``"""
    manager = MagicMock()
    manager.get_all_values_from_section.return_value = section

    if error is not None:
        manager.get_all_values_from_section.side_effect = error

    return manager


class TestReadDbVersion:
    """The version the updater recorded"""

    def test_answers_the_recorded_version(self) -> None:
        """Read from the updater section, with an empty default so a missing section is no error"""
        manager = _settings_manager({SystemInfoKey.VERSION.value: DB_VERSION})

        assert read_db_version(manager) == DB_VERSION
        manager.get_all_values_from_section.assert_called_once_with(UPDATER_SETTINGS_SECTION, default={})

    @pytest.mark.parametrize('section', [{}, {SystemInfoKey.VERSION.value: None}], ids=['no-section', 'no-version'])
    def test_nothing_recorded_is_unknown(self, section: dict[str, Any]) -> None:
        """A database the updater never touched"""
        assert read_db_version(_settings_manager(section)) == UNKNOWN_DB_VERSION

    def test_a_failed_read_is_unknown(self) -> None:
        """The rest of the information is still valid"""
        assert read_db_version(_settings_manager(error=DocumentGetError('down'))) == UNKNOWN_DB_VERSION

    def test_any_other_error_is_raised(self) -> None:
        """A defect is not reported as an unknown version"""
        with pytest.raises(RuntimeError):
            read_db_version(_settings_manager(error=RuntimeError('boom')))


class TestReadHostName:
    """The machine's name, on premise only"""

    def test_on_premise_the_machine_is_named(self) -> None:
        """The name the licence fingerprint reads"""
        with patch(f'{HELPER_PATH}.get_computer_name', return_value=HOST_NAME):
            assert read_host_name(cloud_mode=False) == HOST_NAME

    def test_in_cloud_mode_the_shared_machine_is_unnamed(self) -> None:
        """Not even read: every tenant shares it"""
        with patch(f'{HELPER_PATH}.get_computer_name') as get_computer_name:
            assert read_host_name(cloud_mode=True) is None

        get_computer_name.assert_not_called()

    def test_an_unresolvable_name_is_none_not_the_fingerprint_placeholder(self) -> None:
        """The fingerprint's fallback is a placeholder, not a machine name"""
        with patch(f'{HELPER_PATH}.get_computer_name', return_value=FINGERPRINT_FALLBACK):
            assert read_host_name(cloud_mode=False) is None


class TestBuildDeploymentInformation:
    """The four keys of GET /settings/system/deployment/"""

    def test_on_premise(self) -> None:
        """Every value as handed in, the deployment named on_premise"""
        assert build_deployment_information(False, True, HOST_NAME) == {
            DeploymentInfoKey.DEPLOYMENT.value: DeploymentKind.ON_PREMISE.value,
            DeploymentInfoKey.VERSION.value: __version__,
            DeploymentInfoKey.DATABASE_REACHABLE.value: True,
            DeploymentInfoKey.HOST_NAME.value: HOST_NAME,
        }

    def test_cloud(self) -> None:
        """The deployment named cloud; an unreachable database and no host name answered as such"""
        assert build_deployment_information(True, False, None) == {
            DeploymentInfoKey.DEPLOYMENT.value: DeploymentKind.CLOUD.value,
            DeploymentInfoKey.VERSION.value: __version__,
            DeploymentInfoKey.DATABASE_REACHABLE.value: False,
            DeploymentInfoKey.HOST_NAME.value: None,
        }

    def test_the_keys_are_exactly_the_contract(self) -> None:
        """Nothing more and nothing less than DeploymentInfoKey"""
        assert set(build_deployment_information(False, True, None)) == {key.value for key in DeploymentInfoKey}
