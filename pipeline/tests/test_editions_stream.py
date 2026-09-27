import httpx
import pyarrow as pa
import respx

from pipeline.sources.editions import stream_editions
from pipeline.tests.fixtures.dumps import edition_line, gz

URL = "https://dumps.test/ol_dump_editions_2026-08-31.txt.gz"
LINES = [
    edition_line("OL1M", "OL10W", title="A Game of Thrones", series=["A Song of Ice and Fire ; 1"]),
    edition_line("OL2M", "OL10W", languages=("fre",), title="Le Trône de fer"),
    edition_line("OL3M", "OL77W", title="Not selected"),
    edition_line("OL4M", "OL77W", languages=("ger",), title="Linked by Wikidata"),
    edition_line("OL5M", "OL99W", title="Redirected work"),
    "garbage line without tabs",
]


class ListSink:
    def __init__(self):
        self.batches, self.resets = [], 0

    def reset(self):
        self.batches, self.resets = [], self.resets + 1

    def write(self, batch):
        self.batches.append(batch)

    def rows(self):
        return pa.concat_tables(self.batches).to_pylist() if self.batches else []


@respx.mock
def test_keeps_english_editions_of_candidates_and_wikidata_editions(tmp_path):
    respx.get(URL).mock(return_value=httpx.Response(200, content=gz(LINES)))
    sink = ListSink()
    with httpx.Client() as client:
        record, counts = stream_editions(client, URL, {"OL10W", "OL30W"}, {"OL4M"}, sink,
                                         resolve={"OL99W": "OL30W"}, sleep=lambda s: None, batch_size=2)
    kept = {r["ol_id"]: r for r in sink.rows()}
    assert set(kept) == {"OL1M", "OL4M", "OL5M"}
    assert kept["OL1M"]["series"] == ["A Song of Ice and Fire ; 1"]
    assert kept["OL4M"]["is_english"] is False
    assert kept["OL5M"]["work_ol_id"] == "OL30W"
    assert counts == {"OL10W": 2, "OL30W": 1}
    assert record.retrieved == "2026-08-31"
    assert list(tmp_path.iterdir()) == []  # nothing written to disk


@respx.mock
def test_a_truncated_stream_restarts_from_the_beginning():
    data = gz(LINES)
    respx.get(URL).mock(side_effect=[httpx.Response(200, content=data[:-30]), httpx.Response(200, content=data)])
    sink = ListSink()
    with httpx.Client() as client:
        stream_editions(client, URL, {"OL10W"}, set(), sink, sleep=lambda s: None)
    assert sink.resets == 2
    assert [r["ol_id"] for r in sink.rows()] == ["OL1M"]
