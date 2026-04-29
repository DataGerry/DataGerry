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
Different wrapper functions for interface module
"""
from logging import Logger, getLogger
import warnings
import inspect
from functools import wraps

import cmdb
# -------------------------------------------------------------------------------------------------------------------- #

string_types = (type(b''), type(''))

LOGGER: Logger = getLogger(__name__)

# -------------------------------------------------------------------------------------------------------------------- #
def deprecated(message):
    """
    This is a decorator which can be used to mark functions as deprecated.
    It will result in a warning being emitted when the function is used.
    The `message` argument must be an instance of :class:`basestring`
    (:class:`str` in python 3) For example::

        # The @deprecated is used with a 'message'.
        @deprecated("please, use another function")
        def old_function(x, y):
            pass

        # The @deprecated is used without any 'message'.
        @deprecated
        def old_function(x, y):
            pass

        # The @deprecated is used for class.
        @deprecated
        def OldClass(object):
                pass
    """
    if cmdb.__MODE__ == 'DEBUG':
        if isinstance(message, string_types):
            def deprecated_decorator(func1):

                warning1 = "Call to deprecated class {name} ({message})." \
                    if inspect.isclass(func1) else "Call to deprecated function {name} ({message})."

                @wraps(func1)
                def deprecated_func1(*args, **kwargs):
                    warnings.warn(
                        warning1.format(name=deprecated_func1.__name__, message=message),
                        category=DeprecationWarning,
                        stacklevel=2
                    )
                    warnings.simplefilter('default', DeprecationWarning)
                    return func1(*args, **kwargs)

                return deprecated_func1

            return deprecated_decorator

        if inspect.isclass(message) or inspect.isfunction(message):
            warning2 = "Call to deprecated class {name}." \
                if inspect.isclass(message) else "Call to deprecated function {name}."

            @wraps(message)
            def deprecated_func2(*args, **kwargs):
                warnings.warn(
                    warning2.format(name=message.__name__),
                    category=DeprecationWarning,
                    stacklevel=2
                )
                warnings.simplefilter('default', DeprecationWarning)
                return message(*args, **kwargs)

            return deprecated_func2


    @wraps(message)
    def _deprecated(*args, **kwargs):
        LOGGER.debug('%s is likely to be deprecated soon!',message)
        return message(*args, **kwargs)

    return _deprecated
