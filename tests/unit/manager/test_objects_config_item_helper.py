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
Unit tests for cmdb.manager.objects_config_item_helper - which objects a ConfigItem limit counts

Which documents the filter matches is pinned against a real MongoDB in the integration tier; here the filter's
shape and its freshness per call
"""
from cmdb.manager.objects_config_item_helper import config_item_criteria
# -------------------------------------------------------------------------------------------------------------------- #

SYSTEM_REF_KEY: str = 'system_ref'


def test_the_criteria_leaves_out_every_linked_object() -> None:
    """An object linked to user management - person or person group - is no ConfigItem"""
    assert config_item_criteria() == {SYSTEM_REF_KEY: {'$exists': False}}


def test_every_call_answers_a_fresh_criteria() -> None:
    """A caller narrowing its criteria cannot change the next caller's"""
    first = config_item_criteria()
    first[SYSTEM_REF_KEY]['$exists'] = True

    assert config_item_criteria()[SYSTEM_REF_KEY] == {'$exists': False}
