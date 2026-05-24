from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import islice
import json
from logging import getLogger
from pathlib import Path
from pprint import pformat
import re
from typing import Any, Final

import aiohttp
from bs4 import BeautifulSoup

from custom_components.bcnn.exceptions import (
    BCNNAuthError,
    BCNNConnectionError,
    BCNNParseError,
)
from custom_components.bcnn.parsers import convert_period_to_date

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
HEADERS_HTML = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": USER_AGENT,
}
HEADERS_JSON = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}
LOGGER = getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
SESSION_COOKIE = "Drupal.visitor.autologout_login"


def _read_manifest_version() -> str:
    manifest = Path(__file__).parent / "manifest.json"
    try:
        return json.loads(manifest.read_text())["version"]
    except Exception:
        return "unknown"


def format_number(number: float, total_digits_before: int = 5, digits_after: int = 2) -> str:
    return f"{number:0{total_digits_before + digits_after + 1}.{digits_after}f}"


@dataclass(unsafe_hash=True)
class DeviceInfo:
    account_number: str
    device_type: str
    device_number: str
    repr_number: str
    prev_value: str
    cur_value: str
    amount_water: str
    new_value: str | None = None
    formatter: tuple[str, ...] = (5, 5)

    def send_value(self) -> str:
        value = max(
            float(self.new_value or 0),
            float(self.cur_value or 0),
            float(self.prev_value or 0),
        )
        return format_number(value, *[len(elem) for elem in self.formatter])


def batched(iterable: Any, n: int):
    if n < 1:
        raise ValueError("n must be at least one")
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch


def _require_input(soup: BeautifulSoup, name: str, context: str) -> str:
    tag = soup.find("input", {"name": name})
    if tag is None:
        raise BCNNParseError(f"Не найден input[name={name!r}] на странице {context!r}")
    return tag["value"]


