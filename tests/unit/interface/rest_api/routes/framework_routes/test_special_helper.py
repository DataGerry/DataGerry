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
Unit tests for the special (DataGerry Assistant) route helper.

Covers has_framework_data: False only when every collection is empty, True as soon as one is
non-empty, and the short-circuit (later managers are not counted once an earlier one is non-empty);
and drop_locked_profiles, the license filter that keeps the assistant itself licensing-agnostic.

**The filter used to consult a hand-maintained profile -> feature map, and that map had one entry:
the RACK profile.** The IPAM profile - which creates the SpecialTypes the IPAM licence actually owns -
was missing from it, so an unlicensed on-premise installation could seed IPAM special types through
the assistant that `POST /types/` refuses with a 403. The requirement is now DERIVED from what a
profile creates, through the same `special_type_license_feature` the type routes use, and the tests
below pin that derivation rather than a list.

The filter is driven at the feature_locked seam rather than through a real license: the underlying
request_has_feature caches its answer per request on flask.g, which leaks across a session-scoped app
context and would make the licensed / unlicensed cases order-dependent.
"""
from unittest.mock import patch

import pytest

from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.framework.datagerry_assistant.profile_assistant import (
    PROFILE_BUILDERS,
    special_types_created_by,
)
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.framework_routes.special_helper import (
    drop_locked_profiles,
    has_framework_data,
    profile_license_feature,
)

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.special_helper'
# -------------------------------------------------------------------------------------------------------------------- #


class _CountingManager:
    """Minimal stand-in exposing count_documents() and recording how many times it was called."""

    def __init__(self, count: int) -> None:
        self._count = count
        self.calls = 0

    def count_documents(self) -> int:
        """Returns the configured count and records the call."""
        self.calls += 1
        return self._count


def test_returns_false_when_all_empty() -> None:
    """No categories, types, or objects -> False."""
    categories, types, objects = _CountingManager(0), _CountingManager(0), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is False
    # every collection had to be counted to conclude 'empty'
    assert (categories.calls, types.calls, objects.calls) == (1, 1, 1)


def test_true_when_categories_present_short_circuits() -> None:
    """A non-empty categories collection returns True without counting types/objects."""
    categories, types, objects = _CountingManager(1), _CountingManager(0), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is True
    assert (types.calls, objects.calls) == (0, 0)


def test_true_when_types_present_short_circuits() -> None:
    """A non-empty types collection returns True without counting objects."""
    categories, types, objects = _CountingManager(0), _CountingManager(2), _CountingManager(0)

    assert has_framework_data(categories, types, objects) is True
    assert objects.calls == 0


def test_true_when_objects_present() -> None:
    """A non-empty objects collection returns True."""
    categories, types, objects = _CountingManager(0), _CountingManager(0), _CountingManager(3)

    assert has_framework_data(categories, types, objects) is True


# -------------------------------------------------------------------------------------------------------------------- #
#                                              drop_locked_profiles                                                    #
# -------------------------------------------------------------------------------------------------------------------- #

@pytest.mark.parametrize('profile', [ProfileName.IPAM.value, ProfileName.RACK.value])
def test_a_profile_creating_a_gated_special_type_requires_its_feature(profile: str) -> None:
    """
    Both profiles that build licence-gated SpecialTypes require the licence

    The IPAM one is the regression: it creates the SpecialTypes the IPAM licence owns and was absent
    from the map this replaced, so the assistant seeded them on an unlicensed installation while
    `POST /types/` answered 403 for the very same markers.
    """
    assert profile_license_feature(profile) == LicenseFeature.IPAM


@pytest.mark.parametrize('profile', [
    ProfileName.LOCATION.value,
    ProfileName.USER_MANAGEMENT.value,
    ProfileName.CLIENT_MANAGEMENT.value,
])
def test_a_profile_creating_no_gated_special_type_needs_no_feature(profile: str) -> None:
    """Community profiles must stay seedable without a licence."""
    assert profile_license_feature(profile) is None


def test_an_unknown_profile_needs_no_feature() -> None:
    """A name the assistant does not know creates nothing, so it gates nothing."""
    assert profile_license_feature('not-a-profile') is None


def test_every_profile_building_a_gated_special_type_is_gated() -> None:
    """
    The property the derivation buys, checked across every profile rather than a list of two

    A new profile that creates a licence-gated SpecialType is covered the moment it declares what it
    builds - which is what the hand-maintained map could not do, and how the IPAM profile came to be
    missing from it.
    """
    for name, _builder in PROFILE_BUILDERS:
        created = special_types_created_by(name.value)
        gated = any(SpecialType.is_license_gated(special_type) for special_type in created)

        assert (profile_license_feature(name.value) is not None) == gated


def test_the_declaration_matches_what_the_ipam_profile_builds() -> None:
    """Declared from the definition list the profile iterates, so it cannot fall behind it."""
    from cmdb.framework.datagerry_assistant.datagerry_assistant_constants import (
        IPAM_SPECIAL_TYPE_DEFINITIONS,
        IpamSpecialTypeKey,
    )

    built = {definition[IpamSpecialTypeKey.SPECIAL_TYPE] for definition in IPAM_SPECIAL_TYPE_DEFINITIONS}

    assert special_types_created_by(ProfileName.IPAM.value) == built


@pytest.mark.parametrize('profile', [ProfileName.IPAM.value, ProfileName.RACK.value])
def test_drops_a_gated_profile_when_its_feature_is_locked(profile: str) -> None:
    """The assistant writes through the managers, so a locked profile is filtered before it runs."""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=True):
        assert drop_locked_profiles([profile], None) == []


def test_keeps_the_ungated_profiles_when_a_gated_one_is_dropped() -> None:
    """One locked profile must not discard the rest - the assistant only ever runs once."""
    selected = [ProfileName.LOCATION.value, ProfileName.RACK.value, ProfileName.IPAM.value]

    with patch(f'{HELPER_PATH}.feature_locked', return_value=True):
        remaining = drop_locked_profiles(selected, None)

    assert remaining == [ProfileName.LOCATION.value]


@pytest.mark.parametrize('profile', [ProfileName.IPAM.value, ProfileName.RACK.value])
def test_keeps_a_gated_profile_when_its_feature_is_unlocked(profile: str) -> None:
    """With the feature available the profile is seeded as normal."""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=False):
        assert drop_locked_profiles([profile], None) == [profile]


def test_the_order_of_the_selection_is_preserved() -> None:
    """The filter removes, it does not reorder - the assistant has its own fixed build order."""
    selected = [ProfileName.CLIENT_MANAGEMENT.value, ProfileName.LOCATION.value]

    with patch(f'{HELPER_PATH}.feature_locked', return_value=True):
        assert drop_locked_profiles(selected, None) == selected


def test_ungated_profiles_never_consult_the_license() -> None:
    """A profile absent from the map is always available - no license lookup for it at all"""
    ungated = [ProfileName.LOCATION.value, ProfileName.USER_MANAGEMENT.value]

    with patch(f'{HELPER_PATH}.feature_locked') as guard:
        remaining = drop_locked_profiles(ungated, None)

    assert remaining == ungated
    guard.assert_not_called()


def test_only_the_gated_profiles_feature_is_looked_up() -> None:
    """The lookup asks for the profile's own feature, not a blanket one"""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=False) as guard:
        drop_locked_profiles([ProfileName.LOCATION.value, ProfileName.RACK.value], None)

    guard.assert_called_once_with(LicenseFeature.IPAM, None)
