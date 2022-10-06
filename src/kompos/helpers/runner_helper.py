import logging
from subprocess import Popen, PIPE


def validate_runner_version(kompos_config, runner):
    """
    Check if runner binary version is compatible with the
    version specified by the kompos configuration.
    """
    try:
        execution = Popen([runner, '--version'],
                          stdin=PIPE,
                          stdout=PIPE,
                          stderr=PIPE)
    except Exception:
        logging.exception("Runner {} does not appear to be installed, "
                          "please ensure terraform is in your PATH".format(runner))
        exit(1)

    expected_version = kompos_config.runner_version(runner)
    current_version, execution_error = execution.communicate()
    current_version = current_version.decode('utf-8').split('\n', 1)[0]

    if expected_version not in current_version:
        raise Exception("Runner [{}] should be {}, but you have {}. Please change your version.".format(
            runner, expected_version, current_version))

    return
