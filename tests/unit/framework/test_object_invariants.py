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
Unit tests for cmdb.framework.object_invariants

The merged write-invariant entry point both object write paths call. Asserts every feature's
validators run, that each feature's errors keep that feature's own abort wording (a Rack problem must
not be reported under the IPAM feature's name), that both messages survive when two features reject
the same candidate, and that a valid candidate yields None so the caller does not abort
"""
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.utils.validation_error import ValidationErrorKey
from cmdb.framework.object_invariants import enforce_object_write_invariants
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.object_invariants'

CANDIDATE: dict[str, Any] = {'type_id': 7, 'fields': []}
PREVIOUS: dict[str, Any] = {'type_id': 7, 'fields': [], 'public_id': 3}


def _error(message: str) -> dict[str, Any]:
    """Builds a structured validation error carrying the given message"""
    return {ValidationErrorKey.MESSAGE.value: message}

# -------------------------------------------------------------------------------------------------------------------- #


def test_returns_none_when_every_feature_is_satisfied() -> None:
    """A valid candidate yields None, so the caller never aborts"""
    with patch(f'{PATH}.enforce_object_invariants', return_value=[]), \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[]):
        assert enforce_object_write_invariants(MagicMock(), MagicMock(), CANDIDATE) is None


def test_runs_every_feature_validator() -> None:
    """Both features are consulted on every write, not just the first one that matches"""
    with patch(f'{PATH}.enforce_object_invariants', return_value=[]) as ipam, \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[]) as rack:
        enforce_object_write_invariants(MagicMock(), MagicMock(), CANDIDATE)

    ipam.assert_called_once()
    rack.assert_called_once()


def test_passes_the_previous_object_to_the_ipam_validators() -> None:
    """The IPAM update rules compare against the pre-edit document, so it must be forwarded"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(f'{PATH}.enforce_object_invariants', return_value=[]) as ipam, \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[]):
        enforce_object_write_invariants(objects_manager, types_manager, CANDIDATE, previous_object=PREVIOUS)

    ipam.assert_called_once_with(objects_manager, types_manager, CANDIDATE, previous_object=PREVIOUS)


def test_ipam_errors_keep_the_ipam_wording() -> None:
    """An IPAM rejection is reported under the IPAM feature's name, unchanged from before"""
    with patch(f'{PATH}.enforce_object_invariants', return_value=[_error('bad cidr')]), \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[]):
        message = enforce_object_write_invariants(MagicMock(), MagicMock(), CANDIDATE)

    assert message == 'IPAM validation failed: bad cidr'


def test_rack_errors_keep_the_rack_wording() -> None:
    """A Rack rejection must not be labelled as an IPAM failure"""
    with patch(f'{PATH}.enforce_object_invariants', return_value=[]), \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[_error('bad height')]):
        message = enforce_object_write_invariants(MagicMock(), MagicMock(), CANDIDATE)

    assert message == 'Rack validation failed: bad height'
    assert 'IPAM' not in message


def test_both_features_rejecting_yields_both_messages() -> None:
    """
    A Rack type carrying dg-ipam-interface rows can trip both feature's rules at once

    Each half keeps its own prefix so the user can tell which feature complained about what.
    """
    with patch(f'{PATH}.enforce_object_invariants', return_value=[_error('bad cidr')]), \
         patch(f'{PATH}.enforce_rack_object_invariants', return_value=[_error('bad height')]):
        message = enforce_object_write_invariants(MagicMock(), MagicMock(), CANDIDATE)

    assert 'IPAM validation failed: bad cidr' in message
    assert 'Rack validation failed: bad height' in message
