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
Integration test for KeyHolder on-premise RSA key retrieval.

Read-only against the 'security' settings section: the RSA keypair is seeded during session setup, so
this asserts the non-cloud branch returns the stored keys. The autouse app_context fixture provides a
non-cloud current_app.
"""
from cmdb.security.key.holder import KeyHolder
# -------------------------------------------------------------------------------------------------------------------- #


def test_loads_stored_rsa_keys(database_manager) -> None:
    """Constructing a KeyHolder on-premise loads the stored public/private keys from settings."""
    key_holder = KeyHolder(database_manager)

    assert key_holder.rsa_public
    assert key_holder.rsa_private
    assert key_holder.get_public_key() == key_holder.rsa_public
    assert key_holder.get_private_key() == key_holder.rsa_private
