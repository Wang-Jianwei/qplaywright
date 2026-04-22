from pathlib import Path
from shutil import copy2

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


ROOT = Path(__file__).parent.resolve()
SOURCE_HEADER = ROOT / "agent_cpp" / "qplaywright_agent.h"
PACKAGE_HEADER = Path("qplaywright") / "cpp" / "qplaywright_agent.h"


class build_py(_build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / PACKAGE_HEADER
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(SOURCE_HEADER, target)


setup(cmdclass={"build_py": build_py})