# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2025 becon GmbH
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
Logging module
"""
from typing import Any
import os
import multiprocessing
import pathlib

import cmdb
# -------------------------------------------------------------------------------------------------------------------- #

DEFAULT_LOG_DIR: str = os.path.join(os.path.dirname(__file__), '../../logs/')

LOGLEVELS: dict[str, int] = {
    "NOTSET": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50
}


def get_log_level(minlevel=None):
    """
    loads logger configuration from config file
    will be overwrite cmdb.__MODE__
    Returns:
        config level
    """
    # set default loglevel to WARNING
    loglevel = "WARNING"

    # get loglevel from CMDB mode, if a correct value is set
    if cmdb.__MODE__ in LOGLEVELS:
        loglevel = cmdb.__MODE__

    # ensure a minimum loglevel
    if minlevel and minlevel in LOGLEVELS:
        if LOGLEVELS.get(minlevel) < LOGLEVELS.get(loglevel):
            loglevel = minlevel

    # return loglevel
    return loglevel


def get_logging_conf() -> dict[str, Any]:
    """
    returns the logging configuration

    Returns:
        instance of logging.Logger
    """
    pathlib.Path(DEFAULT_LOG_DIR).mkdir(parents=True, exist_ok=True)

    # get current process name
    proc_name = multiprocessing.current_process().name

    logging_conf: dict[str, Any] = {
        'version':1,
        'disable_existing_loggers':True,
        'handlers':{
            'console': {
                'class': 'logging.StreamHandler',
                'formatter': 'generic'
            },
            'file_daemon': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}{proc_name}.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            },
            'file_web_access': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}webserver.access.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            },
            'file_web_error': {
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'generic',
                'filename': f"{DEFAULT_LOG_DIR}webserver.error.log",
                'maxBytes': 10 * 1024 * 1024,  # 10 MBytes
                'backupCount': 4
            }
        },
        'formatters':{
            'generic': {
                'format': '[%(asctime)s][%(levelname)-8s] --- %(message)s (%(filename)s)',
                'datefmt': '%Y-%m-%d %H:%M:%S',
                'class': 'logging.Formatter'
            }
        },
        'loggers':{
            "__main__": {
                'level': str(get_log_level(minlevel="INFO")),
                'handlers': ['console', 'file_daemon'],
                'propagate': False
            },
            "cmdb": {
                'level': str(get_log_level()),
                'handlers': ['console', 'file_daemon'],
                'propagate': False
            },
            "gunicorn.error": {
                "level": "INFO",
                "handlers": ["file_web_error"],
                "propagate": False,
                "qualname": "gunicorn.error"
            },
            "gunicorn.access": {
                "level": "INFO",
                "handlers": ["file_web_access"],
                "propagate": False,
                "qualname": "gunicorn.access"
            }
        }
    }

    return logging_conf