class BCNNApi:
    """Async client for lk.bcnn.ru.

    A single ClientSession holds the Drupal session cookie. Re-auth happens
    automatically once `start_session` falls outside the 30-minute window.
    """

    VERSION: Final[str] = _read_manifest_version()

    def __init__(self, login: str, password: str) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._auth_lock = asyncio.Lock()
        self.login = login
        self.password = password
        self.base_url = "https://lk.bcnn.ru"
        self.form_build_id: str | None = None
        self.form_token: str | None = None
        self.start_session: int | None = None
        self.devices: dict[str, set[DeviceInfo]] = {}

    def _parse_account_number(self, account: str | int) -> int:
        digits = re.sub(r"\D", "", str(account))
        if not digits:
            raise ValueError(f"Номер лицевого счёта {account!r} не содержит цифр")
        return int(digits)

    def session_is_expired(self) -> bool:
        return not (self.start_session and self.start_session + 1800 > datetime.now().timestamp())

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create the ClientSession + authenticate on first use / after expiry."""
        async with self._auth_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(headers=HEADERS_HTML, timeout=REQUEST_TIMEOUT)
                self.start_session = None
            if self.session_is_expired():
                await self._authenticate()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def _cookie(self, name: str) -> str | None:
        if not self._session:
            return None
        for cookie in self._session.cookie_jar:
            if cookie.key == name:
                return cookie.value
        return None

    async def _authenticate(self) -> None:
        assert self._session is not None
        try:
            async with self._session.get(
                f"{self.base_url}/node/4?destination=/node/4"
            ) as auth_page:
                auth_page.raise_for_status()
                body = await auth_page.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Не удалось загрузить страницу авторизации: {exc}") from exc

        soup = BeautifulSoup(body, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "авторизация")

        auth_data = {
            "name": self.login,
            "pass": self.password,
            "form_build_id": self.form_build_id,
            "form_id": "user_login_form",
            "op": "Войти",
        }
        try:
            async with self._session.post(
                f"{self.base_url}/node/4?destination=/node/4", data=auth_data
            ) as resp:
                await resp.read()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка при отправке формы авторизации: {exc}") from exc

        autologout = self._cookie(SESSION_COOKIE)
        if not autologout:
            raise BCNNAuthError("Неверный логин или пароль")

        self.start_session = int(autologout)
        LOGGER.info("Успешная авторизация.")

    async def get_accounts(self) -> dict[str, Any]:
        """Returns the list of personal accounts the login has access to.

        Example response:
        {'code': 0,
         'data': {'accountInfo': {'accounts': [123456789, 987654321],
                                  'occ': 123456789,
                                  'view': 'few'},
                  'errors': []},
         'message': 'Данные успешно получены'}
        """
        session = await self._ensure_session()
        json_data = {"data": {}, "function": "getAccountInfo"}
        try:
            async with session.post(
                f"{self.base_url}/api/v1/cabinet/querydata",
                headers=HEADERS_JSON,
                json=json_data,
            ) as response:
                response.raise_for_status()
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError, json.JSONDecodeError) as exc:
                    body = await response.text()
                    LOGGER.error(
                        "Не удалось разобрать ответ getAccountInfo: %s\nТело: %.500s",
                        exc,
                        body,
                    )
                    raise BCNNConnectionError(
                        f"Неверный формат ответа getAccountInfo: {exc}"
                    ) from exc
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка запроса getAccountInfo: {exc}") from exc

        LOGGER.debug("getAccountInfo ответ: %s", payload)
        if payload.get("errors"):
            errors = payload["errors"]
            LOGGER.warning("API вернул ошибки getAccountInfo: %s", errors)
            raise BCNNConnectionError(f"Ошибка API: {errors}")

        return payload

    async def navigate_to_readings(self) -> None:
        session = await self._ensure_session()
        try:
            async with session.get(f"{self.base_url}/readings") as response:
                response.raise_for_status()
                body = await response.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Не удалось загрузить страницу показаний: {exc}") from exc

        soup = BeautifulSoup(body, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "/readings")
        self.form_token = _require_input(soup, "form_token", "/readings")
        LOGGER.info("Загружена форма передачи показаний.")

    async def select_account(self, account_number: str) -> None:
        session = await self._ensure_session()
        account_data = {
            "account_number": account_number,
            "find_account": "OK",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form",
        }
        try:
            async with session.post(f"{self.base_url}/readings", data=account_data) as response:
                response.raise_for_status()
                body = await response.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(
                f"Ошибка при выборе аккаунта {account_number}: {exc}"
            ) from exc

        soup = BeautifulSoup(body, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "select_account")
        self.form_token = _require_input(soup, "form_token", "select_account")
        LOGGER.info("Аккаунт %s выбран.", account_number)

    async def change_readings_form(self, account_number: str) -> str:
        session = await self._ensure_session()
        readings_data = {
            "account_number": account_number,
            "op": "Изменить показания",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form",
        }
        try:
            async with session.post(f"{self.base_url}/readings", data=readings_data) as response:
                response.raise_for_status()
                body = await response.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка при открытии формы показаний: {exc}") from exc

        soup = BeautifulSoup(body, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "change_readings_form")
        self.form_token = _require_input(soup, "form_token", "change_readings_form")
        LOGGER.info("Форма для ввода показаний загружена.")
        return body

    async def enter_readings(self, account_number: str, readings: dict[str, str]) -> None:
        await self.change_readings_form(account_number)
        session = await self._ensure_session()

        final_data = {
            "account_number": account_number,
            **readings,
            "ok": "1",
            "op": "Передать показания",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form",
        }
        try:
            async with session.post(f"{self.base_url}/readings", data=final_data) as response:
                response.raise_for_status()
                body = await response.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка при отправке показаний: {exc}") from exc

        LOGGER.debug("Отправленные данные: %s", pformat(readings))
        if "распечатать" in body:
            LOGGER.info("Показания успешно переданы.")
        else:
            LOGGER.warning("Ответ сервера не содержит признака успешной передачи показаний.")

    async def get_information_on_water_meters(self, account: str | int) -> list[dict[str, str]]:
        await self.navigate_to_readings()
        await self.select_account(str(account))
        body = await self.change_readings_form(str(account))

        self.devices[str(account)] = set()
        soup = BeautifulSoup(body, "lxml")
        water_meters: list[dict[str, str]] = []

        for row in soup.find_all("tr"):
            columns = row.find_all("td")
            if not columns:
                continue

            device_type = columns[0].text.strip()
            device_number = columns[1].text.strip()
            # columns[2] is the meter's verification due date — 'MM/YY' in
            # real cabinets, e.g. '09/28' (calibration expires Sept 2028).
            verification_date_raw = columns[2].text.strip()
            prev_value = columns[3].text.strip()
            cur_value = columns[4].text.strip()
            # Real cabinets only have 6 columns; older versions had a 7th
            # 'amount' column. Fall back gracefully if it's not there.
            amount_water = columns[5].text.strip() if len(columns) > 5 else ""

            input_tag = row.find("input", {"name": re.compile(".+")})
            repr_number = input_tag["name"] if input_tag else None

            cabinet_change = row.find("input", {"onchange": re.compile(".+")})
            if cabinet_change is None:
                raise BCNNParseError(
                    f"Не найден input[onchange] для счётчика {device_number!r} — структура сайта изменилась"
                )
            match = re.match(r"cabinet_change\((\d+\.\d+)", cabinet_change["onchange"])
            if match is None:
                raise BCNNParseError(
                    f"Неожиданный формат onchange для счётчика {device_number!r}: {cabinet_change['onchange']!r}"
                )
            formatter = tuple(match.group(1).split("."))

            water_meters.append(
                {
                    "device_type": device_type,
                    "device_number": device_number,
                    "verification_date_raw": verification_date_raw,
                    "prev_value": prev_value,
                    "cur_value": cur_value,
                    "amount_water": amount_water,
                    "repr_number": repr_number,
                    "formatter": formatter,
                }
            )
            self.devices[str(account)].add(
                DeviceInfo(
                    str(account),
                    device_type,
                    device_number,
                    repr_number,
                    prev_value,
                    cur_value,
                    amount_water,
                    formatter=formatter,
                )
            )
        return water_meters

    async def send_meter_readings(
        self,
        account: str | int,
        readings: tuple[tuple[str, str], ...] | None = None,
    ) -> str:
        if not readings:
            readings = ()

        for device_number, value in readings:
            self.add_meter_reading(account, device_number, value)

        await self.navigate_to_readings()
        await self.select_account(str(account))
        readings_payload = {
            device.repr_number: device.send_value()
            for device in self.devices.get(str(account), set())
        }
        await self.enter_readings(str(account), readings_payload)
        LOGGER.info("Показания переданы для аккаунта %s", account)
        return "Показания успешно переданы"

    async def get_address(self, account: str | int) -> dict[str, Any]:
        session = await self._ensure_session()
        occ = self._parse_account_number(account)
        json_data = {"function": "getAddress", "data": {"occ": occ}}
        try:
            async with session.post(
                f"{self.base_url}/api/v1/cabinet/querydata", json=json_data
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка запроса getAddress: {exc}") from exc

    async def get_chart_data(self, account: str | int) -> dict[str, Any]:
        session = await self._ensure_session()
        today = date.today()
        prev_month = today - timedelta(days=today.day)
        occ = self._parse_account_number(account)
        json_data = {
            "function": "getChartData",
            "data": {
                "occ": occ,
                "beginPeriod": prev_month.strftime("%Y%m"),
                "endPeriod": today.strftime("%Y%m"),
            },
        }
        try:
            async with session.post(
                f"{self.base_url}/api/v1/cabinet/querydata", json=json_data
            ) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка запроса getChartData: {exc}") from exc

    def add_meter_reading(self, account: str | int, device_number: str, value: str) -> None:
        for device in self.devices.get(str(account), set()):
            if device.device_number == device_number:
                device.new_value = value

    async def get_bill(self, account: str | int) -> bytes:
        await self.get_chart_data(account)
        session = await self._ensure_session()
        try:
            async with session.get(f"{self.base_url}/to_payment_pdf") as response:
                response.raise_for_status()
                return await response.read()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка получения PDF: {exc}") from exc

    async def get_charges(self, account: str | int) -> list[dict[str, Any]]:
        await self.get_chart_data(account)
        session = await self._ensure_session()
        try:
            async with session.get(f"{self.base_url}/payments") as response:
                response.raise_for_status()
                body = await response.text()
        except aiohttp.ClientError as exc:
            raise BCNNConnectionError(f"Ошибка загрузки страницы платежей: {exc}") from exc

        soup = BeautifulSoup(body, "html.parser")
        table = soup.find("table", {"data-drupal-selector": "edit-table1"})
        if table is None:
            raise BCNNParseError("Таблица начислений не найдена — структура сайта изменилась")

        data: list[dict[str, Any]] = []
        translation_mapper = {
            "Период / Услуга": "period_or_service",
            "Входящее сальдо": "opening_balance",
            "Начислено": "accrued",
            "Оплачено": "paid",
            "К оплате": "due_payment",
        }

        all_rows = table.find_all("tr")
        if len(all_rows) < 2:
            return data

        column_names = [
            translation_mapper.get(elem.text.strip(), elem.text.strip())
            for elem in all_rows[0].find_all("th")
        ]
        LOGGER.debug("Column names: %s", column_names)

        data_rows = all_rows[1:]
        count_rows = len(data_rows)
        if count_rows == 0:
            return data

        for batch in batched(data_rows, max(1, count_rows // 3)):
            period: dict[str, Any] = {}
            first_row = [elem.text.strip() for elem in batch[0].find_all("td")]
            current_period = dict(zip(column_names, first_row, strict=False))
            period_col = next(
                (k for k, v in current_period.items() if convert_period_to_date(v) != date.today()),
                None,
            )
            if period_col:
                period["period"] = convert_period_to_date(current_period.pop(period_col))
            period.update(current_period)

            for row in batch[1:]:
                columns = [elem.text.strip() for elem in row.find_all("td")]
                period.setdefault("services", []).append(
                    dict(zip(column_names, columns, strict=False))
                )
            data.append(period)

        return data

    async def get_current_payment(self, account: str | int) -> dict[str, Any]:
        payments = await self.get_charges(account)
        LOGGER.debug(payments)
        if not payments:
            return {}

        periods = [p.get("period") for p in payments if p.get("period")]
        if not periods:
            return {}

        latest_period = max(periods)
        for payment in payments:
            if payment.get("period") == latest_period:
                return payment
        return payments[0]
