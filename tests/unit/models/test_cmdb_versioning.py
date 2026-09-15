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
Unit tests for cmdb.models.cmdb_versioning.Versioning

Pure tests: no Mongo, no Flask. The value object behind every CmdbObject's and CmdbType's version
string, and until this sweep no test module named it.

What is pinned here is semantic versioning itself, because the class did not implement it: a minor
bump left the patch component alone - against what its own docstring promised - and a major bump left
both. A series of edits therefore produced strings like 1.5.7, where the patch count belonged to a
minor version two releases old
"""
import pytest

from cmdb.models.cmdb_versioning import Versioning
from cmdb.errors.cmdb_object import VersionTypeError
# -------------------------------------------------------------------------------------------------------------------- #


class TestTheSemverResets:
    """The rule the class is named after."""

    def test_a_major_bump_starts_a_new_line(self) -> None:
        """
        1.2.3 becomes 2.0.0

        A major release replaces the line, so carrying its minor and patch forward described changes
        that no longer exist.
        """
        version = Versioning(1, 2, 3)

        version.update_major()

        assert repr(version) == '2.0.0'

    def test_a_minor_bump_resets_the_patch(self) -> None:
        """
        1.2.3 becomes 1.3.0 - which is what the docstring always claimed and the code never did
        """
        version = Versioning(1, 2, 3)

        version.update_minor()

        assert repr(version) == '1.3.0'

    def test_a_patch_bump_touches_only_the_patch(self) -> None:
        """The one bump that was already right."""
        version = Versioning(1, 2, 3)

        version.update_patch()

        assert repr(version) == '1.2.4'

    def test_each_bump_returns_its_own_component(self) -> None:
        """The return value is the component that moved, not the whole version."""
        assert Versioning(1, 2, 3).update_major() == 2
        assert Versioning(1, 2, 3).update_minor() == 3
        assert Versioning(1, 2, 3).update_patch() == 4

    def test_repeated_minor_bumps_do_not_accumulate_patches(self) -> None:
        """
        The visible symptom: two edits after a patch used to read 1.4.7 instead of 1.4.0

        Asserted as a sequence because that is how a real object's version moves.
        """
        version = Versioning(1, 0, 0)

        version.update_patch()
        version.update_patch()
        version.update_minor()

        assert repr(version) == '1.1.0'


class TestTheComponents:
    """The three setters, which are the class's only validation."""

    def test_the_default_version_is_the_first_release(self) -> None:
        """Every model's DEFAULT_VERSION is this same 1.0.0."""
        assert repr(Versioning()) == '1.0.0'

    @pytest.mark.parametrize('component', ['major', 'minor', 'patch'])
    def test_a_non_integer_component_is_refused(self, component: str) -> None:
        """
        A version is three integers; anything else would render into a string nothing can parse back

        Which matters because CmdbDAO.update_version parses the stored string to bump it.
        """
        with pytest.raises(VersionTypeError):
            Versioning(**{component: '1'})

    @pytest.mark.parametrize('component', ['major', 'minor', 'patch'])
    def test_a_component_can_be_read_back(self, component: str) -> None:
        """The properties are what the setters guard, so the round trip is worth pinning."""
        version = Versioning(4, 5, 6)

        assert getattr(version, component) == {'major': 4, 'minor': 5, 'patch': 6}[component]

    def test_assigning_a_bad_component_after_construction_is_refused_too(self) -> None:
        """The guard is on the setter, not only on the constructor."""
        version = Versioning(1, 0, 0)

        with pytest.raises(VersionTypeError):
            version.minor = 1.5

    def test_the_string_form_is_the_stored_form(self) -> None:
        """repr() is what update_version writes back onto the model, so it IS the wire format."""
        assert repr(Versioning(10, 20, 30)) == '10.20.30'
