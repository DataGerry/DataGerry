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
Unit tests for cmdb.utils.name_shape

The name rule a user's login name and a group's name are held to: not blank, no surrounding whitespace, no control
character. Covers each problem, the order they are reported in, the whitespace ``str.strip`` knows beyond ASCII,
the names the rule accepts, the Cerberus hook, and the two schemas that use it
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from cerberus import Validator

from cmdb.class_schema.write_schema_helper import build_write_schema
from cmdb.models.group_model import CmdbUserGroup, GroupKey
from cmdb.models.user_model import CmdbUser, CmdbUserKey
from cmdb.utils import NameShapeProblem, check_name_shape, name_shape_problem, strip_name
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'name'
GOOD_NAME: str = 'Jane Doe'


class TestStripName:
    """strip_name"""

    @pytest.mark.parametrize('name, expected', [
        (' bob ', 'bob'), ('\tbob\n', 'bob'), ('\u00a0bob\u2003', 'bob'), ('b o b', 'b o b'), ('   ', ''),
    ], ids=['spaces', 'tab-newline', 'unicode-spaces', 'inner-kept', 'blank'])
    def test_only_the_surrounding_whitespace_goes(self, name: str, expected: str) -> None:
        """The inside of the name is never touched"""
        assert strip_name(name) == expected


class TestNameShapeProblem:
    """name_shape_problem"""

    @pytest.mark.parametrize('name', ['', ' ', '   ', '\t\n', '\u00a0'],
                             ids=['empty', 'space', 'spaces', 'tab-newline', 'no-break-space'])
    def test_a_blank_name_is_blank(self, name: str) -> None:
        """Nothing is left once stripped"""
        assert name_shape_problem(name) is NameShapeProblem.BLANK

    @pytest.mark.parametrize('name', [' bob', 'bob ', ' bob ', '\tbob', 'bob\n', '\u00a0bob', 'bob\u2003'],
                             ids=['leading', 'trailing', 'both', 'leading-tab', 'trailing-newline',
                                  'no-break-space', 'em-space'])
    def test_a_padded_name_is_padded(self, name: str) -> None:
        """Every whitespace str.strip removes counts, not only ASCII"""
        assert name_shape_problem(name) is NameShapeProblem.PADDED

    @pytest.mark.parametrize('name', ['a\tb', 'a\nb', 'a\rb', 'a\x00b', 'a\x7fb', 'a\x1bb'],
                             ids=['tab', 'newline', 'carriage-return', 'nul', 'delete', 'escape'])
    def test_a_control_character_inside_is_refused(self, name: str) -> None:
        """Whitespace or not, a control character inside the name is refused"""
        assert name_shape_problem(name) is NameShapeProblem.CONTROL_CHARACTER

    def test_padding_is_reported_before_a_control_character(self) -> None:
        """The first problem found answers"""
        assert name_shape_problem(' a\tb') is NameShapeProblem.PADDED

    @pytest.mark.parametrize('name', ['bob', GOOD_NAME, 'Jürgen', 'admin-2', 'a.b@c', '名前', 'a\u00a0b'],
                             ids=['plain', 'inner-space', 'umlaut', 'dash-digit', 'punctuation', 'cjk',
                                  'inner-no-break-space'])
    def test_a_usable_name_has_no_problem(self, name: str) -> None:
        """Whitespace inside the name is allowed - only a control character is not"""
        assert name_shape_problem(name) is None


class TestCheckNameShape:
    """check_name_shape, the Cerberus hook"""

    def test_a_problem_is_reported_with_its_wording(self) -> None:
        """The schema 400 names the field and the reason"""
        error = MagicMock()

        check_name_shape(FIELD, ' bob ', error)

        error.assert_called_once_with(FIELD, NameShapeProblem.PADDED.value)

    def test_a_usable_name_reports_nothing(self) -> None:
        """The ordinary case"""
        error = MagicMock()

        check_name_shape(FIELD, GOOD_NAME, error)

        error.assert_not_called()

    @pytest.mark.parametrize('value', [None, 5, ['bob']], ids=['none', 'integer', 'list'])
    def test_a_value_that_is_no_string_is_the_type_rules(self, value: Any) -> None:
        """Not reported twice"""
        error = MagicMock()

        check_name_shape(FIELD, value, error)

        error.assert_not_called()


class TestTheSchemasUseIt:
    """CmdbUser.SCHEMA user_name and CmdbUserGroup.SCHEMA name, through the write schema the routes use"""

    @pytest.mark.parametrize('schema, field', [
        (CmdbUser.SCHEMA, CmdbUserKey.USER_NAME.value), (CmdbUserGroup.SCHEMA, GroupKey.NAME.value),
    ], ids=['user_name', 'group-name'])
    @pytest.mark.parametrize('name, problem', [
        ('', NameShapeProblem.BLANK), (' bob ', NameShapeProblem.PADDED), ('a\nb', NameShapeProblem.CONTROL_CHARACTER),
    ], ids=['blank', 'padded', 'control'])
    def test_a_refused_name_fails_the_field(self, schema: dict[str, Any], field: str, name: str,
                                            problem: NameShapeProblem) -> None:
        """Exactly this field, with exactly this reason"""
        validator = Validator(build_write_schema(schema), purge_unknown=True)

        assert not validator.validate({field: name})
        assert validator.errors[field] == [problem.value]

    @pytest.mark.parametrize('schema, field', [
        (CmdbUser.SCHEMA, CmdbUserKey.USER_NAME.value), (CmdbUserGroup.SCHEMA, GroupKey.NAME.value),
    ], ids=['user_name', 'group-name'])
    def test_a_usable_name_passes_the_field(self, schema: dict[str, Any], field: str) -> None:
        """The field raises nothing - whatever else the body lacks"""
        validator = Validator(build_write_schema(schema), purge_unknown=True)
        validator.validate({field: GOOD_NAME})

        assert field not in validator.errors
