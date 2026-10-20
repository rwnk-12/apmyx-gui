import argparse
import asyncio

from creart import add_creator

parser = argparse.ArgumentParser(description="AppleMusicDecrypt")
parser.add_argument(
    "--legacy-ui",
    action="store_true",
    help="use the plain-terminal REPL instead of the full-screen TUI",
)
args, _ = parser.parse_known_args()

loop = asyncio.new_event_loop()

from applemusicdecrypt.logger import LoggerCreator
add_creator(LoggerCreator)
from applemusicdecrypt.config import ConfigCreator
add_creator(ConfigCreator)
from applemusicdecrypt.api import APICreator
add_creator(APICreator)
from applemusicdecrypt.wrapper import WrapperCreator
add_creator(WrapperCreator)
from applemusicdecrypt.decrypt import DecryptorCreator
add_creator(DecryptorCreator)
from applemusicdecrypt.measurer import MeasurerCreator
add_creator(MeasurerCreator)
from applemusicdecrypt.tui.task_tree import TaskTreeCreator
add_creator(TaskTreeCreator)

from applemusicdecrypt.cmd import InteractiveShell

if __name__ == '__main__':
    cmd = InteractiveShell(loop, legacy_ui=args.legacy_ui)
    try:
        loop.run_until_complete(cmd.start())
    except KeyboardInterrupt:
        loop.stop()
