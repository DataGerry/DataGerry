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

The filter is driven at the feature_locked seam rather than through a real license: the underlying
request_has_feature caches its answer per request on flask.g, which leaks across a session-scoped app
context and would make the licensed / unlicensed cases order-dependent.
"""
from unittest.mock import patch

from cmdb.framework.datagerry_assistant.profile_name import ProfileName
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.framework_routes.special_helper import (
    PROFILE_LICENSE_FEATURES,
    drop_locked_profiles,
    has_framework_data,
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

def test_the_rack_profile_is_the_only_gated_profile_and_maps_to_ipam() -> None:
    """The interim policy, pinned: Rack View is gated behind IPAM and nothing else is gated"""
    assert PROFILE_LICENSE_FEATURES == {ProfileName.RACK.value: LicenseFeature.IPAM}


def test_drops_the_rack_profile_when_its_feature_is_locked() -> None:
    """The assistant writes through the managers, so the locked profile is filtered before it runs"""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=True):
        remaining = drop_locked_profiles([ProfileName.RACK.value], None)

    assert remaining == []


def test_keeps_the_other_profiles_when_the_rack_profile_is_dropped() -> None:
    """One locked profile must not discard the rest - the assistant only ever runs once"""
    selected = [ProfileName.LOCATION.value, ProfileName.RACK.value, ProfileName.IPAM.value]

    with patch(f'{HELPER_PATH}.feature_locked', return_value=True):
        remaining = drop_locked_profiles(selected, None)

    assert remaining == [ProfileName.LOCATION.value, ProfileName.IPAM.value]


def test_keeps_the_rack_profile_when_its_feature_is_unlocked() -> None:
    """With the feature available the profile is seeded as normal"""
    with patch(f'{HELPER_PATH}.feature_locked', return_value=False):
        remaining = drop_locked_profiles([ProfileName.RACK.value], None)

    assert remaining == [ProfileName.RACK.value]


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
