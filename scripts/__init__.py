"""Reviewed legacy Controller components shared by the V1 application."""

def __getattr__(name):
    if name != "ReviewedBuildPy":
        raise AttributeError(name)
    import json
    from pathlib import Path
    from setuptools.command.build_py import build_py

    class ReviewedBuildPy(build_py):
        def find_package_modules(self, package, package_dir):
            approved = set(json.loads(Path("release-manifest.json").read_text(encoding="utf8"))["inventory"]["runtime_files"])
            modules = super().find_package_modules(package, package_dir)
            return [entry for entry in modules if Path(entry[2]).as_posix() in approved]

    return ReviewedBuildPy
