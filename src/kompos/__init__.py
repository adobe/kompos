# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import re
from subprocess import call, Popen, PIPE

from .cli import display


__version__ = "0.2.12"


class Executor():
    """ All cli commands usually return a dict(command=...) that will be executed by this handler"""

    def __call__(self, result, pass_trough=True, cwd=None):
        try:
            return self._execute(result, pass_trough, cwd)
        except Exception as ex:
            display(str(ex), stderr=True, color='red')
            display(
                '------- TRACEBACK ----------',
                stderr=True,
                color='dark gray')
            import traceback
            traceback.print_exc()
            display(
                '------ END TRACEBACK -------',
                stderr=True,
                color='dark gray')

    def _execute(self, result, pass_trough=True, cwd=None):
        exit_code = 0

        if not result or not isinstance(result, dict):
            return

        if 'command' in result:
            shell_command = result['command']
            display(
                "%s" %
                shell_command,
                stderr=True,
                color='yellow')
            if pass_trough:
                exit_code = call(shell_command, shell=True, cwd=cwd)
            else:
                p = Popen(
                    shell_command,
                    shell=True,
                    stdout=PIPE,
                    stderr=PIPE,
                    cwd=cwd)
                output, errors = p.communicate()
                display(str(output))
                if errors:
                    display(
                        "%s" %
                        shell_command,
                        stderr=True,
                        color='red')
                exit_code = p.returncode

        if 'post_actions' in result:
            for callback in result['post_actions']:
                callback()

        return exit_code
