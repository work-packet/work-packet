"""The dashboard shows a finished project the same once its runs are removed
and it is read from the history store (docs/dash-history-v1.md)."""

import os
import shutil

import pytest

from test_migrate import finished
from work_packet import archived, history, migrate, registry


def _tree(d):
    out = {}
    for dp, dns, fns in os.walk(d):
        rel = os.path.relpath(dp, d)
        if rel.split(os.sep)[0] in history.SKIP_TOP or set(rel.split(os.sep)) & history.SKIP_DIRS:
            dns[:] = []
            continue
        for f in fns:
            p = os.path.join(dp, f)
            r = os.path.normpath(os.path.join(rel, f))
            if f in history.SKIP_FILES:
                continue
            if not os.path.islink(p):
                out[r] = open(p, "rb").read()
    return out


@pytest.fixture
def client_for():
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient
    from work_packet.dash.app import create_app
    return lambda: TestClient(create_app())


def test_restore_gives_back_the_record(tmp_path, fake):
    proj, root, kid = finished(tmp_path)
    migrate.migrate()
    con = history.connect()
    for pkt in (root, kid):
        dest = tmp_path / "r" / pkt.wpid
        history.restore_packet(con, pkt.wpid, str(dest))
        assert _tree(str(dest)) == _tree(pkt.path)
        assert not os.path.exists(os.path.join(str(dest), "work"))

    # A snapshot a step took of work/ is part of the record.
    sd = os.path.join(root.path, "steps", "0001", "deliverables", "work", "r")
    os.makedirs(sd)
    with open(os.path.join(sd, "f.md"), "w") as fp:
        fp.write("x\n")
    assert "steps/0001/deliverables/work/r/f.md" in history._files(root.path)
    con.close()


def test_pages_are_the_same_from_history(tmp_path, fake, client_for):
    from work_packet.dash import crawl
    proj, root, kid = finished(tmp_path)
    # Looked at first: opening a finished project records "seen" in its journal,
    # which the copy in the history store would not have otherwise.
    from work_packet import executor
    from work_packet.packet import Packet
    assert executor.mark_seen(Packet(root.path)).msg.endswith("seen")
    migrate.migrate()
    before = crawl.crawl(client_for(), "demo")
    assert len(before) > 10 and before["/p/demo/" + root.wpid][0] == 200

    shutil.rmtree(os.path.join(proj, "packets"))
    after = crawl.crawl(client_for(), "demo")
    e = archived.get("demo")
    assert archived.is_archived(e) and e["origin"] == proj
    assert crawl.compare(before, after, [(e["path"], proj)]) == []

    # The board and the overview list it as before.
    c = client_for()
    assert "demo" in c.get("/").text


def test_archived_project_is_read_only(tmp_path, fake, client_for):
    proj, root, kid = finished(tmp_path)
    migrate.migrate()
    shutil.rmtree(os.path.join(proj, "packets"))
    c = client_for()
    r = c.post("/p/demo/%s/act" % root.wpid, data={"op": "pause"}, follow_redirects=False)
    assert r.status_code == 409 and "archived" in r.text


def test_deliverables_in_work_that_reports_link_to_are_kept(tmp_path, fake, client_for):
    proj, root, kid = finished(tmp_path)
    os.makedirs(os.path.join(root.path, "work", "repo", "docs"))
    with open(os.path.join(root.path, "work", "repo", "docs", "guide.md"), "w") as fp:
        fp.write("# The guide\n")
    with open(os.path.join(root.path, "work", "repo", "big.bin"), "wb") as fp:
        fp.write(b"x")
    from work_packet import frontmatter
    meta, body = frontmatter.load(os.path.join(root.path, "report.md"))
    meta["deliverables"] = [{"path": "work/repo/docs/guide.md", "what": "the guide"}]
    with open(os.path.join(root.path, "report.md"), "w") as fp:
        fp.write(frontmatter.dump(meta, body + "\nSee [the guide](work/repo/docs/guide.md#top).\n"))
    migrate.migrate()
    con = history.connect()
    tiers = dict(con.execute("SELECT path, tier FROM file WHERE packet = ?", (root.wpid,)))
    con.close()
    assert tiers["work/repo/docs/guide.md"] == "deliverables"
    assert "work/repo/big.bin" not in tiers
    url = "/p/demo/%s/file?path=work/repo/docs/guide.md" % root.wpid
    before = client_for().get(url)
    assert before.status_code == 200 and "The guide" in before.text
    shutil.rmtree(os.path.join(proj, "packets"))
    after = client_for().get(url)
    e = archived.get("demo")
    assert after.status_code == 200
    from work_packet.dash import crawl
    assert crawl.compare({url: (200, before.text)}, {url: (200, after.text)},
                         [(e["path"], proj)]) in ([], ["%s: body differs" % url])
    assert "The guide" in after.text


def test_cache_is_rebuilt_when_out_of_date(tmp_path, fake):
    proj, root, kid = finished(tmp_path)
    migrate.migrate()
    shutil.rmtree(os.path.join(proj, "packets"))
    d = archived.get("demo")["path"]
    os.unlink(os.path.join(d, archived.MARK))
    assert archived.get("demo")["path"] == d
    assert os.path.isfile(os.path.join(d, archived.MARK))
    # A project with its runs is read from them, not the cache.
    os.makedirs(os.path.join(proj, "packets"))
    assert not archived.is_archived(archived.view(registry.get("demo")))
