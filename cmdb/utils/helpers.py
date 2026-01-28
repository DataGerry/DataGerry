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
Collection of different helper classes and functions
"""
import re
import sys
import importlib
import inspect
import logging
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER = logging.getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #

def load_class(classname):
    """ load and return the class with the given classname """
    # extract class from module
    pattern = re.compile(r"(.*)\.(.*)")
    match = pattern.fullmatch(classname)

    if match is None:
        raise Exception(f"Could not load class {classname}")

    module_name = match.group(1)
    class_name = match.group(2)
    loaded_module = importlib.import_module(module_name)
    loaded_class = getattr(loaded_module, class_name)

    return loaded_class


def get_module_classes(module_name):
    """Get all class of an module and return list of classes"""
    class_list = []
    loaded_module = importlib.import_module(module_name)

    for key, data in inspect.getmembers(loaded_module, inspect.isclass):
        if module_name in str(data):
            class_list.append(key)

    return class_list


def str_to_bool(s: Any) -> bool:
    """
    Converts a string or boolean value to a corresponding boolean

    Args:
        s (str or bool): The input value to be converted. This can be:
            - A string, which is either 'True', 'true', 'False', 'false' (case-insensitive)
            - A boolean value (`True` or `False`)

    Returns:
        bool: `True` or `False` depending on the input value

    Raises:
        ValueError: If the input is not a valid boolean string or boolean value
    """
    # Check if input is a string and convert based on known truthy or falsy values
    if isinstance(s, str):
        s = s.strip().lower()
        if s == 'true':
            return True
        if s == 'false':
            return False

    # Check if input is already a boolean
    if isinstance(s, bool):
        return s

    # If input is not a valid string or boolean, raise an error
    raise ValueError("Invalid value for conversion to boolean")


def process_bar(name, total, progress):
    """
    Displays or updates a console progress bar to visualize the progress of a task.

    Args:
        name (str): The name of the process being tracked.
        total (int): The total number of steps or tasks to complete.
        progress (int): The current progress (steps or tasks completed).

    Example:
        >>> process_bar('Task', 100, 45)
        Task:[####################--------------------] 45%   [45/100]
    """
    # Ensure progress is a float for accurate calculation and prevent division by zero
    progress = float(progress) / float(total)

    # Set progress to 1 when it's equal to or greater than the total
    if progress >= 1.0:
        progress = 1.0
        status = "\r\n"  # New line after completion
    else:
        status = ""  # Keep same line for progress

    # Define the bar's length and calculate the number of blocks
    bar_length = 50
    block = int(round(bar_length * progress))

    # Construct the progress bar text
    progress_percentage = f"{progress * 100:.0f}%"
    through_of = f"[{progress}/{total}]"
    progress_bar = f'[{ "#" * block + "-" * (bar_length - block)}] {progress_percentage} {through_of}'

    # Print or update the progress bar on the same line
    sys.stdout.write(f'\r{name}: {progress_bar}{status}')
    sys.stdout.flush()
