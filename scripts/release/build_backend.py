"""Filter the wheel against the exact reviewed runtime inventory."""
import json
from pathlib import Path
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

ROOT = Path(__file__).resolve().parents[2]

class ReviewedBuildPy(build_py):
    def find_package_modules(self, package, package_dir):
        approved = set(json.loads((ROOT / 'release-manifest.json').read_text(encoding='utf8'))['inventory']['runtime_files'])
        return [entry for entry in super().find_package_modules(package, package_dir)
                if Path(entry[2]).as_posix() in approved]


class ReviewedSdist(sdist):
    """Ship the exact reviewed source plus explicitly known setuptools metadata."""
    def make_distribution(self):
        approved = set(json.loads((ROOT / 'release-manifest.json').read_text(encoding='utf8'))['inventory']['files'])
        metadata = {self.distribution.get_name().replace('-', '_') + '.egg-info/' + name
                    for name in ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt',
                                 'entry_points.txt', 'requires.txt', 'top_level.txt')}
        self.filelist.files = sorted(approved | {name for name in metadata if Path(name).is_file()})
        sources = Path(self.distribution.get_name().replace('-', '_') + '.egg-info/SOURCES.txt')
        sources.write_text('\n'.join(self.filelist.files) + '\n', encoding='utf-8')
        super().make_distribution()
