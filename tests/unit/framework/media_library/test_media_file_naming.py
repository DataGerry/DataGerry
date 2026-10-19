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
Unit tests for cmdb.framework.media_library.media_file_naming

first_free_name - the name itself when free, else the first free ``copy_(n)_<name>``, never a stacked prefix.
replacement_staging_name - a prefix carrying the replacement's own public_id, so two replacements never clash.
"""
import pytest

from cmdb.framework.media_library import first_free_name, replacement_staging_name
# -------------------------------------------------------------------------------------------------------------------- #

NAME: str = 'file.txt'
PUBLIC_ID: int = 42


class TestFirstFreeName:
    """The name, or the first copy_(n)_ the folder does not hold"""

    def test_a_free_name_is_kept(self) -> None:
        """Nothing else carries it"""
        assert first_free_name(NAME, {'other.txt'}) == NAME

    def test_a_taken_name_becomes_the_first_copy(self) -> None:
        """copy_(1)_ when only the name is taken"""
        assert first_free_name(NAME, {NAME}) == f'copy_(1)_{NAME}'

    @pytest.mark.parametrize('copies, expected', [(1, 2), (3, 4)])
    def test_taken_copies_are_skipped(self, copies: int, expected: int) -> None:
        """The first index the folder does not hold"""
        taken = {NAME} | {f'copy_({index})_{NAME}' for index in range(1, copies + 1)}

        assert first_free_name(NAME, taken) == f'copy_({expected})_{NAME}'

    def test_a_gap_is_filled(self) -> None:
        """copy_(1)_ is free again although copy_(2)_ is taken"""
        assert first_free_name(NAME, {NAME, f'copy_(2)_{NAME}'}) == f'copy_(1)_{NAME}'

    def test_the_prefix_is_never_stacked(self) -> None:
        """copy_(2)_<name>, not copy_(2)_copy_(1)_<name>"""
        assert first_free_name(NAME, {NAME, f'copy_(1)_{NAME}'}) == f'copy_(2)_{NAME}'


def test_the_staging_name_carries_the_public_id() -> None:
    """replacing_(<id>)_<name>"""
    assert replacement_staging_name(NAME, PUBLIC_ID) == f'replacing_({PUBLIC_ID})_{NAME}'


def test_two_replacements_of_one_name_never_clash() -> None:
    """Their public_ids differ, so their staging names do"""
    assert replacement_staging_name(NAME, PUBLIC_ID) != replacement_staging_name(NAME, PUBLIC_ID + 1)
