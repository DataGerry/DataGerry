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
Unit tests for cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_template_helper

The type write routes' use of the global-template reconcile: the templates are read once for the claims, a conflict
is the 400 the routes answer, and the dropped claims are handed back for the update's removed-template computation
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.section_templates.global_template_reconcile import (
    GlobalTemplateReconcile,
    TemplateSectionConflict,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_template_helper import (
    abort_on_template_section_conflict,
    reconcile_global_template_copies,
)
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_template_helper'
TEMPLATE_NAME: str = 'dg-modelspec'
TEMPLATE: dict[str, Any] = {
    'name': TEMPLATE_NAME, 'label': 'Model', 'type': 'section', 'is_global': True,
    'fields': [{'type': 'text', 'name': 'dg-modelspec-model', 'label': 'Model'}],
}


def _manager(templates: list[dict[str, Any]]) -> MagicMock:
    """A SectionTemplatesManager stand-in answering the given templates"""
    manager = MagicMock()
    manager.find.return_value = templates
    return manager


class TestReconcileGlobalTemplateCopies:
    """The routes' entry point"""

    def test_a_payload_without_claims_reads_no_templates(self) -> None:
        """No manager, no query"""
        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager') as get_manager:
            assert reconcile_global_template_copies({'name': 'plain'}, MagicMock()) == []

        get_manager.assert_not_called()

    def test_the_copy_is_reconciled_from_the_stored_templates(self) -> None:
        """The payload is changed in place"""
        payload: dict[str, Any] = {'global_template_ids': [TEMPLATE_NAME], 'fields': [], 'render_meta': {}}

        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager', return_value=_manager([TEMPLATE])):
            reconcile_global_template_copies(payload, MagicMock())

        assert payload['fields'] == TEMPLATE['fields']
        assert payload['render_meta']['sections'][0]['name'] == TEMPLATE_NAME

    def test_the_dropped_claims_are_handed_back(self) -> None:
        """The update keeps them out of the removed-template cleanup"""
        payload: dict[str, Any] = {'global_template_ids': [TEMPLATE_NAME, 'gone'], 'fields': [], 'render_meta': {}}

        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager', return_value=_manager([TEMPLATE])):
            assert reconcile_global_template_copies(payload, MagicMock()) == ['gone']

        assert payload['global_template_ids'] == [TEMPLATE_NAME]

    def test_a_foreign_field_is_a_400(self) -> None:
        """Before anything is written"""
        payload: dict[str, Any] = {
            'global_template_ids': [TEMPLATE_NAME], 'fields': [{'type': 'text', 'name': 'own', 'label': 'Own'}],
            'render_meta': {'sections': [{'type': 'section', 'name': TEMPLATE_NAME, 'fields': ['own']}]},
        }

        with patch(f'{MODULE_PATH}.ManagerProvider.get_manager', return_value=_manager([TEMPLATE])):
            with pytest.raises(HTTPException) as exc_info:
                reconcile_global_template_copies(payload, MagicMock())

        assert exc_info.value.code == 400


class TestAbortOnTemplateSectionConflict:
    """The 400's message"""

    def test_names_the_first_template_and_its_fields(self) -> None:
        """Sorted and comma-joined"""
        outcome = GlobalTemplateReconcile(
            conflicts=[TemplateSectionConflict(TEMPLATE_NAME, 'b'), TemplateSectionConflict(TEMPLATE_NAME, 'a')],
            dropped_claims=[],
        )

        with pytest.raises(HTTPException) as exc_info:
            abort_on_template_section_conflict(outcome)

        assert exc_info.value.description == TEMPLATE_SECTION_FOREIGN_FIELD_MESSAGE.format(
            template=TEMPLATE_NAME, names='a, b',
        )

    def test_no_conflict_passes(self) -> None:
        """No exception"""
        abort_on_template_section_conflict(GlobalTemplateReconcile(conflicts=[], dropped_claims=[]))
