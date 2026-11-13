import logging

import pytest
import requests

from pipeline import config, ingest
from tests.conftest import VIIRS_NRT_HEADER

FAKE_KEY = "abcdef0123456789SECRET"


class Resp:
    def __init__(self, text, status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error for url: {self.url}")


class Session:
    """Fake requests: returns a canned answer per source, records URLs."""

    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        for source, ans in self.answers.items():
            if f"/{source}/" in url:
                if isinstance(ans, Exception):
                    raise type(ans)(f"{ans} url={url}")
                r = Resp(*ans) if isinstance(ans, tuple) else Resp(ans)
                r.url = url
                return r
        raise AssertionError(url)


@pytest.fixture(autouse=True)
def fake_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FIRMS_MAP_KEY", FAKE_KEY)
    monkeypatch.setattr(ingest.paths, "RAW_API", tmp_path / "api")
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)
    monkeypatch.setattr(ingest.paths, "API_STATUS", tmp_path / "api_status.json")


CSV = VIIRS_NRT_HEADER + "\n-2.5,113.5,345,0.4,0.4,2026-11-08,0620,N20,VIIRS,n,2.0NRT,290,9.1,D\n"


def test_url_per_source():
    s = Session({"VIIRS_NOAA20_NRT": CSV, "VIIRS_SNPP_NRT": VIIRS_NRT_HEADER + "\n", "MODIS_NRT": ""})
    rows, report = ingest.fetch_all(2, FAKE_KEY, s)
    assert [u.split("/")[-3] for u in s.urls] == config.data_cfg()["firms"]["api_sources"]
    assert s.urls[0].endswith("/VIIRS_NOAA20_NRT/108.5,-4.5,119.5,7.5/2")
    assert report == {"VIIRS_NOAA20_NRT": 1, "VIIRS_SNPP_NRT": 0, "MODIS_NRT": 0}
    assert rows.satellite.tolist() == ["NOAA-20"] and rows.source.tolist() == ["nrt"]


def test_days_clamped_to_api_limit():
    s = Session({"VIIRS_NOAA20_NRT": CSV, "VIIRS_SNPP_NRT": CSV, "MODIS_NRT": CSV})
    ingest.fetch_all(50, FAKE_KEY, s)
    assert all(u.endswith("/10") for u in s.urls)


def test_html_and_empty_are_no_data():
    s = Session({"VIIRS_NOAA20_NRT": "<html>down</html>", "VIIRS_SNPP_NRT": VIIRS_NRT_HEADER + "\n",
                 "MODIS_NRT": ("", 200)})
    rows, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert rows.empty and set(report.values()) == {0}


def test_invalid_key_is_a_failure():
    """FIRMS answers a wrong key with HTTP 200 "Invalid MAP_KEY." -> failed fetch, not "no data"."""
    s = Session({"VIIRS_NOAA20_NRT": "Invalid MAP_KEY.", "VIIRS_SNPP_NRT": "Invalid MAP_KEY.",
                 "MODIS_NRT": "Invalid MAP_KEY."})
    _, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert not ingest.api_fetch_ok(report)
    assert ingest.failure_reason(report) == "FIRMS_MAP_KEY rejected by FIRMS"


def test_key_never_in_logs_or_errors(caplog):
    s = Session({"VIIRS_NOAA20_NRT": requests.ConnectionError("boom"),
                 "VIIRS_SNPP_NRT": ("nope", 500), "MODIS_NRT": "Invalid MAP_KEY " + FAKE_KEY})
    with caplog.at_level(logging.DEBUG):
        _, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert "error" in str(report["VIIRS_NOAA20_NRT"]) and "error" in str(report["VIIRS_SNPP_NRT"])
    assert FAKE_KEY in "".join(s.urls)                      # the key was used in the URL ...
    assert FAKE_KEY not in caplog.text                       # ... but never logged
    assert FAKE_KEY not in str(report)
    with pytest.raises(ingest.FirmsError) as e:
        ingest.fetch_api("VIIRS_NOAA20_NRT", 1, FAKE_KEY, s)
    assert FAKE_KEY not in str(e.value)


def test_redact():
    assert config.redact(f"https://x/{FAKE_KEY}/y") == "https://x/***/y"


def test_no_key_skips_download(no_key, caplog):
    assert config.get_map_key() is None
    with caplog.at_level(logging.WARNING):
        rows, report = ingest.fetch_all(1, config.get_map_key())
    assert rows.empty and report == {"error": "no key"}
    assert "FIRMS_MAP_KEY is not set" in caplog.text


