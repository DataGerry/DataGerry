# DataGerry - OpenSource Enterprise CMDB
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
DataGerry is a flexible asset management tool and open-source configurable management database
"""
import logging.config
import signal
import traceback
from argparse import ArgumentParser, Namespace
import os
import sys

import cmdb
from cmdb import __title__

from cmdb.utils.logger import get_logging_conf
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.process_management.process_manager import ProcessManager
# -------------------------------------------------------------------------------------------------------------------- #

# Setup logging
logging.config.dictConfig(get_logging_conf())

LOGGER = logging.getLogger(__name__)

app_manager = ProcessManager()

# -------------------------------------------------------------------------------------------------------------------- #

def main(args: Namespace):
    """
    Default application start function
    Args:
        args: start-options
    """
    try:
        # dbm = None
        LOGGER.info("Starting DataGerry...")

        __activate_debug_mode(args)
        __activate_cloud_mode(args)
        __activate_local_mode(args)
        _init_config_reader(args.config_file)

        if args.start:
            _start_app()
    except Exception as err:
        raise RuntimeError(err) from err

# ------------------------------------------------- HELPER FUNCTIONS ------------------------------------------------- #

def build_arg_parser() -> Namespace:
    """
    Generate application parameter parser

    Returns: instance of OptionParser
    """
    _parser = ArgumentParser(prog='DataGerry', usage=f"usage: {__title__} [options]")

    _parser.add_argument(
        '--keys',
        action='store_true',
        default=False,
        dest='keys',
        help="init keys"
    )

    _parser.add_argument(
        '--cloud',
        action='store_true',
        default=False,
        dest='cloud',
        help="init cloud mode"
    )

    _parser.add_argument(
        '--local',
        action='store_true',
        default=False,
        dest='local',
        help="init local mode"
    )

    _parser.add_argument(
        '-d',
        '--debug',
        action='store_true',
        default=False,
        dest='debug',
        help="enable debug mode: DO NOT USE ON PRODUCTIVE SYSTEMS"
    )

    _parser.add_argument(
        '-s',
        '--start',
        action='store_true',
        default=False,
        dest='start',
        help="starting cmdb core system - enables services"
    )

    _parser.add_argument(
        '-c',
        '--config',
        default='./etc/cmdb.conf',
        dest='config_file',
        help="optional path to config file"
    )

    return _parser.parse_args()


def __activate_debug_mode(args: Namespace):
    """
    Sets the __MODE__ to DEBUG if activated
    """
    if args.debug:
        cmdb.__MODE__ = 'DEBUG'
        LOGGER.warning("DEBUG MODE enabled")


def __activate_local_mode(args: Namespace):
    """
    Activates __LOCAL_MODE__ if set
    """
    if args.local:
        cmdb.__LOCAL_MODE__ = True
        LOGGER.warning("LOCAL MODE enabled")


def __activate_cloud_mode(args: Namespace):
    """
    Activates __CLOUD_MODE__ if set
    """
    if args.cloud:
        cmdb.__CLOUD_MODE__ = True
        LOGGER.info("CLOUD MODE enabled")


def _init_config_reader(config_file: str):
    """
    Initialises the config file reader

    Args:
        config_file (str): Path to config file as a string
    """
    path, filename = os.path.split(config_file)

    if filename is not SystemConfigReader.DEFAULT_CONFIG_NAME:
        SystemConfigReader.RUNNING_CONFIG_NAME = filename

    if path is not SystemConfigReader.DEFAULT_CONFIG_LOCATION:
        SystemConfigReader.RUNNING_CONFIG_LOCATION = path + '/'

    SystemConfigReader(SystemConfigReader.RUNNING_CONFIG_NAME, SystemConfigReader.RUNNING_CONFIG_LOCATION)


def _start_app() -> None:
    """
    Starting application services
    """
    # install signal handler
    signal.signal(signal.SIGTERM, _stop_app)

    # start app
    app_status = app_manager.start_app()
    LOGGER.info('Process manager started: %s', app_status)


def _stop_app():
    """
    Stop application services
    """
    app_manager.stop_app()

# --------------------------------------------------- INTIALISATION -------------------------------------------------- #

if __name__ == "__main__":
    BRAND_STRING = """
        ########################################################################                                  
        
        @@@@@     @   @@@@@@@ @           @@@@@  @@@@@@@ @@@@@   @@@@@  @@    @@
        @    @    @@     @    @@         @@@@@@@ @@@@@@@ @@@@@@  @@@@@@ @@@  @@@
        @     @  @  @    @   @  @       @@@   @@ @@@     @@   @@ @@   @@ @@  @@ 
        @     @  @  @    @   @  @       @@       @@@@@@  @@   @@ @@   @@  @@@@  
        @     @ @    @   @  @    @      @@   @@@ @@@@@@  @@@@@@  @@@@@@   @@@@  
        @     @ @@@@@@   @  @@@@@@      @@   @@@ @@@     @@@@@   @@@@@     @@   
        @     @ @    @   @  @    @      @@@   @@ @@@     @@ @@@  @@ @@@    @@   
        @    @ @      @  @ @      @      @@@@@@@ @@@@@@@ @@  @@@ @@  @@@   @@   
        @@@@@  @      @  @ @      @       @@@@@@ @@@@@@@ @@  @@@ @@  @@@   @@   
                            
        ########################################################################\n
    """

    WELCOME_STRING = """
        Welcome to DataGerry
        Starting system with following parameters:
        {}\n
    """

    LICENSE_STRING = """
        Copyright (C) 2025 becon GmbH
        licensed under the terms of the GNU Affero General Public License version 3\n
    """

    try:
        options: Namespace = build_arg_parser()
        print(BRAND_STRING)
        print(WELCOME_STRING.format(options.__dict__))
        print(LICENSE_STRING)
        main(options)
    except Exception as err:
        if cmdb.__MODE__ == 'DEBUG':
            traceback.print_exc()

        LOGGER.critical("%s: %s",type(err).__name__, err, exc_info=True)
        LOGGER.info("DataGerry stopped!")
        sys.exit(1)
