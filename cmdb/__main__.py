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
DataGerry is a flexible asset management tool and open-source configurable management database
"""
from logging import Logger, getLogger, config

import signal
import traceback
from argparse import ArgumentParser, Namespace
import os
import sys
from types import FrameType

import cmdb
from cmdb import __title__

from cmdb.utils.logger import get_logging_conf
from cmdb.manager.system_manager.system_config_reader import SystemConfigReader
from cmdb.process_management.process_manager import ProcessManager
# -------------------------------------------------------------------------------------------------------------------- #

# Setup logging
config.dictConfig(get_logging_conf())

LOGGER: Logger = getLogger(__name__)

app_manager = ProcessManager()

# -------------------------------------------------------------------------------------------------------------------- #

def main(args: Namespace) -> None:
    """
    Application entrypoint invoked from the __main__ block

    Applies the mode flags from the parsed CLI arguments to the cmdb module-level globals
    (__MODE__, __CLOUD_MODE__, __LOCAL_MODE__), initialises the SystemConfigReader from the
    requested config file, and — when --start was passed — hands off to ProcessManager to
    spawn the registered service processes. Any exception raised during startup is wrapped
    in a RuntimeError so the __main__ block's logging path receives a uniform failure type

    Args:
        args (Namespace): Parsed CLI arguments produced by build_arg_parser

    Raises:
        RuntimeError: Wraps any exception raised during startup so the __main__ block can
            log a single failure type and exit cleanly
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
    Defines and parses the DataGerry CLI flags

    Recognised flags: --keys, --cloud, --local, -d/--debug, -s/--start, -c/--config. The
    config flag defaults to './etc/cmdb.conf' when omitted; the boolean flags default to
    False so the absence of a flag matches its 'off' state

    Returns:
        Namespace: argparse Namespace carrying the parsed values, ready for main()
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


def __activate_debug_mode(args: Namespace) -> None:
    """
    Promotes cmdb.__MODE__ to 'DEBUG' when --debug was passed

    The __MODE__ global is consulted by other startup paths (e.g. the __main__ block's
    traceback printing on startup failure) so setting it here is a process-wide side effect
    that influences logging verbosity and error rendering everywhere

    Args:
        args (Namespace): Parsed CLI arguments; only args.debug is consulted
    """
    if args.debug:
        cmdb.__MODE__ = 'DEBUG'
        LOGGER.warning("DEBUG MODE enabled")


def __activate_local_mode(args: Namespace) -> None:
    """
    Sets cmdb.__LOCAL_MODE__ to True when --local was passed

    The __LOCAL_MODE__ global is read by parts of the auth and key-handling pipeline that
    branch on local vs. cloud deployment, so toggling it here is a process-wide side effect

    Args:
        args (Namespace): Parsed CLI arguments; only args.local is consulted
    """
    if args.local:
        cmdb.__LOCAL_MODE__ = True
        LOGGER.warning("LOCAL MODE enabled")


def __activate_cloud_mode(args: Namespace) -> None:
    """
    Sets cmdb.__CLOUD_MODE__ to True when --cloud was passed

    The __CLOUD_MODE__ global is read by parts of the request and auth pipeline (e.g.
    'x-api-key' header acceptance) that branch on local vs. cloud deployment, so toggling
    it here is a process-wide side effect

    Args:
        args (Namespace): Parsed CLI arguments; only args.cloud is consulted
    """
    if args.cloud:
        cmdb.__CLOUD_MODE__ = True
        LOGGER.info("CLOUD MODE enabled")


def _init_config_reader(config_file: str) -> None:
    """
    Points SystemConfigReader at the requested config file and instantiates the singleton

    Splits 'config_file' into directory + filename and overrides
    SystemConfigReader.RUNNING_CONFIG_LOCATION / .RUNNING_CONFIG_NAME when they differ from
    the class defaults. Then constructs a SystemConfigReader so subsequent code that calls
    SystemConfigReader() picks up the already-loaded singleton

    Args:
        config_file (str): Path to the cmdb.conf file (e.g. './etc/cmdb.conf')
    """
    path, filename = os.path.split(config_file)

    if filename is not SystemConfigReader.DEFAULT_CONFIG_NAME:
        SystemConfigReader.RUNNING_CONFIG_NAME = filename

    if path is not SystemConfigReader.DEFAULT_CONFIG_LOCATION:
        SystemConfigReader.RUNNING_CONFIG_LOCATION = path + '/'

    SystemConfigReader(SystemConfigReader.RUNNING_CONFIG_NAME, SystemConfigReader.RUNNING_CONFIG_LOCATION)


def _start_app() -> None:
    """
    Wires the SIGTERM handler and asks ProcessManager to spawn the registered services

    Registers _stop_app as the SIGTERM handler so a graceful shutdown can tear down each
    CmdbProcess, then delegates to the module-level app_manager (a ProcessManager) to
    spawn one multiprocessing.Process per registered service and logs the outcome
    """
    # install signal handler
    signal.signal(signal.SIGTERM, _stop_app)

    # start app
    app_status: bool = app_manager.start_app()
    LOGGER.info('Process manager started: %s', app_status)


def _stop_app(signum: int, frame: FrameType | None) -> None:
    """
    Asks ProcessManager to tear down every running CmdbProcess

    Installed as the SIGTERM handler by _start_app, so the OS-signalled shutdown path runs
    through this function before the interpreter exits. The signum / frame parameters are
    required by Python's signal-handler contract (signal.signal calls the handler with
    these two positional arguments) but are unused here because the action is unconditional

    Args:
        signum (int): The signal number that triggered the handler (always SIGTERM here)
        frame (FrameType | None): The interrupted stack frame, or None when not available
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
        Copyright (C) 2026 becon GmbH
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