def test_update_falls_back_to_sample_without_key(no_key, monkeypatch, tmp_path):
    """Empty data/processed + no key -> sample rebuild, flagged as sample."""
    monkeypatch.setattr(ingest.paths, "HOTSPOTS_DIR", tmp_path / "hotspots")
    monkeypatch.setattr(ingest.paths, "INGEST_META", tmp_path / "ingest_meta.json")
    monkeypatch.setattr(ingest, "load_processed", lambda folder=None: ingest.pd.DataFrame())
    written = {}

    def fake_rebuild(now=None):
        written["rebuilt"] = True
        (tmp_path / "hotspots").mkdir()
        (tmp_path / "hotspots" / "year=2026.parquet").write_bytes(b"x")
        (tmp_path / "ingest_meta.json").write_text('{"is_sample": true, "data_through_utc": "2026-11-08 06:00"}')

    monkeypatch.setattr(ingest, "rebuild", fake_rebuild)
    result = ingest.update()
    assert written["rebuilt"] and result["is_sample"] is True and result["added"] == 0


# ----------------------------------------------------------------- Data status (api_status.json)
def test_failure_reason_is_short_and_key_free():
    s = Session({"VIIRS_NOAA20_NRT": ("nope", 403), "VIIRS_SNPP_NRT": ("nope", 403), "MODIS_NRT": ("nope", 403)})
    _, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert ingest.failure_reason(report) == "HTTP 403"
    s = Session({"VIIRS_NOAA20_NRT": CSV, "VIIRS_SNPP_NRT": requests.Timeout("slow"), "MODIS_NRT": CSV})
    _, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert ingest.failure_reason(report) == "timeout (VIIRS_SNPP_NRT)"
    s = Session({"VIIRS_NOAA20_NRT": requests.ConnectionError("x"), "VIIRS_SNPP_NRT": ("e", 500), "MODIS_NRT": CSV})
    _, report = ingest.fetch_all(1, FAKE_KEY, s)
    assert ingest.failure_reason(report) == "VIIRS_NOAA20_NRT: connection error; VIIRS_SNPP_NRT: HTTP 500"
    assert ingest.failure_reason({"error": "no key"}) == "FIRMS_MAP_KEY missing"
    assert ingest.failure_reason({"VIIRS_NOAA20_NRT": 3}) is None
    assert FAKE_KEY not in str(report)


def test_api_fetch_ok():
    assert ingest.api_fetch_ok({"VIIRS_NOAA20_NRT": 54, "VIIRS_SNPP_NRT": 0, "MODIS_NRT": 33})
    assert not ingest.api_fetch_ok({"VIIRS_NOAA20_NRT": 54, "MODIS_NRT": "error: FIRMS MODIS_NRT unreachable"})
    assert not ingest.api_fetch_ok({"error": "no key"})
    assert not ingest.api_fetch_ok({})


def test_api_status_success_then_failure_keeps_last_success(tmp_path):
    from datetime import datetime, timezone
    p = tmp_path / "s.json"
    t1 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    ok = ingest.record_api_status({"VIIRS_NOAA20_NRT": 54, "MODIS_NRT": 33}, t1, p)
    assert ok == {"api_last_attempt": "2026-11-09T12:00:00Z", "api_ok": True,
                  "api_last_success": "2026-11-09T12:00:00Z",
                  "api_rows_by_source": {"VIIRS_NOAA20_NRT": 54, "MODIS_NRT": 33}, "api_error": None}
    bad = ingest.record_api_status({"VIIRS_NOAA20_NRT": "error: boom", "MODIS_NRT": 3}, t2, p)
    assert bad["api_ok"] is False and bad["api_last_attempt"] == "2026-11-10T12:00:00Z"
    assert bad["api_last_success"] == "2026-11-09T12:00:00Z"
    assert bad["api_rows_by_source"] == {"VIIRS_NOAA20_NRT": 54, "MODIS_NRT": 33}
    assert bad["api_error"] == "boom (VIIRS_NOAA20_NRT)"


def test_api_status_no_key_is_failure(no_key, tmp_path):
    st = ingest.record_api_status({"error": "no key"}, path=tmp_path / "s.json")
    assert st["api_ok"] is False and st["api_last_success"] is None and st["api_rows_by_source"] == {}
    assert st["api_error"] == "FIRMS_MAP_KEY missing"


def test_update_records_status_without_the_key(monkeypatch, tmp_path):
    """The daily update writes api_status.json; neither it nor anything derived contains the key."""
    monkeypatch.setattr(ingest, "read_meta", lambda: {"is_sample": True, "data_through_utc": "2026-11-08 06:00"})
    monkeypatch.setattr(ingest.paths, "HOTSPOTS_DIR", tmp_path / "hot")
    (tmp_path / "hot").mkdir()
    (tmp_path / "hot" / "year=2026.parquet").write_bytes(b"x")
    s = Session({"VIIRS_NOAA20_NRT": requests.ConnectionError("boom"), "VIIRS_SNPP_NRT": "", "MODIS_NRT": ""})
    ingest.update(session=s)
    text = (tmp_path / "api_status.json").read_text(encoding="utf-8")
    assert FAKE_KEY not in text and FAKE_KEY[:6] not in text
    assert ingest.json.loads(text)["api_ok"] is False
    assert ingest.json.loads(text)["api_error"] == "connection error (VIIRS_NOAA20_NRT)"
