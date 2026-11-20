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
Unit tests of section_template_helper.guard_template_sync_targets

Pinned: a template that is not global reads nothing; a global one reads the settings, and the consuming Types only
while the sync has a target; only a target carrying the template's section counts; a refusal aborts 400
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.person_sync.sync_settings import PersonSyncSettings, UserSyncSettings
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper import (
    guard_template_sync_targets,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper'
TEMPLATE_NAME: str = 'badge'
TARGET_TYPE_ID: int = 71
OTHER_TYPE_ID: int = 72
USER: Any = SimpleNamespace(public_id=1)
REQUIRED_FIELD: dict[str, Any] = {'type': 'text', 'name': 'badge_number', 'label': 'Badge', 'required': True}
PARAMS: dict[str, Any] = {'name': TEMPLATE_NAME, 'fields': [REQUIRED_FIELD]}
TARGETING: PersonSyncSettings = PersonSyncSettings(users=UserSyncSettings(default_type_id=TARGET_TYPE_ID))


def _template(is_global: bool = True) -> Any:
    """The stored template"""
    return SimpleNamespace(is_global=is_global, type='section')


def _type(public_id: int, carries_section: bool = True) -> Any:
    """A Type using the template"""
    return SimpleNamespace(public_id=public_id,
                           get_section=lambda name: object() if carries_section and name == TEMPLATE_NAME else None)


def test_a_template_that_is_not_global_reads_nothing() -> None:
    """It is copied nowhere"""
    templates = MagicMock()

    with patch(f'{PATH}.ManagerProvider') as provider:
        guard_template_sync_targets(USER, templates, _template(is_global=False), PARAMS)

    provider.get_manager.assert_not_called()
    templates.get_types_using_template.assert_not_called()


def test_without_a_target_no_type_is_read() -> None:
    """The settings say the sync writes nowhere"""
    templates = MagicMock()

    with patch(f'{PATH}.ManagerProvider'), patch(f'{PATH}.read_sync_settings', return_value=PersonSyncSettings()):
        guard_template_sync_targets(USER, templates, _template(), PARAMS)

    templates.get_types_using_template.assert_not_called()


def test_a_target_carrying_the_section_is_refused() -> None:
    """400 naming it"""
    templates = MagicMock()
    templates.get_types_using_template.return_value = [_type(TARGET_TYPE_ID), _type(OTHER_TYPE_ID)]

    with patch(f'{PATH}.ManagerProvider'), patch(f'{PATH}.read_sync_settings', return_value=TARGETING), \
         pytest.raises(HTTPException) as raised:
        guard_template_sync_targets(USER, templates, _template(), PARAMS)

    assert raised.value.code == 400
    assert str([TARGET_TYPE_ID]) in raised.value.description


def test_a_target_without_the_section_does_not_count() -> None:
    """The propagation skips it - nothing is copied into it"""
    templates = MagicMock()
    templates.get_types_using_template.return_value = [_type(TARGET_TYPE_ID, carries_section=False)]

    with patch(f'{PATH}.ManagerProvider'), patch(f'{PATH}.read_sync_settings', return_value=TARGETING):
        guard_template_sync_targets(USER, templates, _template(), PARAMS)
