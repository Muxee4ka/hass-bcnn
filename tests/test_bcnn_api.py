"""Tests for custom_components.bcnn.bcnn_api."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from bs4 import BeautifulSoup
import pytest
import requests

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

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _response(text: str = "", status: int = 200) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.text = text
    resp.status_code = status
    resp.content = text.encode("utf-8")
    resp.raise_for_status.return_value = None
    return resp


def _make_api(login: str = "user@example.com", password: str = "secret") -> BCNNApi:
    api = BCNNApi(login=login, password=password)
    api._session = MagicMock()
    # Set a fresh start_session so the session property doesn't trigger re-auth.
    api.start_session = int(datetime.now().timestamp())
    return api


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
        api = BCNNApi("u", "p")
        assert api.session_is_expired() is True

    def test_fresh(self) -> None:
        api = BCNNApi("u", "p")
        api.start_session = int(datetime.now().timestamp())
        assert api.session_is_expired() is False

    def test_stale(self) -> None:
        api = BCNNApi("u", "p")
        api.start_session = int(datetime.now().timestamp()) - 2000
        assert api.session_is_expired() is True


# ----------------------- authenticate -----------------------


class TestAuthenticate:
    def test_happy_path(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response(_fixture("auth_page.html"))
        api._session.post.return_value = _response("OK")
        api._session.cookies = {"Drupal.visitor.autologout_login": "1700000000"}

        api.authenticate()

        assert api.form_build_id == "form-AUTH123"
        assert api.start_session == 1700000000
        api._session.post.assert_called_once()

    def test_missing_cookie_raises_auth_error(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response(_fixture("auth_page.html"))
        api._session.post.return_value = _response("OK")
        api._session.cookies = {}

        with pytest.raises(BCNNAuthError):
            api.authenticate()

    def test_no_form_build_id_raises_parse_error(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response("<html><body>no form</body></html>")

        with pytest.raises(BCNNParseError, match="form_build_id"):
            api.authenticate()

    def test_network_error_wrapped(self) -> None:
        api = _make_api()
        api._session.get.side_effect = requests.ConnectionError("boom")

        with pytest.raises(BCNNConnectionError):
            api.authenticate()


# ----------------------- readings flow -----------------------


class TestReadingsFlow:
    def test_navigate_updates_tokens(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response(_fixture("readings_page.html"))

        api.navigate_to_readings()

        assert api.form_build_id == "form-READ456"
        assert api.form_token == "token-READ789"

    def test_select_account_posts_and_updates_tokens(self) -> None:
        api = _make_api()
        api.form_build_id = "stale-build"
        api.form_token = "stale-token"
        api._session.post.return_value = _response(_fixture("readings_page.html"))

        api.select_account("123456789")

        args, kwargs = api._session.post.call_args
        assert args[0].endswith("/readings")
        body = kwargs["data"]
        assert body["account_number"] == "123456789"
        assert body["find_account"] == "OK"
        assert body["form_build_id"] == "stale-build"
        assert body["form_token"] == "stale-token"
        # tokens are refreshed from the response
        assert api.form_build_id == "form-READ456"
        assert api.form_token == "token-READ789"

    def test_get_information_on_water_meters(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response(_fixture("readings_page.html"))
        api._session.post.return_value = _response(_fixture("readings_page.html"))

        meters = api.get_information_on_water_meters("123456789")

        assert len(meters) == 2
        cold = next(m for m in meters if m["device_type"] == "Холодная вода")
        assert cold["device_number"] == "12345678"
        assert cold["prev_value"] == "105.123"
        assert cold["cur_value"] == "110.456"
        assert cold["amount_water"] == "5.333"
        assert cold["repr_number"] == "cw_12345678"

        # devices cache is populated with formatter parsed from onchange
        cached = api.devices["123456789"]
        assert len(cached) == 2
        cold_device = next(d for d in cached if d.device_number == "12345678")
        assert cold_device.formatter == ("5", "3")

    def test_get_information_clears_devices_between_calls(self) -> None:
        api = _make_api()
        api._session.get.return_value = _response(_fixture("readings_page.html"))
        api._session.post.return_value = _response(_fixture("readings_page.html"))

        api.get_information_on_water_meters("123456789")
        first = {d.device_number for d in api.devices["123456789"]}
        api.get_information_on_water_meters("123456789")
        second = {d.device_number for d in api.devices["123456789"]}

        assert first == second  # no duplicates from a second call

    def test_enter_readings_logs_success_marker(self, caplog) -> None:
        api = _make_api()
        api._session.post.side_effect = [
            _response(_fixture("readings_page.html")),  # change_readings_form
            _response(_fixture("readings_submitted.html")),  # enter_readings
        ]
        with caplog.at_level("INFO", logger="custom_components.bcnn.bcnn_api"):
            api.enter_readings("123456789", {"cw_12345678": "00110.456"})
        assert any("успешно" in r.message for r in caplog.records)


# ----------------------- JSON endpoints -----------------------


class TestGetAccounts:
    def test_returns_payload(self) -> None:
        api = _make_api()
        resp = _response("{}")
        resp.json.return_value = {
            "code": 0,
            "data": {"accountInfo": {"accounts": [123, 456]}},
            "errors": [],
        }
        api._session.post.return_value = resp

        result = api.get_accounts()
        assert result["data"]["accountInfo"]["accounts"] == [123, 456]

    def test_errors_in_payload_raise_connection_error(self) -> None:
        api = _make_api()
        resp = _response("{}")
        resp.json.return_value = {"errors": ["something broke"]}
        api._session.post.return_value = resp

        with pytest.raises(BCNNConnectionError):
            api.get_accounts()

    def test_non_json_response_raises_connection_error(self) -> None:
        api = _make_api()
        resp = _response("oops")
        resp.json.side_effect = ValueError("not json")
        api._session.post.return_value = resp

        with pytest.raises(BCNNConnectionError):
            api.get_accounts()


# ----------------------- charges / current payment -----------------------


class TestGetCharges:
    def _prep_api(self) -> BCNNApi:
        api = _make_api()
        # get_chart_data POSTs JSON, get_charges GETs /payments. Mock both.
        chart_resp = _response("{}")
        chart_resp.json.return_value = {"data": {}}
        api._session.post.return_value = chart_resp
        api._session.get.return_value = _response(_fixture("payments_page.html"))
        return api

    def test_parses_periods_and_services(self) -> None:
        api = self._prep_api()
        charges = api.get_charges("123456789")

        # 3 periods × 1 service each
        assert len(charges) == 3
        periods = [c["period"] for c in charges]
        assert periods == sorted(periods)  # natural order from the page
        for period in charges:
            assert period["opening_balance"] in {"0.00", "200.00"}
            assert isinstance(period.get("services"), list)
            assert len(period["services"]) == 1

    def test_missing_table_raises_parse_error(self) -> None:
        api = self._prep_api()
        api._session.get.return_value = _response("<html><body>пусто</body></html>")
        with pytest.raises(BCNNParseError):
            api.get_charges("123456789")

    def test_current_payment_returns_latest_period(self) -> None:
        api = self._prep_api()
        current = api.get_current_payment("123456789")
        assert current["period"].month == 3  # март 2026 в фикстуре — самый поздний
        assert current["due_payment"] == "900.00"
