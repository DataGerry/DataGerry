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
Unit tests for cmdb.models.right_model.base_right

Pure: no Mongo, no Flask. `BaseRight` is the only node type of the static rights tree. What it has to keep is the
name/label contract: `__init__` prefixes the caller's name with the subclass PREFIX, and those qualified names are
what CmdbUserGroup stores and what `APIBlueprint.protect(right=...)` names, so the prefixing is part of the
authorisation contract and not presentation. A right carries no level: it is a name, a label and a description
"""
from typing import Any

import pytest

from cmdb.models.right_model.base_right import BaseRight
from cmdb.models.right_model.right_constants import GLOBAL_RIGHT_IDENTIFIER
# -------------------------------------------------------------------------------------------------------------------- #

RIGHT_NAME: str = 'view'
CUSTOM_LABEL: str = 'A custom label'
DESCRIPTION: str = 'View something'

# A PREFIX with several segments, as every real subclass has (e.g. base.framework.object)
NESTED_PREFIX: str = 'base.framework.object'

UNKNOWN_ATTRIBUTE: str = 'not_an_attribute'
RETIRED_LEVEL_KEY: str = 'level'


class NestedRight(BaseRight):
    """A right whose PREFIX has several segments, like every real domain right."""
    PREFIX = NESTED_PREFIX


class TestNameAndLabel:
    """Tests for the qualified name, the generated label and the master flag"""

    def test_name_is_prefixed(self) -> None:
        """The stored name is PREFIX + '.' + the given name."""
        assert NestedRight(RIGHT_NAME).name == f'{NESTED_PREFIX}.{RIGHT_NAME}'

    def test_label_is_generated_from_the_last_prefix_segment(self) -> None:
        """A generated label joins the last PREFIX segment with the last name segment."""
        assert NestedRight(RIGHT_NAME).label == f'object.{RIGHT_NAME}'

    def test_explicit_label_wins(self) -> None:
        """A label passed in is kept verbatim."""
        assert NestedRight(RIGHT_NAME, label=CUSTOM_LABEL).label == CUSTOM_LABEL

    def test_the_description_is_kept(self) -> None:
        """As given"""
        assert NestedRight(RIGHT_NAME, description=DESCRIPTION).description == DESCRIPTION

    def test_get_prefix_returns_the_last_segment(self) -> None:
        """get_prefix is the last dotted segment of PREFIX."""
        assert NestedRight(RIGHT_NAME).get_prefix() == 'object'
        assert BaseRight(RIGHT_NAME).get_prefix() == 'base'

    def test_wildcard_name_is_master(self) -> None:
        """The '*' right of a branch is flagged as a master right."""
        assert NestedRight(GLOBAL_RIGHT_IDENTIFIER).is_master is True

    def test_ordinary_name_is_not_master(self) -> None:
        """Any other right is not a master right."""
        assert NestedRight(RIGHT_NAME).is_master is False

    def test_a_right_carries_no_level(self) -> None:
        """The security level is gone - nothing about a right but its name decides what it grants"""
        assert not hasattr(NestedRight(RIGHT_NAME), RETIRED_LEVEL_KEY)


class TestItemAccess:
    """Tests for BaseRight.__getitem__, the mechanism RightsManager sorts through"""

    def test_reads_an_attribute_by_name(self) -> None:
        """Dictionary-style access returns the attribute value."""
        right = NestedRight(RIGHT_NAME, description=DESCRIPTION)

        assert right['name'] == f'{NESTED_PREFIX}.{RIGHT_NAME}'
        assert right['description'] == DESCRIPTION

    @pytest.mark.parametrize('item', [UNKNOWN_ATTRIBUTE, RETIRED_LEVEL_KEY])
    def test_unknown_attribute_raises_attribute_error(self, item: str) -> None:
        """An unknown key raises AttributeError - what an unknown ?sort= value produces."""
        with pytest.raises(AttributeError):
            NestedRight(RIGHT_NAME)[item]  # pylint: disable=expression-not-assigned


class TestToDict:
    """Tests for BaseRight.to_dict, the serialiser every rights response goes through"""

    def test_carries_every_field(self) -> None:
        """to_dict exposes exactly the four documented keys with the instance's values."""
        right = NestedRight(RIGHT_NAME, description=DESCRIPTION)
        result: dict[str, Any] = BaseRight.to_dict(right)

        assert result == {
            'name': f'{NESTED_PREFIX}.{RIGHT_NAME}',
            'label': f'object.{RIGHT_NAME}',
            'description': DESCRIPTION,
            'is_master': False,
        }

    def test_description_defaults_to_none(self) -> None:
        """A right created without a description serialises it as None."""
        assert BaseRight.to_dict(BaseRight(RIGHT_NAME))['description'] is None
