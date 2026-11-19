"""The VS Code server releases wpkd runs (docs/ide-direct-server-plan.md §3)."""

import io
import json
import os
import tarfile

import pytest

from work_packet import ide_releases as rel

PLAT = "linux-x64"


def release_files(commit, version, date="2026-11-17T00:00:00Z"):
    return {
        "product.json": json.dumps({"commit": commit, "version": version, "date": date,
                                    "quality": "stable"}),
        "bin/code-server": "#!/bin/sh\necho %s\n" % version,
        "out/server-main.js": "// server\n",
    }


def make_archive(dest, commit, version, top="vscode-server-linux-x64-web"):
    with tarfile.open(dest, "w:gz") as tf:
        d = tarfile.TarInfo(top)
        d.type = tarfile.DIRTYPE
        tf.addfile(d)
        for name, text in release_files(commit, version).items():
            data = text.encode()
            ti = tarfile.TarInfo("%s/%s" % (top, name))
            ti.size = len(data)
            ti.mode = 0o755 if name.startswith("bin/") else 0o644
            tf.addfile(ti, io.BytesIO(data))


def unpacked(d, commit, version, date="2026-11-17T00:00:00Z"):
    for name, text in release_files(commit, version, date).items():
        p = os.path.join(d, name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fp:
            fp.write(text)
    os.chmod(os.path.join(d, "bin", "code-server"), 0o755)


C1 = "1" * 40
C2 = "2" * 40
C3 = "3" * 40


class Service:
    """VS Code's update service: one latest release, its archive."""

    def __init__(self, commit, version):
        self.commit, self.version = commit, version
        self.downloads = []

    def get_json(self, url):
        assert url.endswith("/api/latest/server-linux-x64-web/stable"), url
        return {"version": self.commit, "productVersion": self.version, "name": self.version}

    def download(self, url, dest):
        self.downloads.append(url)
        commit = url.split("commit:")[1].split("/")[0]
        make_archive(dest, commit, self.version if commit == self.commit else "1.0.0")


def test_platform():
    assert rel.platform("Linux", "x86_64") == "linux-x64"
    assert rel.platform("Linux", "aarch64") == "linux-arm64"
    assert rel.platform("Darwin", "arm64") == "darwin-arm64"
    assert rel._artifact("darwin-x64") == "server-darwin-web"
    assert rel._artifact("linux-arm64") == "server-linux-arm64-web"
    with pytest.raises(rel.ReleaseError):
        rel.platform("Windows", "x86_64")


def test_vkey_orders_versions():
    assert rel.vkey("1.147.0") > rel.vkey("1.98.2")
    assert rel.vkey("1.147.1") > rel.vkey("1.147.0")


def test_install_unpacks_and_checks(tmp_path):
    svc = Service(C1, "1.147.0")
    r = rel.check(str(tmp_path), PLAT, svc.get_json, svc.download)
    assert r == {"commit": C1, "version": "1.147.0", "date": "2026-11-17T00:00:00Z"}
    assert os.access(rel.binary(str(tmp_path), C1, PLAT), os.X_OK)
    assert [x["commit"] for x in rel.installed(str(tmp_path), PLAT)] == [C1]
    assert not any(n.endswith(rel.STAGING) for n in os.listdir(rel.root(str(tmp_path), PLAT)))
    assert rel.read_state(str(tmp_path), PLAT)["latest"] == C1
    # Already here: no second download.
    rel.check(str(tmp_path), PLAT, svc.get_json, svc.download)
    assert len(svc.downloads) == 1


def test_install_refuses_a_wrong_archive(tmp_path):
    def wrong(url, dest):
        make_archive(dest, C2, "1.2.3")         # names another commit
    with pytest.raises(rel.ReleaseError):
        rel.install(str(tmp_path), C1, PLAT, wrong)
    assert rel.installed(str(tmp_path), PLAT) == []
    assert os.listdir(rel.root(str(tmp_path), PLAT)) == []


def test_failed_download_leaves_nothing(tmp_path):
    def broken(url, dest):
        raise OSError("connection reset")
    with pytest.raises(rel.ReleaseError, match="connection reset"):
        rel.install(str(tmp_path), C1, PLAT, broken)
    assert os.listdir(rel.root(str(tmp_path), PLAT)) == []


def test_check_records_an_offline_failure(tmp_path):
    def offline(url):
        raise OSError("no network")
    with pytest.raises(rel.ReleaseError):
        rel.check(str(tmp_path), PLAT, offline)
    assert "no network" in rel.read_state(str(tmp_path), PLAT)["error"]


def test_current_is_newest_or_held(tmp_path):
    home = str(tmp_path)
    unpacked(rel.path(home, C1, PLAT), C1, "1.146.0")
    unpacked(rel.path(home, C2, PLAT), C2, "1.147.0")
    assert rel.current(home, {}, PLAT)["commit"] == C2
    assert rel.current(home, {"release": C1[:8]}, PLAT)["commit"] == C1
    assert rel.current(home, {"release": "1.146.0"}, PLAT)["commit"] == C1
    assert rel.current(home, {"release": C3}, PLAT) is None        # held, not here


def test_staging_is_not_a_release(tmp_path):
    home = str(tmp_path)
    unpacked(rel.path(home, C1, PLAT) + rel.STAGING, C1, "1.147.0")
    assert rel.installed(home, PLAT) == []


def test_seed_links_serve_webs_newest(tmp_path):
    home, cache = str(tmp_path / "home"), tmp_path / "serve-web"
    unpacked(str(cache / C1), C1, "1.146.0")
    unpacked(str(cache / C2), C2, "1.147.0")
    unpacked(str(cache / (C3 + ".staging")), C3, "1.148.0")       # serve-web mid-download
    r = rel.seed(home, rel.platform(), str(cache))
    assert r["commit"] == C2
    src = os.stat(cache / C2 / "bin" / "code-server")
    dst = os.stat(rel.binary(home, C2))
    assert (src.st_ino, src.st_dev) == (dst.st_ino, dst.st_dev)    # linked, not copied
    assert rel.seed(home, rel.platform(), str(cache)) is None      # nothing newer


def test_gc_keeps_running_current_and_one_more(tmp_path):
    home = str(tmp_path)
    for c, v in ((C1, "1.145.0"), (C2, "1.146.0"), (C3, "1.147.0")):
        unpacked(rel.path(home, c, PLAT), c, v)
    os.makedirs(rel.path(home, "f" * 40, PLAT) + rel.STAGING)
    # C3 is current (kept by the caller), C1 runs a desk; C2 is the one spare.
    assert rel.gc(home, {C3, C1}, PLAT) == []
    assert sorted(r["commit"] for r in rel.installed(home, PLAT)) == [C1, C2, C3]
    assert not any(n.endswith(rel.STAGING) for n in os.listdir(rel.root(home, PLAT)))
    # No desk on C1 any more: C2 is the spare, C1 goes.
    assert rel.gc(home, {C3}, PLAT) == [C1]


def test_start_get_runs_once(tmp_path):
    svc = Service(C1, "1.147.0")
    t = rel.start_get(str(tmp_path), PLAT, svc.get_json, svc.download)
    t.join(10)
    assert rel.find(str(tmp_path), C1, PLAT) is not None
    assert not rel.getting(PLAT)
    assert rel.last_failure(PLAT) is None
