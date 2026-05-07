"""Tests for airport lookup caching behaviour."""

from __future__ import annotations

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest


class TestParseResponse:
    """Tests for the CSV-parsing helper."""

    def test_parses_csv(self):
        """CSV text should be parsed into a correct lookup dict."""
        from custom_components.flightid.airports import _parse_response

        text = (
            "Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
            ",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
            ",JFK Airport,KJFK,JFK,New York,US,40.64,-73.78,13\n"
        )
        result = _parse_response(text)

        assert result["EGLL"] == ("Heathrow", "London", "GB")
        assert result["KJFK"] == ("JFK Airport", "New York", "US")

    def test_skips_empty_lines(self):
        """Empty lines should be skipped without error."""
        from custom_components.flightid.airports import _parse_response

        text = (
            "\n\n"
            ",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
            "\n"
        )
        result = _parse_response(text)
        assert "EGLL" in result

    def test_skips_missing_icao(self):
        """Rows without ICAO codes should be skipped."""
        from custom_components.flightid.airports import _parse_response

        # Note: no header row — _parse_response processes all lines
        text = ",Some Airport,,,City,US,0,0,0\n"  # empty ICAO at index 2
        result = _parse_response(text)
        assert result == {}

    def test_skips_short_lines(self):
        """Lines with fewer than 9 columns should be skipped."""
        from custom_components.flightid.airports import _parse_response

        text = "EGLL,Heathrow,EGLL"  # only 3 columns
        result = _parse_response(text)
        assert result == {}

    def test_strips_whitespace(self):
        """Field values should be stripped of whitespace."""
        from custom_components.flightid.airports import _parse_response

        text = "Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
        text += ",  Heathrow  ,  EGLL  , LHR ,  London  ,  GB  , 51.47 , -0.46 , 83\n"
        result = _parse_response(text)
        assert result["EGLL"] == ("Heathrow", "London", "GB")


class TestDecompress:
    """Tests for the gzip decompression helper."""

    def test_plain_text(self):
        """Plain text should pass through unchanged."""
        from custom_components.flightid.airports import _decompress

        raw = b"Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
        result = _decompress(raw)
        assert isinstance(result, str)
        assert "Code" in result

    def test_gzip_compressed(self):
        """Gzip-compressed data should be decompressed."""
        import gzip

        from custom_components.flightid.airports import _decompress

        original = "Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
        compressed = gzip.compress(original.encode("utf-8-sig"))
        result = _decompress(compressed)
        assert "Code" in result


class TestSerializeData:
    """Tests for cache serialization helpers."""

    def test_serialize_deserialize_roundtrip(self):
        """Serializing and deserializing should preserve data."""
        from custom_components.flightid.airports import (
            _deserialize_data,
            _serialize_data,
        )

        original = {
            "EGLL": ("Heathrow", "London", "GB"),
            "KJFK": ("JFK Airport", "New York", "US"),
        }
        serialized = _serialize_data(original)
        deserialized = _deserialize_data(serialized)
        assert deserialized == original


