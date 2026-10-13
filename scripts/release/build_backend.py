"""Filter the wheel against the exact reviewed runtime inventory."""
import json
from pathlib import Path
from setuptools.command.build_py import build_py

class ReviewedBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        approved = set(json.loads(Path('release-manifest.json').read_text(encoding='utf8'))['inventory']['runtime_files'])
        return [entry for entry in super().find_package_modules(package, package_dir)
                if Path(entry[2]).as_posix() in approved]
