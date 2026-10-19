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
The names the media library gives an entry itself, rather than taking the one it was sent

Two cases, both forced by the unique index over (filename, metadata.parent):

* a renamed entry whose name another entry of its folder already carries becomes the first free
  ``copy_(n)_<name>`` (``first_free_name``)
* the replacement written by an upload over an existing entry is stored under a name of its own first
  (``replacement_staging_name``), because the entry it replaces still holds the real name until it is removed

Pure functions: the caller reads what the folder holds
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'COPY_PREFIX_TEMPLATE',
    'REPLACEMENT_PREFIX_TEMPLATE',
    'first_free_name',
    'replacement_staging_name',
]

# The prefix a clashing name is given, the n-th copy of it
COPY_PREFIX_TEMPLATE: str = 'copy_({index})_'

# The prefix a replacement carries while the entry it replaces still holds the name. The replacement's own
# public_id makes it unique, so two replacements of one entry never clash with each other
REPLACEMENT_PREFIX_TEMPLATE: str = 'replacing_({public_id})_'


def first_free_name(name: str, taken: set[str]) -> str:
    """
    Builds the first of ``name``, ``copy_(1)_<name>``, ``copy_(2)_<name>``, ... the folder does not hold

    The previous prefix is stripped before the next one is applied, so the n-th candidate is
    ``copy_(n)_<name>`` and never ``copy_(2)_copy_(1)_<name>``

    Args:
        name (str): The name the entry asks for
        taken (set[str]): The names the other entries of the folder carry

    Returns:
        str: A name no other entry of the folder carries
    """
    index: int = 0
    candidate: str = name

    while candidate in taken:
        index += 1
        stripped: str = candidate.replace(COPY_PREFIX_TEMPLATE.format(index=index - 1), '')
        candidate = f'{COPY_PREFIX_TEMPLATE.format(index=index)}{stripped}'

    return candidate


def replacement_staging_name(name: str, public_id: int) -> str:
    """
    The name a replacement is stored under until the entry it replaces is gone

    Args:
        name (str): The name the replacement will carry in the end
        public_id (int): The replacement's own public_id

    Returns:
        str: E.g. ``replacing_(42)_report.pdf``
    """
    return f'{REPLACEMENT_PREFIX_TEMPLATE.format(public_id=public_id)}{name}'
