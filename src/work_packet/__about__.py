version_info = (0, 0, 1)

# CI rewrites this to ".dev<run-id>+<forge>.g<sha>" on non-tag builds, so a
# wheel produced by an ordinary push can never carry a version that could
# collide with a release on PyPI. Tag builds leave it empty and ship the clean
# version_info number.
SUFFIX = ""

__version__ = ".".join([str(n) for n in version_info]) + SUFFIX