class TestCaching:
    """Tests for ETag-based caching behaviour."""

    def _make_mock_response(
        self,
        status_code: int = 200,
        content: bytes | None = None,
        etag: str | None = None,
    ) -> MagicMock:
        """Create a mock requests.Response."""
        if content is None:
            content = b""
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = content
        resp.raise_for_status = MagicMock()
        resp.headers = {}
        if etag:
            resp.headers["ETag"] = f'"{etag}"'
        return resp

    def _write_cache(
        self,
        tmp_path: str,
        data: dict,
        etag: str | None = "test-etag",
    ) -> str:
        """Write a cache file and return its path."""
        path = os.path.join(tmp_path, "airports.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "data": {k: list(v) for k, v in data.items()},
                    "etag": etag,
                    "fetched_at": int(time.time()),
                },
                fh,
            )
        return path



    def test_cache_miss_200(self, tmp_path, monkeypatch):
        """When server returns 200, data should be fetched and cached."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )
        # Write old cache with different data
        old_cache = {"ZZZZ": ("Old Airport", "Nowhere", "XX")}
        cache_path = self._write_cache(tmp_path, old_cache)

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", cache_path
        )

        new_csv = (
            b",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
        )
        mock_resp = self._make_mock_response(
            status_code=200, content=new_csv, etag="new-etag"
        )

        with patch("requests.get", return_value=mock_resp):
            result = _fetch_airport_lookup()

        assert result == {"EGLL": ("Heathrow", "London", "GB")}
        # Verify cache was updated
        with open(cache_path, "r") as fh:
            saved = json.load(fh)
        assert saved["etag"] == "new-etag"
        assert "EGLL" in saved["data"]
        assert "ZZZZ" not in saved["data"]

    def test_stale_cache_ttl(self, tmp_path, monkeypatch):
        """When cache file is older than 7 days and no ETag, should re-fetch."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )

        old_cache = {"ZZZZ": ("Old Airport", "Nowhere", "XX")}
        cache_path = self._write_cache(tmp_path, old_cache, etag=None)

        # Make the cache file stale (> 7 days old)
        stale_time = int(time.time()) - (8 * 24 * 3600)
        with open(cache_path, "r") as fh:
            info = json.load(fh)
        info["fetched_at"] = stale_time
        with open(cache_path, "w") as fh:
            json.dump(info, fh)

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", cache_path
        )

        new_csv = (
            b"Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
            b",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
        )
        mock_resp = self._make_mock_response(
            status_code=200, content=new_csv, etag="fresh-etag"
        )

        with patch("requests.get", return_value=mock_resp):
            result = _fetch_airport_lookup()

        assert result == {"EGLL": ("Heathrow", "London", "GB")}

    def test_network_error_fallback(self, tmp_path, monkeypatch):
        """When network fails, should fall back to cached data."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )

        cached = {"EGLL": ("Heathrow", "London", "GB")}
        cache_path = self._write_cache(tmp_path, cached)

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", cache_path
        )

        import requests as requests_mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests_mod.ConnectionError(
            "Connection refused"
        )

        with patch("requests.get", return_value=mock_resp):
            result = _fetch_airport_lookup()

        assert result == cached

    def test_network_error_no_cache(self, monkeypatch):
        """When network fails and no cache, should return empty dict."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", None
        )

        import requests as requests_mod

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests_mod.ConnectionError(
            "Connection refused"
        )

        with patch("requests.get", return_value=mock_resp):
            result = _fetch_airport_lookup()

        assert result == {}

    def test_no_cache_path(self, monkeypatch):
        """When CACHE_PATH is None, should always fetch (no file I/O)."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", None
        )

        new_csv = (
            b"Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
            b",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
        )
        mock_resp = self._make_mock_response(
            status_code=200, content=new_csv, etag="no-cache-etag"
        )

        with patch("requests.get", return_value=mock_resp) as mock_get:
            result = _fetch_airport_lookup()

        assert result == {"EGLL": ("Heathrow", "London", "GB")}
        # Should have made a request without If-None-Match header
        assert "If-None-Match" not in mock_get.call_args[1]["headers"]

    def test_cache_path_none_no_file_ops(self, tmp_path, monkeypatch):
        """When CACHE_PATH is None, _save_cache should do nothing."""
        from custom_components.flightid.airports import _save_cache

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", None
        )

        # Should not raise, even with non-existent directory
        _save_cache({"EGLL": ("Heathrow", "London", "GB")}, "etag")

    def test_get_cache_info_missing_file(self, monkeypatch):
        """_get_cache_info should return None when cache file doesn't exist."""
        from custom_components.flightid.airports import _get_cache_info

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH",
            "/nonexistent/path/cache.json",
        )
        assert _get_cache_info() is None

    def test_get_cache_info_invalid_json(self, tmp_path, monkeypatch):
        """_get_cache_info should return None for invalid JSON."""
        from custom_components.flightid.airports import _get_cache_info

        path = os.path.join(tmp_path, "invalid.json")
        with open(path, "w") as fh:
            fh.write("not json")

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", path
        )
        assert _get_cache_info() is None

    def test_etag_stripped_of_quotes(self, tmp_path, monkeypatch):
        """ETag headers with surrounding quotes should be stripped."""
        from custom_components.flightid.airports import (
            _fetch_airport_lookup,
        )

        cached = {"ZZZZ": ("Old", "Nowhere", "XX")}
        cache_path = self._write_cache(tmp_path, cached, etag="old-etag")

        monkeypatch.setattr(
            "custom_components.flightid.airports.CACHE_PATH", cache_path
        )

        new_csv = (
            b"Code,Name,ICAO,IATA,Location,CountryISO2,Latitude,Longitude,AltitudeFeet\n"
            b",Heathrow,EGLL,LHR,London,GB,51.47,-0.46,83\n"
        )
        # Server sends ETag with quotes (standard HTTP format)
        mock_resp = self._make_mock_response(
            status_code=200, content=new_csv, etag='dGVzdC1ldGFn'
        )

        with patch("requests.get", return_value=mock_resp) as mock_get:
            _fetch_airport_lookup()

        # Verify saved ETag has quotes stripped
        with open(cache_path, "r") as fh:
            saved = json.load(fh)
        assert saved["etag"] == "dGVzdC1ldGFn"
