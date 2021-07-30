from packaging.version import Version


def _strip_local_version_identifier(version):
    """
    Strips a local version identifier in `version`. For example, "1.2.3+ab" is stripped to "1.2.3".

    Local version identifiers:
    https://www.python.org/dev/peps/pep-0440/#local-version-identifiers
    """

    class IgnoreLocal(Version):
        @property
        def local(self):
            return None

    return str(IgnoreLocal(version))
