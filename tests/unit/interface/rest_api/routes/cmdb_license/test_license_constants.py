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
Unit tests for the license route constants: every way a license can fail verification has its own message
"""
from cmdb.security.license.license_constants import LicenseVerificationStatus
from cmdb.interface.rest_api.routes.cmdb_license.license_constants import LICENSE_ACTIVATION_REFUSALS
# -------------------------------------------------------------------------------------------------------------------- #


def test_every_failure_status_has_a_message_and_success_has_none() -> None:
    """A status added to the verification later must get its message here too"""
    failures: set[LicenseVerificationStatus] = set(LicenseVerificationStatus) - {LicenseVerificationStatus.VALID}

    assert set(LICENSE_ACTIVATION_REFUSALS) == failures


# A status value that reads as a code, not as a word (``expired`` is both)
CODE_SEPARATOR: str = '_'


def test_no_message_leaks_a_status_code() -> None:
    """The messages are sentences for the user, not the verification's codes"""
    codes: list[str] = [status.value for status in LicenseVerificationStatus if CODE_SEPARATOR in status.value]

    for message in LICENSE_ACTIVATION_REFUSALS.values():
        assert not any(code in message for code in codes)
        assert 'status:' not in message
        assert message.endswith('.')
