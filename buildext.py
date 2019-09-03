# Common things

import dragon
import apps_tools.android as android
from apps_tools.common import get_version_code


def setup_argparse(parser):
    android.setup_argparse(parser)

def setup_deftasks():
    # Do additional checks on version code early to avoid useless builds
    try:
        _ = get_version_code(dragon.PARROT_BUILD_VERSION)
    except ValueError:
        raise dragon.SetupError("Bad version {}".format(dragon.PARROT_BUILD_VERSION))