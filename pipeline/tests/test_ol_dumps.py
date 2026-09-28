import hashlib

import httpx
import pytest
import respx

from pipeline.sources.ol_dumps import DownloadError, download
from pipeline.tests.fixtures.dumps import gz

LATEST = "https://dumps.test/ol_dump_works_latest.txt.gz"
DATED = "https://archive.test/ol_dump_works_2026-08-31.txt.gz"
DATA = gz([f"/type/work\t/works/OL{i}W\t1\t2026\t{{}}" for i in range(500)])


@respx.mock
def test_downloads_through_the_redirect_and_records_the_source(tmp_path):
    respx.get(LATEST).mock(return_value=httpx.Response(302, headers={"Location": DATED}))
    respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA))
    with httpx.Client() as client:
        record = download(client, "works", LATEST, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert (tmp_path / "works.txt.gz").read_bytes() == DATA
    assert record.url == DATED
    assert record.retrieved == "2026-08-31"
    assert record.sha256 == hashlib.sha256(DATA).hexdigest()
    assert record.size == len(DATA)


@respx.mock
def test_resumes_a_partial_download_with_a_range_request(tmp_path):
    half = len(DATA) // 2
    (tmp_path / "works.txt.gz.part").write_bytes(DATA[:half])

    def serve(request):
        assert request.headers["Range"] == f"bytes={half}-"
        return httpx.Response(206, content=DATA[half:])

    respx.get(DATED).mock(side_effect=serve)
    with httpx.Client() as client:
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert (tmp_path / "works.txt.gz").read_bytes() == DATA


@respx.mock
def test_retries_a_server_error_with_backoff(tmp_path):
    respx.get(DATED).mock(side_effect=[httpx.Response(503), httpx.Response(200, content=DATA)])
    sleeps = []
    with httpx.Client() as client:
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=sleeps.append)
    assert sleeps == [1]


@respx.mock
def test_a_corrupt_file_is_deleted_and_fails_the_stage(tmp_path):
    respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA[:-20]))
    with httpx.Client() as client, pytest.raises(DownloadError, match="verification"):
        download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert list(tmp_path.iterdir()) == []


@respx.mock
def test_a_finished_download_is_not_fetched_again(tmp_path):
    route = respx.get(DATED).mock(return_value=httpx.Response(200, content=DATA))
    with httpx.Client() as client:
        first = download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
        second = download(client, "works", DATED, tmp_path / "works.txt.gz", sleep=lambda s: None)
    assert route.call_count == 1
    assert first == second
