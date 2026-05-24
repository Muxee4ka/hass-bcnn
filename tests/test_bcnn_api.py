"""Tests for custom_components.bcnn.bcnn_api."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aioresponses import aioresponses
from bs4 import BeautifulSoup
import pytest

from custom_components.bcnn.bcnn_api import (
    BCNNApi,
    DeviceInfo,
    _require_input,
    batched,
    format_number,
)
from custom_components.bcnn.exceptions import (
    BCNNAuthError,
    BCNNConnectionError,
    BCNNParseError,
)


# aiohttp.ClientSession spins up a daemon thread for graceful shutdown that
# pytest-homeassistant-custom-component flags as "lingering" in its strict
# verify_cleanup autouse fixture. Override it in this module — the fixture is
# only useful for the HA-scenario tests that run inside a real HA event loop.
@pytest.fixture(autouse=True)
def verify_cleanup():
    yield


FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://lk.bcnn.ru"
AUTH_URL = f"{BASE}/node/4?destination=/node/4"
READINGS_URL = f"{BASE}/readings"
QUERYDATA_URL = f"{BASE}/api/v1/cabinet/querydata"
PAYMENTS_URL = f"{BASE}/payments"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _make_api(login: str = "user@example.com", password: str = "secret") -> BCNNApi:
    return BCNNApi(login=login, password=password)


def _mock_auth(mocked: aioresponses, *, with_cookie: bool = True) -> None:
    """Register the two requests authenticate() performs.

    aioresponses doesn't populate the real CookieJar from a mocked
    Set-Cookie header, so tests that need the cookie present should also
    patch BCNNApi._cookie via `_patch_auth_cookie(value)`.
    """
    mocked.get(AUTH_URL, body=_fixture("auth_page.html"))
    mocked.post(AUTH_URL, body="OK")


def _patch_auth_cookie(value: str | None):
    """Patch BCNNApi._cookie to return the given value for the session cookie."""
    return patch(
        "custom_components.bcnn.bcnn_api.BCNNApi._cookie",
        return_value=value,
    )


# ----------------------- pure helpers -----------------------


class TestFormatNumber:
    @pytest.mark.parametrize(
        ("value", "before", "after", "expected"),
        [
            (105.123, 5, 3, "00105.123"),
            (53.75, 5, 3, "00053.750"),
            (0, 5, 2, "00000.00"),
            (12345.6, 5, 2, "12345.60"),
            (1.5, 1, 1, "1.5"),
        ],
    )
    def test_format(self, value: float, before: int, after: int, expected: str) -> None:
        assert format_number(value, before, after) == expected


class TestDeviceInfo:
    """formatter is a tuple of *strings*; widths are len(parts), so ("12345", "678")
    means 5 digits before the dot and 3 after — total field width 5+3+1=9."""

    def test_send_value_picks_max(self) -> None:
        device = DeviceInfo(
            account_number="123",
            device_type="ХВС",
            device_number="A1",
            repr_number="cw_A1",
            prev_value="100",
            cur_value="110",
            amount_water="10",
            new_value="115",
            formatter=("12345", "678"),
        )
        assert device.send_value() == "00115.000"

    def test_send_value_handles_missing_new(self) -> None:
        device = DeviceInfo(
            account_number="123",
            device_type="ХВС",
            device_number="A1",
            repr_number="cw_A1",
            prev_value="100",
            cur_value="110",
            amount_water="10",
            new_value=None,
            formatter=("12345", "67"),
        )
        assert device.send_value() == "00110.00"

    def test_send_value_never_below_cur(self) -> None:
        device = DeviceInfo(
            account_number="123",
            device_type="ХВС",
            device_number="A1",
            repr_number="cw_A1",
            prev_value="100",
            cur_value="110",
            amount_water="10",
            new_value="50",  # ниже предыдущего — должно быть отброшено max()
            formatter=("12345", "678"),
        )
        assert device.send_value() == "00110.000"


class TestBatched:
    def test_batches(self) -> None:
        assert list(batched([1, 2, 3, 4, 5], 2)) == [(1, 2), (3, 4), (5,)]

    def test_empty(self) -> None:
        assert list(batched([], 3)) == []

    def test_invalid_n(self) -> None:
        with pytest.raises(ValueError):
            list(batched([1, 2, 3], 0))


class TestRequireInput:
    def test_returns_value(self) -> None:
        soup = BeautifulSoup('<form><input name="form_token" value="abc"></form>', "html.parser")
        assert _require_input(soup, "form_token", "ctx") == "abc"

    def test_raises_when_missing(self) -> None:
        soup = BeautifulSoup("<form></form>", "html.parser")
        with pytest.raises(BCNNParseError, match="form_token"):
            _require_input(soup, "form_token", "ctx")


class TestParseAccountNumber:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("123456789", 123456789),
            ("123-456-789", 123456789),
            ("ЛС № 123 456 789", 123456789),
            (123, 123),
        ],
    )
    def test_strips_non_digits(self, raw: str | int, expected: int) -> None:
        api = _make_api()
        assert api._parse_account_number(raw) == expected

    def test_no_digits_raises(self) -> None:
        api = _make_api()
        with pytest.raises(ValueError, match="не содержит цифр"):
            api._parse_account_number("abc")


class TestSessionIsExpired:
    def test_no_start_session(self) -> None:
        assert _make_api().session_is_expired() is True

    def test_fresh(self) -> None:
        api = _make_api()
        api.start_session = int(datetime.now().timestamp())
        assert api.session_is_expired() is False

    def test_stale(self) -> None:
        api = _make_api()
        api.start_session = int(datetime.now().timestamp()) - 2000
        assert api.session_is_expired() is True


# ----------------------- authenticate -----------------------


class TestAuthenticate:
    async def test_happy_path(self, authed_api: BCNNApi) -> None:
        # Force re-auth by invalidating the seeded start_session.
        authed_api.start_session = None
        with aioresponses() as mocked, _patch_auth_cookie("1700000000"):
            _mock_auth(mocked)
            mocked.post(
                QUERYDATA_URL,
                payload={
                    "code": 0,
                    "data": {"accountInfo": {"accounts": [1]}},
                    "errors": [],
                },
            )
            await authed_api.get_accounts()
        assert authed_api.form_build_id == "form-AUTH123"
        assert authed_api.start_session == 1700000000

    async def test_missing_cookie_raises_auth_error(self, authed_api: BCNNApi) -> None:
        authed_api.start_session = None
        with aioresponses() as mocked, _patch_auth_cookie(None):
            _mock_auth(mocked)

            with pytest.raises(BCNNAuthError):
                await authed_api.get_accounts()

    async def test_no_form_build_id_raises_parse_error(self, authed_api: BCNNApi) -> None:
        authed_api.start_session = None
        with aioresponses() as mocked:
            mocked.get(AUTH_URL, body="<html><body>no form</body></html>")

            with pytest.raises(BCNNParseError, match="form_build_id"):
                await authed_api.get_accounts()

    async def test_network_error_wrapped(self, authed_api: BCNNApi) -> None:
        authed_api.start_session = None
        with aioresponses() as mocked:
            mocked.get(AUTH_URL, exception=aiohttp.ClientConnectionError("boom"))

            with pytest.raises(BCNNConnectionError):
                await authed_api.get_accounts()


# ----------------------- readings flow -----------------------


@pytest.fixture
async def authed_api():
    """API with a fresh session and pre-set start_session, so _ensure_session
    skips re-auth. Tests below register their own /readings mocks."""
    api = _make_api()
    api._session = aiohttp.ClientSession()
    api.start_session = int(datetime.now().timestamp())
    yield api
    await api.close()


class TestReadingsFlow:
    async def test_navigate_updates_tokens(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.get(READINGS_URL, body=_fixture("readings_page.html"))

            await authed_api.navigate_to_readings()

        assert authed_api.form_build_id == "form-READ456"
        assert authed_api.form_token == "token-READ789"

    async def test_select_account_posts_and_updates_tokens(self, authed_api: BCNNApi) -> None:
        authed_api.form_build_id = "stale-build"
        authed_api.form_token = "stale-token"
        with aioresponses() as mocked:
            mocked.post(READINGS_URL, body=_fixture("readings_page.html"))

            await authed_api.select_account("123456789")

            req = next(iter(mocked.requests.values()))[0]
            body = dict(req.kwargs["data"])
            assert body["account_number"] == "123456789"
            assert body["find_account"] == "OK"
            assert body["form_build_id"] == "stale-build"
            assert body["form_token"] == "stale-token"

        assert authed_api.form_build_id == "form-READ456"
        assert authed_api.form_token == "token-READ789"

    async def test_get_information_on_water_meters(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.get(READINGS_URL, body=_fixture("readings_page.html"))
            # POSTed twice — select_account and change_readings_form.
            mocked.post(READINGS_URL, body=_fixture("readings_page.html"))
            mocked.post(READINGS_URL, body=_fixture("readings_page.html"))

            meters = await authed_api.get_information_on_water_meters("123456789")

        assert len(meters) == 2
        cold = next(m for m in meters if m["device_type"] == "Холодная вода")
        assert cold["device_number"] == "12345678"
        assert cold["prev_value"] == "105.123"
        assert cold["cur_value"] == "110.456"
        assert cold["amount_water"] == "5.333"
        assert cold["repr_number"] == "cw_12345678"

        cached = authed_api.devices["123456789"]
        assert len(cached) == 2
        cold_device = next(d for d in cached if d.device_number == "12345678")
        assert cold_device.formatter == ("5", "3")

    async def test_get_information_clears_devices_between_calls(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.get(READINGS_URL, body=_fixture("readings_page.html"), repeat=True)
            mocked.post(READINGS_URL, body=_fixture("readings_page.html"), repeat=True)

            await authed_api.get_information_on_water_meters("123456789")
            first = {d.device_number for d in authed_api.devices["123456789"]}
            await authed_api.get_information_on_water_meters("123456789")
            second = {d.device_number for d in authed_api.devices["123456789"]}

        assert first == second  # no duplicates from a second call

    async def test_enter_readings_logs_success_marker(self, authed_api: BCNNApi, caplog) -> None:
        with aioresponses() as mocked:
            # change_readings_form → readings_page.html, then enter_readings → submitted.html
            mocked.post(READINGS_URL, body=_fixture("readings_page.html"))
            mocked.post(READINGS_URL, body=_fixture("readings_submitted.html"))

            with caplog.at_level("INFO", logger="custom_components.bcnn.bcnn_api"):
                await authed_api.enter_readings("123456789", {"cw_12345678": "00110.456"})

        assert any("успешно" in r.message for r in caplog.records)


# ----------------------- JSON endpoints -----------------------


class TestGetAccounts:
    async def test_returns_payload(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.post(
                QUERYDATA_URL,
                payload={
                    "code": 0,
                    "data": {"accountInfo": {"accounts": [123, 456]}},
                    "errors": [],
                },
            )

            result = await authed_api.get_accounts()

        assert result["data"]["accountInfo"]["accounts"] == [123, 456]

    async def test_errors_in_payload_raise_connection_error(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.post(QUERYDATA_URL, payload={"errors": ["something broke"]})

            with pytest.raises(BCNNConnectionError):
                await authed_api.get_accounts()

    async def test_non_json_response_raises_connection_error(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.post(QUERYDATA_URL, body="oops", content_type="text/plain")

            with pytest.raises(BCNNConnectionError):
                await authed_api.get_accounts()


# ----------------------- charges / current payment -----------------------


def _mock_charges(mocked: aioresponses) -> None:
    """get_charges → get_chart_data POST + /payments GET."""
    mocked.post(QUERYDATA_URL, payload={"data": {}})
    mocked.get(PAYMENTS_URL, body=_fixture("payments_page.html"))


class TestGetCharges:
    async def test_parses_periods_and_services(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            _mock_charges(mocked)

            charges = await authed_api.get_charges("123456789")

        assert len(charges) == 3
        periods = [c["period"] for c in charges]
        assert periods == sorted(periods)
        for period in charges:
            assert period["opening_balance"] in {"0.00", "200.00"}
            assert isinstance(period.get("services"), list)
            assert len(period["services"]) == 1

    async def test_missing_table_raises_parse_error(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            mocked.post(QUERYDATA_URL, payload={"data": {}})
            mocked.get(PAYMENTS_URL, body="<html><body>пусто</body></html>")

            with pytest.raises(BCNNParseError):
                await authed_api.get_charges("123456789")

    async def test_current_payment_returns_latest_period(self, authed_api: BCNNApi) -> None:
        with aioresponses() as mocked:
            _mock_charges(mocked)

            current = await authed_api.get_current_payment("123456789")

        assert current["period"].month == 3
        assert current["due_payment"] == "900.00"
