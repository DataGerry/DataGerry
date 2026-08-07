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
Unit tests for RenderResult

The serialization is a frontend contract: the Angular `RenderResult` model mirrors the attribute
names one to one, and declares `current_render_time` as the bson extended-JSON `{$date: ...}` shape,
which the `database_utils.default` hook produces from the raw datetime left in place here.
"""
from datetime import datetime

from cmdb.framework.rendering.render_result import RenderResult
# -------------------------------------------------------------------------------------------------------------------- #

SUMMARY_LINE: str = 'host-1'


class TestRenderResultToJson:
    """`to_json` dumps the attributes, detached from the instance."""

    def test_exposes_every_attribute(self) -> None:
        """The serialized keys are exactly the instance attributes - the wire contract."""
        result = RenderResult()

        assert set(result.to_json()) == set(vars(result))

    def test_values_match_the_attributes(self) -> None:
        """A written attribute is reflected in the serialized body."""
        result = RenderResult()
        result.summary_line = SUMMARY_LINE

        assert result.to_json()['summary_line'] == SUMMARY_LINE

    def test_leaves_the_render_time_as_a_datetime(self) -> None:
        """The timestamp is not pre-converted, so the JSON hook can emit its {$date: ...} form."""
        assert isinstance(RenderResult().to_json()['current_render_time'], datetime)

    def test_returns_a_detached_copy(self) -> None:
        """Mutating the returned mapping does not reach back into the render result."""
        result = RenderResult()
        body = result.to_json()
        body['summary_line'] = SUMMARY_LINE

        assert result.summary_line == ''

    def test_is_equal_to_the_instance_dict(self) -> None:
        """Serialization stays a plain attribute dump, so no consumer sees a shape change."""
        result = RenderResult()

        assert result.to_json() == vars(result)
