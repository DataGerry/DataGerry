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
Unit tests for the three writes the field pattern rule guards

The type routes (``types_structure_helper.guard_field_patterns``), the section-template routes
(``section_template_helper.guard_template_fields``) and the type import (``importer_type_rules.field_patterns_error``)
refuse a pattern the browser and the server read differently - on an update only the patterns the write adds or
changes - with the rule's own wording
"""
from types import SimpleNamespace
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.framework.field_pattern_rule import field_pattern_problem
from cmdb.framework.object_field_value_constants import FIELD_DEFAULT_ERROR_SEPARATOR
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper import (
    guard_template_fields,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_structure_helper import guard_field_patterns
from cmdb.interface.rest_api.routes.importer_routes.importer_type_rules import field_patterns_error
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'code'
OTHER_FIELD: str = 'serial'
REFUSED: str = r'\p{L}+'
OTHER_REFUSED: str = '(?i)a'
PORTABLE: str = '[A-Z]+'


def _field(name: str, regex: Any) -> dict[str, Any]:
    """A text field definition."""
    return {'type': 'text', 'name': name, 'label': name.title(), 'regex': regex}


def _stored_type(*fields: dict[str, Any]) -> Any:
    """A stored CmdbType stand-in answering get_fields."""
    return SimpleNamespace(get_fields=lambda: list(fields))


def _refusal(call: Any) -> str:
    """The 400 a guard raises."""
    with pytest.raises(HTTPException) as exc_info:
        call()

    assert exc_info.value.code == 400
    return exc_info.value.description


class TestTypeRoutes:
    """guard_field_patterns"""

    def test_a_create_refuses_every_refused_pattern_joined(self) -> None:
        """All of them at once"""
        data = {'fields': [_field(FIELD, REFUSED), _field(OTHER_FIELD, OTHER_REFUSED)]}

        assert _refusal(lambda: guard_field_patterns(data)) == FIELD_DEFAULT_ERROR_SEPARATOR.join([
            field_pattern_problem(FIELD, REFUSED), field_pattern_problem(OTHER_FIELD, OTHER_REFUSED)])

    def test_an_update_keeping_the_stored_pattern_passes(self) -> None:
        """A stored pattern the rule refuses - saveable"""
        guard_field_patterns({'fields': [_field(FIELD, REFUSED)]}, _stored_type(_field(FIELD, REFUSED)))

    def test_an_update_changing_the_pattern_is_refused(self) -> None:
        """A changed pattern is judged"""
        data = {'fields': [_field(FIELD, REFUSED)]}

        assert _refusal(lambda: guard_field_patterns(data, _stored_type(_field(FIELD, PORTABLE)))) == \
            field_pattern_problem(FIELD, REFUSED)

    def test_portable_patterns_pass(self) -> None:
        """The ordinary create"""
        guard_field_patterns({'fields': [_field(FIELD, PORTABLE), _field(OTHER_FIELD, None)]})


class TestSectionTemplates:
    """guard_template_fields"""

    def test_a_create_refuses_a_refused_pattern(self) -> None:
        """Before the default check"""
        assert _refusal(lambda: guard_template_fields([_field(FIELD, REFUSED)])) == \
            field_pattern_problem(FIELD, REFUSED)

    def test_an_update_keeping_the_stored_pattern_passes(self) -> None:
        """Judged against the stored template's fields"""
        guard_template_fields([_field(FIELD, REFUSED)], [_field(FIELD, REFUSED)])

    def test_an_update_changing_the_pattern_is_refused(self) -> None:
        """A changed pattern is judged"""
        assert _refusal(lambda: guard_template_fields([_field(FIELD, REFUSED)], [_field(FIELD, PORTABLE)])) == \
            field_pattern_problem(FIELD, REFUSED)


class TestTypeImport:
    """field_patterns_error"""

    def test_a_create_entry_reports_every_refused_pattern(self) -> None:
        """Joined, like the route"""
        assert field_patterns_error([_field(FIELD, REFUSED), _field(OTHER_FIELD, OTHER_REFUSED)]) == \
            FIELD_DEFAULT_ERROR_SEPARATOR.join([field_pattern_problem(FIELD, REFUSED),
                                                field_pattern_problem(OTHER_FIELD, OTHER_REFUSED)])

    def test_an_update_entry_keeping_the_stored_pattern_passes(self) -> None:
        """As on the update route"""
        assert field_patterns_error([_field(FIELD, REFUSED)], [_field(FIELD, REFUSED)]) is None

    def test_portable_patterns_pass(self) -> None:
        """Nothing to report"""
        assert field_patterns_error([_field(FIELD, PORTABLE)]) is None
