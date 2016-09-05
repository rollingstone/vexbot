import sys
from os import path
from subprocess import Popen

from vexbot.argenvconfig import ArgEnvConfig


def start_vexbot(context='default'):
    """
    starts up an instance of vexbot
    """
    process = None

    root_directory = path.abspath(path.join(path.dirname(__file__), '..'))
    robot_filepath = path.join(root_directory, 'robot.py')

    # Start the subprocess
    main_robot_args = [sys.executable,
                       robot_filepath,
                       context]

    process = Popen(main_robot_args)

    return process
