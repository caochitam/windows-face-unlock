"""Single source of truth for the app version.

Bumped manually for each release. GitHub Actions tags the repo with the
matching ``v<version>`` and the installer file name includes this too.
The updater compares this constant against the ``tag_name`` of the latest
published release.
"""
__version__ = "0.1.0"
