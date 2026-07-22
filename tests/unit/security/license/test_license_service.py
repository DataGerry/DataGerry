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
Unit tests for LicenseService orchestration

Isolates the service's own logic from the crypto by stubbing the active-license store and
monkeypatching verify_license: no stored license runs on the free default, a VALID result exposes
its tier/feature, a failure degrades to free, and activate() stores only when valid while
deactivate() clears. The verification chain itself is covered at the P11 tier
"""
from typing import Optional
from unittest.mock import MagicMock

import pytest

from cmdb.manager.license_manager import license_service as svc_module
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import (
    LicenseFeature,
    LicenseTier,
    LicenseVerificationStatus,
)
from cmdb.security.license.verification import LicenseVerificationResult
# -------------------------------------------------------------------------------------------------------------------- #

STORED_BLOB: str = 'stored-blob'


class _StubActiveLicense:
    """Stub active-license store recording set/clear and returning a fixed blob"""

    def __init__(self, blob: Optional[str] = None) -> None:
        self.blob = blob
        self.stored: Optional[str] = None
        self.cleared = False

    def get_active_license_blob(self) -> Optional[str]:
        """Returns the configured stored blob"""
        return self.blob

    def set_active_license(self, blob: str) -> None:
        """Records the stored blob"""
        self.stored = blob

    def clear_active_license(self) -> bool:
        """Records the clear and reports success"""
        self.cleared = True
        return True


def _service(blob: Optional[str]) -> LicenseService:
    """A LicenseService whose active-license store returns the given blob"""
    service = LicenseService(MagicMock())
    service.active_license_manager = _StubActiveLicense(blob)
    return service


def _patch_verify(monkeypatch: pytest.MonkeyPatch, result: LicenseVerificationResult) -> None:
    """Makes verify_license return a fixed result regardless of input"""
    monkeypatch.setattr(svc_module, 'verify_license', lambda *args, **kwargs: result)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          no stored license                                                          #
# -------------------------------------------------------------------------------------------------------------------- #
def test_no_license_runs_on_free_default() -> None:
    """With nothing stored the service reports the free tier and is not active"""
    service = _service(None)

    assert service.current_tier() == LicenseTier.FREE.value
    assert service.is_active() is False
    assert service.current_status() is None
    assert service.has_feature(LicenseFeature.IPAM) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                          valid stored license                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_valid_license_exposes_tier_and_features(monkeypatch: pytest.MonkeyPatch) -> None:
    """A VALID verification exposes its entitlement's tier and the features it lists"""
    entitlement = LicenseEntitlement(
        hmac='bind',
        license_type=LicenseTier.BUSINESS.value,
        features=[LicenseFeature.ISMS.value, LicenseFeature.IPAM.value],
    )
    _patch_verify(monkeypatch, LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement))
    service = _service(STORED_BLOB)

    assert service.is_active() is True
    assert service.current_status() == LicenseVerificationStatus.VALID
    assert service.current_tier() == LicenseTier.BUSINESS.value
    assert service.has_feature(LicenseFeature.ISMS) is True
    assert service.has_feature(LicenseFeature.IPAM) is True
    assert service.has_feature(LicenseFeature.AUTOMATIONS) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                          invalid stored license                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_invalid_license_degrades_to_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed verification degrades to free while still reporting the failure status"""
    _patch_verify(monkeypatch, LicenseVerificationResult(LicenseVerificationStatus.EXPIRED))
    service = _service(STORED_BLOB)

    assert service.current_tier() == LicenseTier.FREE.value
    assert service.is_active() is False
    assert service.current_status() == LicenseVerificationStatus.EXPIRED
    assert service.has_feature(LicenseFeature.IPAM) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                          activate / deactivate                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_activate_stores_only_when_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """activate stores the blob when verification is VALID"""
    entitlement = LicenseEntitlement(hmac='bind', license_type=LicenseTier.CORE.value)
    _patch_verify(monkeypatch, LicenseVerificationResult(LicenseVerificationStatus.VALID, entitlement))
    service = _service(None)

    result = service.activate('new-blob')

    assert result.is_valid is True
    assert service.active_license_manager.stored == 'new-blob'


def test_activate_does_not_store_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """activate does not store the blob when verification fails"""
    _patch_verify(monkeypatch, LicenseVerificationResult(LicenseVerificationStatus.BINDING_MISMATCH))
    service = _service(None)

    result = service.activate('bad-blob')

    assert result.status == LicenseVerificationStatus.BINDING_MISMATCH
    assert service.active_license_manager.stored is None


def test_deactivate_clears_the_store() -> None:
    """deactivate clears the stored license"""
    service = _service(STORED_BLOB)

    assert service.deactivate() is True
    assert service.active_license_manager.cleared is True

