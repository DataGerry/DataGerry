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
This file contains all helper methods for OpenCelium

Beside the tenant name mapping, `is_hosted_cloud` names the predicate the whole integration branches
on: OpenCelium is shared between tenants on a hosted installation - names are prefixed, connectors are
authenticated with a master password - while `--cloud --local` is a developer's own stack and behaves
like an on-premise one. It was spelled `current_app.cloud_mode and not current_app.local_mode` inline
in the managers and a dozen times in the OpenCelium routes
"""
from flask import current_app


def is_hosted_cloud() -> bool:
    """
    Reports whether this process serves a HOSTED cloud installation

    `--cloud --local` is a developer's local stack: cloud mode is on, but the OpenCelium instance is
    that developer's own, so nothing is shared and nothing is prefixed. Both flags are set at process
    start (see `cmdb/__init__.py`), so the answer cannot change within a request

    Returns:
        bool: True on a hosted cloud installation, False on-premise and in local cloud development
    """
    return bool(current_app.cloud_mode) and not bool(current_app.local_mode)


def map_oc_name(map_name: str, input_str: str) -> str:
    """
    Prefixes `input_str` with `map_name` so OpenCelium names are scoped to a tenant

    Args:
        map_name (str): the prefix the input is scoped with (e.g. the tenant database name)
        input_str (str): the original string

    Returns:
        str: the mapped string in the format `<map_name>_<input_str>`
    """
    return f"{map_name}_{input_str}"


def unmap_oc_name(mapped_str: str, strict: bool = True) -> str:
    """
    Reverses `map_oc_name`, stripping the leading `<map_name>_` prefix

    Only the first underscore is split on, so a value that itself contains underscores is restored
    intact (`'db_a_b'` -> `'a_b'`). This assumes the prefix carries no underscore.

    Args:
        mapped_str (str): the previously mapped string to unmap
        strict (bool): when True a string without an underscore is rejected; when False such a
            string is returned unchanged. Defaults to True

    Raises:
        ValueError: if `strict` is True and `mapped_str` contains no underscore "_"

    Returns:
        str: the unmapped string (the part after the first underscore)
    """
    if "_" not in mapped_str:
        if strict:
            raise ValueError(f"Invalid mapped string: {mapped_str!r}. It contains no underscore.")

        return mapped_str

    return mapped_str.split("_", 1)[1]
