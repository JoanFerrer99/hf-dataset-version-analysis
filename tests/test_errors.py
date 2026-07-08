"""
Tests unitaris per a `notebooks/errors.py`.

Cobreixen:
  1. `with_retry` reintenta amb backoff davant 429/errors transitoris, però
     NO reintenta errors definitius (403, 404), i esgota els reintents
     correctament.
  2. `classify_error` classifica excepcions en categories semàntiques.
  3. `append_failure_row` escriu files estructurades amb capçalera.

Cap d'aquests tests fa crides reals a l'API de Hugging Face ni espera temps
real (s'injecten `sleep_fn`/`jitter_fn` fake a `with_retry`).
"""

import csv

import httpx
import pytest
from huggingface_hub.utils import HfHubHTTPError

import errors
from errors import ErrorCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_http_error(status_code: int, message: str = "boom") -> HfHubHTTPError:
    """Construeix un HfHubHTTPError real amb un status code concret."""
    request = httpx.Request("GET", "https://huggingface.co/api/datasets/foo/refs")
    response = httpx.Response(status_code, request=request)
    return HfHubHTTPError(message, response=response)


class _RecordingClock:
    """Substitut fake de time.sleep que enregistra les esperes sense esperar."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def no_jitter() -> float:
    return 0.0


# ---------------------------------------------------------------------------
# with_retry
# ---------------------------------------------------------------------------

class TestWithRetry:
    def test_succeeds_immediately_without_retrying(self):
        calls = []

        def fn():
            calls.append(1)
            return "ok"

        clock = _RecordingClock()
        result = errors.with_retry(fn, sleep_fn=clock, jitter_fn=no_jitter)

        assert result == "ok"
        assert len(calls) == 1
        assert clock.waits == []

    def test_succeeds_after_transient_429s(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise make_http_error(429)
            return "ok"

        clock = _RecordingClock()
        result = errors.with_retry(
            flaky, max_retries=5, base_wait_s=10, max_wait_s=120,
            sleep_fn=clock, jitter_fn=no_jitter,
        )

        assert result == "ok"
        assert attempts["n"] == 3
        # Backoff exponencial: 10s abans del 2n intent, 20s abans del 3r.
        assert clock.waits == [10, 20]

    def test_raises_after_exhausting_max_retries_on_429(self):
        def always_rate_limited():
            raise make_http_error(429)

        clock = _RecordingClock()
        with pytest.raises(HfHubHTTPError) as exc_info:
            errors.with_retry(
                always_rate_limited, max_retries=3, base_wait_s=1, max_wait_s=10,
                sleep_fn=clock, jitter_fn=no_jitter,
            )

        assert exc_info.value.response.status_code == 429
        # 3 intents -> només 2 esperes entremig (no s'espera després de l'últim).
        assert len(clock.waits) == 2

    def test_does_not_retry_on_403(self):
        calls = []

        def gated():
            calls.append(1)
            raise make_http_error(403)

        clock = _RecordingClock()
        with pytest.raises(HfHubHTTPError) as exc_info:
            errors.with_retry(gated, max_retries=5, sleep_fn=clock, jitter_fn=no_jitter)

        assert exc_info.value.response.status_code == 403
        assert len(calls) == 1  # cap reintent
        assert clock.waits == []

    def test_does_not_retry_on_404(self):
        def missing():
            raise make_http_error(404)

        clock = _RecordingClock()
        with pytest.raises(HfHubHTTPError):
            errors.with_retry(missing, sleep_fn=clock, jitter_fn=no_jitter)

        assert clock.waits == []

    def test_retries_transient_network_errors(self):
        attempts = {"n": 0}

        def flaky_network():
            attempts["n"] += 1
            if attempts["n"] < 2:
                request = httpx.Request("GET", "https://huggingface.co/")
                raise httpx.ConnectTimeout("timed out", request=request)
            return "ok"

        clock = _RecordingClock()
        result = errors.with_retry(
            flaky_network, max_retries=3, base_wait_s=5, sleep_fn=clock, jitter_fn=no_jitter
        )

        assert result == "ok"
        assert clock.waits == [5]

    def test_backoff_is_capped_at_max_wait_s(self):
        def always_rate_limited():
            raise make_http_error(429)

        clock = _RecordingClock()
        with pytest.raises(HfHubHTTPError):
            errors.with_retry(
                always_rate_limited, max_retries=6, base_wait_s=10, max_wait_s=25,
                sleep_fn=clock, jitter_fn=no_jitter,
            )

        # 10 -> 20 -> capped at 25 -> capped at 25 -> capped at 25
        assert clock.waits == [10, 20, 25, 25, 25]

    def test_jitter_is_added_to_each_wait(self):
        def always_rate_limited():
            raise make_http_error(429)

        clock = _RecordingClock()
        with pytest.raises(HfHubHTTPError):
            errors.with_retry(
                always_rate_limited, max_retries=2, base_wait_s=10,
                sleep_fn=clock, jitter_fn=lambda: 0.5,
            )

        assert clock.waits == [10.5]


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------

class TestClassifyError:
    @pytest.mark.parametrize(
        "status_code,expected",
        [
            (429, ErrorCategory.RATE_LIMITED),
            (403, ErrorCategory.ACCESS_RESTRICTED),
            (404, ErrorCategory.NOT_FOUND),
            (500, ErrorCategory.UNKNOWN),
        ],
    )
    def test_http_status_codes(self, status_code, expected):
        exc = make_http_error(status_code)
        assert errors.classify_error(exc) == expected

    def test_timeout_is_transient(self):
        request = httpx.Request("GET", "https://huggingface.co/")
        exc = httpx.ConnectTimeout("timed out", request=request)
        assert errors.classify_error(exc) == ErrorCategory.TRANSIENT

    def test_connection_error_is_transient(self):
        request = httpx.Request("GET", "https://huggingface.co/")
        exc = httpx.ConnectError("connection refused", request=request)
        assert errors.classify_error(exc) == ErrorCategory.TRANSIENT

    def test_unrelated_exception_is_unknown(self):
        assert errors.classify_error(ValueError("something else")) == ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# append_failure_row
# ---------------------------------------------------------------------------

class TestFailureLog:
    def test_append_failure_row_creates_header_once(self, tmp_path):
        path = tmp_path / "failures.csv"

        errors.append_failure_row(
            path, dataset_id="org/ds-1", category=ErrorCategory.RATE_LIMITED,
            message="429 Too Many Requests" * 30, retries_attempted=5, source="sampling",
        )
        errors.append_failure_row(
            path, dataset_id="org/ds-2", category=ErrorCategory.ACCESS_RESTRICTED,
            message="403 gated", retries_attempted=0, source="full_scan",
        )

        content = path.read_text(encoding="utf-8").splitlines()
        assert content[0].split(",") == errors.FAILURE_LOG_FIELDS
        assert len(content) == 3  # header + 2 rows

        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert rows[0]["dataset_id"] == "org/ds-1"
        assert rows[0]["error_category"] == "rate_limited"
        assert len(rows[0]["error_message"]) <= 500
        assert rows[1]["dataset_id"] == "org/ds-2"
        assert rows[1]["source"] == "full_scan"
