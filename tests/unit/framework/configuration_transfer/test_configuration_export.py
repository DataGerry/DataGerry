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
Unit tests for cmdb.framework.configuration_transfer.configuration_export

Pure tests: no Mongo, no Flask. What is pinned here: the database version is read from the updater section and
only a positive JSON integer counts - a missing section, a missing key, zero, a bool or a string answer None
instead of a version the file would be wrongly stamped with - and an export is one section per component under
its name, in the order given, around the version
"""
from typing import Any
from unittest.mock import MagicMock

import pytest

from cmdb.database.database_services.database_services_constants import UpdaterSetting
from cmdb.framework.configuration_transfer import (
    TransferComponentName,
    TransferFileKey,
    export_configuration,
    read_database_version,
)
# -------------------------------------------------------------------------------------------------------------------- #

DB_VERSION: int = 20261014
VERSION_KEY: str = UpdaterSetting.VERSION.value
TYPES_SECTION: dict[str, Any] = {'counter': 5, 'items': [{'public_id': 5}]}
RELATIONS_SECTION: dict[str, Any] = {'counter': 2, 'items': []}


def _settings(section: dict[str, Any] | None) -> MagicMock:
    """A settings manager answering the given updater section"""
    settings: MagicMock = MagicMock()
    settings.get_section.return_value = section

    return settings


def _component(name: TransferComponentName, section: dict[str, Any]) -> MagicMock:
    """A component answering the given section"""
    component: MagicMock = MagicMock()
    component.NAME = name
    component.export_section.return_value = section

    return component


def test_read_database_version_reads_the_updater_section() -> None:
    """The recorded version, from the 'updater' section"""
    settings: MagicMock = _settings({VERSION_KEY: DB_VERSION})

    assert read_database_version(settings) == DB_VERSION
    settings.get_section.assert_called_once_with(UpdaterSetting.SECTION.value)


@pytest.mark.parametrize('section', [
    None,
    {},
    {VERSION_KEY: None},
    {VERSION_KEY: 0},
    {VERSION_KEY: -DB_VERSION},
    {VERSION_KEY: True},
    {VERSION_KEY: str(DB_VERSION)},
    {VERSION_KEY: float(DB_VERSION)},
])
def test_read_database_version_answers_none_for_no_valid_version(section: dict[str, Any] | None) -> None:
    """Nothing recorded or nothing a file could be stamped with -> None"""
    assert read_database_version(_settings(section)) is None


def test_export_configuration_writes_one_section_per_component_in_order() -> None:
    """Each component's section under its name, in the given order, stamped with the version"""
    exported: dict[str, Any] = export_configuration(
        [_component(TransferComponentName.TYPES, TYPES_SECTION),
         _component(TransferComponentName.RELATIONS, RELATIONS_SECTION)],
        DB_VERSION,
    )

    assert exported[TransferFileKey.DB_VERSION.value] == DB_VERSION
    assert list(exported[TransferFileKey.COMPONENTS.value].items()) == [
        (TransferComponentName.TYPES.value, TYPES_SECTION),
        (TransferComponentName.RELATIONS.value, RELATIONS_SECTION),
    ]
