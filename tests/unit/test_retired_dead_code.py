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
Members removed on 2026-09-14 because nothing called them

The coverage gap table had shrunk to 48 files missing one to three statements each. Checking callers
before writing tests for them turned up eight methods with **no caller anywhere** - not in `cmdb/`,
not in `tests/`, and not through `getattr`. They were removed rather than covered.

Asserted here, as `test_type_reference.py::TestTheRetiredMembers` does for the 2026-09-10 batch, so a
future caller writes what it needs instead of resurrecting a default nobody checked. Two of the eight
were actively wrong, which is fair evidence they were never called:

* `TypeMultiDataSection.get_hidden_fields` returned `self.fields` - **every** field, byte-identical
  to `get_fields()` one method above it
* `CmdbSectionTemplate.to_data` carried a `TODO: check fields if correct` and subscripted
  `instance['public_id']` on a parameter annotated `"CmdbSectionTemplate"`, i.e. a `TypeError` for
  anything but a dict

Two more had been looked at by earlier sweeps and deliberately left as "trivial one-liners outside
the scope" (`test_profile_base.py`, `test_chatgpt_client.py`). That judgement was about how much a
test would be worth; neither sweep checked whether the methods had callers.
"""
import pytest

from cmdb.framework.datagerry_assistant.profile_base import ProfileBase
from cmdb.framework.docapi.docapi_template.docapi_template_base import TemplateManagementBase
from cmdb.interface.rest_api.routes.ai_routes.chatgpt_client import ChatGptClient
from cmdb.models.category_model.category_meta import CategoryMeta
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.type_model.type_multi_data_section import TypeMultiDataSection
from cmdb.models.type_model.type_summary import TypeSummary
from cmdb.security.auth.base_authentication_provider import BaseAuthenticationProvider
# -------------------------------------------------------------------------------------------------------------------- #

RETIRED: list[tuple[type, str]] = [
    (ProfileBase, 'get_created_type_ids'),
    (TemplateManagementBase, 'to_database'),
    (ChatGptClient, 'get_client'),
    (CategoryMeta, 'has_icon'),
    (CmdbSectionTemplate, 'to_data'),
    (TypeMultiDataSection, 'get_hidden_fields'),
    (TypeSummary, 'set_fields'),
    (BaseAuthenticationProvider, 'is_password_able'),
]


class TestTheRetiredMembers:
    """Eight methods had no caller anywhere and were removed on 2026-09-14."""

    @pytest.mark.parametrize('owner, member', RETIRED, ids=lambda arg: arg if isinstance(arg, str) else arg.__name__)
    def test_they_are_gone(self, owner: type, member: str) -> None:
        """A caller that needs one of these should write what it needs, not restore the old body."""
        assert not hasattr(owner, member)


class TestWhatTheyReadIsStillReachable:
    """Removing an accessor must not remove the state behind it."""

    def test_the_profile_slot_map_is_still_an_attribute(self) -> None:
        """`get_created_type_ids` was a plain read of this; profile code uses the attribute."""
        assert 'created_type_ids' in ProfileBase.__init__.__code__.co_names

    def test_a_category_meta_still_carries_its_icon(self) -> None:
        """`has_icon` was `bool(self.icon)`; the icon itself is part of the payload."""
        assert CategoryMeta(icon='fa-cube').icon == 'fa-cube'

    def test_a_type_summary_still_exposes_its_fields(self) -> None:
        """`set_fields` was the only writer; the list is read through `has_fields` and `to_json`."""
        summary = TypeSummary(fields=['a', 'b'])

        assert summary.has_fields() is True
        assert TypeSummary.to_json(summary) == {'fields': ['a', 'b']}

    def test_the_mds_section_still_reports_its_fields_once(self) -> None:
        """`get_fields` is the surviving reader - `get_hidden_fields` returned the same list."""
        section = TypeMultiDataSection(type='multi-data-section', name='s', label='S', fields=['f'])

        assert section.get_fields() == ['f']


class TestPasswordAbleFoundItsReader:
    """
    `PASSWORD_ABLE` outlived its accessor, and was wired on 2026-09-21

    `is_password_able` was removed with the rest above because nothing called it - but the flag was
    KEPT, on the grounds that the LDAP provider's deliberate override was evidence somebody meant it
    to do something. It now means: DataGerry owns this provider's users' passwords. The reader is
    `AuthModule.provider_owns_passwords`, and the password-change route refuses a user whose
    directory owns the credentials (see tests/functional/management/test_functional_users_route.py).
    """

    def test_the_accessor_stayed_removed(self) -> None:
        """Wiring the flag did not resurrect the one-line accessor - callers read the flag."""
        assert not hasattr(BaseAuthenticationProvider, 'is_password_able')

    def test_the_flag_survives_on_the_base(self) -> None:
        """True by default: a provider that says nothing owns its users' passwords locally."""
        assert BaseAuthenticationProvider.PASSWORD_ABLE is True

    def test_the_ldap_provider_still_overrides_it(self) -> None:
        """The override is the rule now - the directory owns those passwords, not DataGerry."""
        from cmdb.security.auth.providers.ldap_auth_provider import (  # pylint: disable=import-outside-toplevel
            LdapAuthenticationProvider,
        )

        assert LdapAuthenticationProvider.PASSWORD_ABLE is False

    def test_it_is_read_through_the_auth_module(self) -> None:
        """The flag is no longer dead state: one lookup answers it for a stored `authenticator`."""
        from cmdb.security.auth.auth_module import AuthModule  # pylint: disable=import-outside-toplevel

        assert AuthModule.provider_owns_passwords('LdapAuthenticationProvider') is False
