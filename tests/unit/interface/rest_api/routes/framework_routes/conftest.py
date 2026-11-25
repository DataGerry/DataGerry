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
Shared fixtures of these unit tests: the access engine's own reads (an object write's ``can()``, a Type answer's
``allowed_operations``) see no assignment and need no database - access is not these tests' subject
"""
import pytest

from tests.utils.type_acl_engine_stub import decide_without_assignments
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def fixture_no_assignments(monkeypatch: pytest.MonkeyPatch) -> None:
    """No assignment restricts a Type: every operation allowed, every field writable"""
    decide_without_assignments(monkeypatch)
