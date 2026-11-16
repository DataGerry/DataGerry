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
Unit tests for cmdb.framework.rendering.summary_line - the summary line of a rendered object
"""
from cmdb.framework.rendering.summary_line import default_summary_line, join_summary_line
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_LABEL: str = 'Server'
PUBLIC_ID: int = 7
DEFAULT_LINE: str = 'Server #7'


def test_the_default_line_is_label_and_id() -> None:
    """``<type label> #<public_id>``"""
    assert default_summary_line(TYPE_LABEL, PUBLIC_ID) == DEFAULT_LINE


def test_the_values_are_joined_as_text() -> None:
    """Every value as text, in order"""
    assert join_summary_line([{'value': 'web01'}, {'value': 3}], DEFAULT_LINE) == 'web01 | 3'


def test_empty_values_answer_the_default_line() -> None:
    """No summary, or one empty value"""
    assert join_summary_line([], DEFAULT_LINE) == DEFAULT_LINE
    assert join_summary_line([{'value': ''}], DEFAULT_LINE) == DEFAULT_LINE
