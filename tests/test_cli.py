import subprocess
import sys

from work_packet import __version__
from work_packet.cli import main


def test_version_flag(capsys):
    try:
        main(["--version"])
    except SystemExit as e:
        assert e.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_is_usage_error():
    assert main([]) == 2


def test_module_entry_point():
    r = subprocess.run([sys.executable, "-m", "work_packet", "--version"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "wpk" in r.stdout
