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
The limits pylint enforces, read from the repository's .pylintrc

Read rather than copied, so a test that holds code to a limit follows a raised or lowered limit
"""
import configparser
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['REPO_ROOT', 'PYLINTRC', 'pylint_limit']

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
PYLINTRC: Path = REPO_ROOT / '.pylintrc'


def pylint_limit(option: str) -> int:
    """
    Reads one numeric limit from the repository's .pylintrc

    Args:
        option (str): The option's name, e.g. ``max-module-lines``

    Raises:
        StopIteration: When no section of the .pylintrc sets the option

    Returns:
        int: The limit
    """
    config = configparser.ConfigParser()
    config.read(PYLINTRC)

    return next(int(section[option]) for section in config.values() if option in section)
