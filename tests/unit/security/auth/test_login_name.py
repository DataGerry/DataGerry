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
Unit tests for cmdb.security.auth.login_name

Pure tests. Pins the two halves of the rule: what the Service Portal is sent (stripped, lower-cased)
and which CmdbUser lookups a login is tried with (stripped, as typed, then - on premise - lower-cased)
"""
import pytest

from cmdb.models.user_model import CmdbUserKey
from cmdb.security.auth.login_name import login_lookup_queries, normalize_login_email, strip_login
# -------------------------------------------------------------------------------------------------------------------- #

USER_NAME: str = CmdbUserKey.USER_NAME.value
EMAIL: str = CmdbUserKey.EMAIL.value


class TestStripLogin:
    """The whitespace around a login."""

    @pytest.mark.parametrize('login, expected', [
        (' admin ', 'admin'), ('admin\t\n', 'admin'), ('ad min', 'ad min'), ('admin', 'admin'),
    ], ids=['spaces', 'tab-newline', 'inner-space-kept', 'untouched'])
    def test_only_the_surrounding_whitespace_goes(self, login: str, expected: str) -> None:
        """Inside the login nothing changes"""
        assert strip_login(login) == expected


class TestNormalizeLoginEmail:
    """The spelling every cloud entry point sends the portal."""

    @pytest.mark.parametrize('email', ['Foo@Bar.com', ' foo@bar.com ', 'FOO@BAR.COM\t', 'foo@bar.com'])
    def test_one_address_one_spelling(self, email: str) -> None:
        """Every variant becomes the same string"""
        assert normalize_login_email(email) == 'foo@bar.com'


class TestLoginLookupQueries:
    """The CmdbUser lookups a login is tried with."""

    def test_on_premise_as_typed_then_lower_cased(self) -> None:
        """A user name is stored as it was created, so the typed form is tried first"""
        assert login_lookup_queries(' Admin ', cloud_mode=False) == [{USER_NAME: 'Admin'}, {USER_NAME: 'admin'}]

    def test_an_already_lower_case_name_is_one_lookup(self) -> None:
        """No second candidate to try"""
        assert login_lookup_queries('admin', cloud_mode=False) == [{USER_NAME: 'admin'}]

    def test_cloud_is_one_lookup_by_email_as_given(self) -> None:
        """The caller hands in the portal's address - the spelling the tenant user is stored under"""
        assert login_lookup_queries(' Foo@Bar.com ', cloud_mode=True) == [{EMAIL: 'Foo@Bar.com'}]
