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
Unit tests for cmdb.framework.field_pattern_rule

Every construct the browser (JavaScript RegExp, no flags) and the server (Python regex) read differently, or only one
of them accepts, is reported - outside and inside a character class - while the portable constructs, escaped
lookalikes and lazy quantifiers pass. A pattern must be text and compile on the server. On an update only the
patterns a write adds or changes are judged
"""
from typing import Any

import pytest

from cmdb.framework.field_pattern_rule import field_pattern_problem, find_dialect_construct, find_field_pattern_errors
from cmdb.framework.object_field_value_constants import FieldPatternError
# -------------------------------------------------------------------------------------------------------------------- #

FIELD: str = 'code'
OTHER_FIELD: str = 'serial'
PORTABLE: str = r'[A-Z]{2}\d{4}'
REFUSED: str = r'\p{L}+'


class TestFindDialectConstruct:
    """find_dialect_construct"""

    @pytest.mark.parametrize('pattern, construct', [
        (r'\p{L}', r'\p'), (r'\P{L}', r'\P'), (r'\Aabc', r'\A'), (r'abc\Z', r'\Z'), (r'abc\z', r'\z'),
        (r'\cJ', r'\c'), (r'(?<n>a)\k<n>', r'\k'), (r'\u{41}', '\\u{'),
        ('[^]', '[^]'), ('[]a]', '[]'), ('[[:alpha:]]', '[:'), (r'[\p{L}]', r'\p'),
        ('x{,3}', '{,n}'),
        ('(?i)abc', '(?i'), ('(?P<n>a)', '(?P'), ('(?#note)a', '(?#'), ('(?>a)', '(?>'), ('(?x) a', '(?x'),
        ('a++', '++'), ('a*+', '*+'), ('a?+', '?+'), ('a{2}+', '}+'), ('a{2,}+', '}+'),
    ], ids=['p', 'P', 'A', 'Z', 'z', 'c', 'k', 'u-brace', 'empty-negated-class', 'empty-class', 'posix',
            'p-in-class', 'open-lower-bound', 'inline-flag', 'python-named', 'comment', 'atomic', 'verbose',
            'possessive-plus', 'possessive-star', 'possessive-optional', 'possessive-bounded',
            'possessive-open-bounded'])
    def test_a_construct_the_dialects_part_on_is_named(self, pattern: str, construct: str) -> None:
        """The first one found, spelled as the refusal names it"""
        assert find_dialect_construct(pattern) == construct

    @pytest.mark.parametrize('pattern', [
        PORTABLE, '[a-z]+', 'a+?', 'a*?', 'a??', 'a{2,3}?', '(?:a)', '(?=a)', '(?!a)', '(?<=a)b', '(?<!a)b',
        '(?<name>a)', '(?<_n>a)', r'\(?i\)', r'\{,3}', '[(?i)]', '[{,3}]', '[+]+', r'a*\+', 'a{1', r'\d+\.\d*',
        r'\u0041', r'\x41', r'\b\w+\b', '^start$', '', '[^a]', r'[\d\-\]]+',
    ], ids=['portable', 'class', 'lazy-plus', 'lazy-star', 'lazy-optional', 'lazy-bounded', 'non-capturing',
            'lookahead', 'negative-lookahead', 'lookbehind', 'negative-lookbehind', 'named', 'named-underscore',
            'escaped-group', 'escaped-brace', 'group-in-class', 'brace-in-class', 'plus-in-class', 'escaped-plus',
            'unclosed-brace', 'decimal', 'u-escape', 'x-escape', 'word-boundaries', 'anchors', 'empty',
            'negated-class', 'escapes-in-class'])
    def test_a_portable_pattern_passes(self, pattern: str) -> None:
        """Both dialects read it alike"""
        assert find_dialect_construct(pattern) is None

    def test_an_unclosed_class_is_left_to_the_compiler(self) -> None:
        """The scanner reaches the end without a finding"""
        assert find_dialect_construct('[abc') is None


class TestFieldPatternProblem:
    """field_pattern_problem"""

    @pytest.mark.parametrize('regex', [None, ''], ids=['none', 'empty'])
    def test_no_pattern_is_no_problem(self, regex: Any) -> None:
        """A field without a pattern"""
        assert field_pattern_problem(FIELD, regex) is None

    @pytest.mark.parametrize('regex, kind', [(5, 'int'), (['a'], 'list'), (True, 'bool')],
                             ids=['number', 'list', 'boolean'])
    def test_a_pattern_that_is_no_text_is_refused(self, regex: Any, kind: str) -> None:
        """The object form could not build a validator from it"""
        assert field_pattern_problem(FIELD, regex) == FieldPatternError.NOT_A_STRING.format(field=FIELD, kind=kind)

    def test_a_dialect_construct_is_refused_by_name(self) -> None:
        """Before compiling"""
        assert field_pattern_problem(FIELD, REFUSED) == FieldPatternError.DIALECT.format(field=FIELD, construct=r'\p')

    @pytest.mark.parametrize('regex', ['(', r'\x', r'\8', 'a**'], ids=['unclosed', 'bare-x', 'backref-8', 'repeat'])
    def test_a_pattern_the_server_cannot_compile_is_refused(self, regex: str) -> None:
        """With the compiler's reason"""
        problem = field_pattern_problem(FIELD, regex)

        assert problem is not None
        assert problem.startswith(FieldPatternError.NOT_COMPILABLE.format(field=FIELD, detail='').rstrip())

    def test_a_portable_pattern_passes(self) -> None:
        """The ordinary case"""
        assert field_pattern_problem(FIELD, PORTABLE) is None


class TestFindFieldPatternErrors:
    """find_field_pattern_errors"""

    def test_a_create_judges_every_pattern_in_field_order(self) -> None:
        """One message per refused field"""
        fields = [{'name': OTHER_FIELD, 'regex': '(?i)a'}, {'name': FIELD, 'regex': PORTABLE},
                  {'name': 'third', 'regex': REFUSED}]

        assert find_field_pattern_errors(fields) == [
            field_pattern_problem(OTHER_FIELD, '(?i)a'), field_pattern_problem('third', REFUSED)]

    def test_an_update_keeping_a_stored_pattern_passes(self) -> None:
        """A stored pattern the rule refuses stays saveable"""
        fields = [{'name': FIELD, 'regex': REFUSED}]

        assert not find_field_pattern_errors(fields, [{'name': FIELD, 'regex': REFUSED}])

    def test_an_update_changing_a_pattern_is_judged(self) -> None:
        """A changed pattern is new"""
        assert find_field_pattern_errors([{'name': FIELD, 'regex': REFUSED}], [{'name': FIELD, 'regex': PORTABLE}])

    def test_an_update_adding_a_field_is_judged(self) -> None:
        """A new field's pattern is new"""
        assert find_field_pattern_errors([{'name': OTHER_FIELD, 'regex': REFUSED}], [{'name': FIELD, 'regex': REFUSED}])

    @pytest.mark.parametrize('fields', [None, 'x', [None, 'x', 3]], ids=['none', 'string', 'non-documents'])
    def test_unreadable_fields_are_skipped(self, fields: Any) -> None:
        """The structure rules answer for those"""
        assert not find_field_pattern_errors(fields, [None, 'x'])
