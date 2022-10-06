# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

from subprocess import call

from termcolor import colored

__version__ = "0.4.0-local"


def display(msg, color):
    print(colored(msg, color))


class Executor:
    """ All cli commands usually return a dict(command=...) that will be executed by this handler"""

    def __call__(self, cmd, cwd=None):
        try:
            return self._execute(cmd, cwd)
        except Exception as ex:
            display(str(ex), color='red')
            display('------- TRACEBACK ----------', color='yellow')
            import traceback
            traceback.print_exc()
            display('------ END TRACEBACK -------', color='yellow')

    @staticmethod
    def _execute(cmd, cwd=None):
        if 'command' in cmd:
            shell_command = cmd['command']
            display(shell_command, color='yellow')
            return call(shell_command, shell=True, cwd=cwd)
        else:
            return 1
