from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from itertools import islice
from logging import getLogger
from pprint import pformat
from typing import Any, Final

import requests
from bs4 import BeautifulSoup
from requests import Response, Session

from custom_components.bcnn.exceptions import (
    BCNNAuthError,
    BCNNConnectionError,
    BCNNParseError,
)
from custom_components.bcnn.helpers import convert_period_to_date

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
REQUEST_TIMEOUT = 30


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
    VERSION: Final[str] = "0.0.1"

    def __init__(self, login: str, password: str) -> None:
        self._session: Session | None = None
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

    @property
    def session(self) -> Session:
        if not self._session or self.session_is_expired():
            self._session = Session()
            self._session.headers = HEADERS_HTML
            self.authenticate()
        return self._session

    def session_is_expired(self) -> bool:
        if self.start_session and self.start_session + 1800 > datetime.now().timestamp():
            return False
        return True

    def get_accounts(self) -> dict[str, Any]:
        """Возвращает список лицевых счетов из личного кабинета.

        Пример ответа:
        {'code': 0,
         'data': {'accountInfo': {'accounts': [123456789, 987654321],
                                  'occ': 123456789,
                                  'view': 'few'},
                  'errors': []},
         'message': 'Данные успешно получены'}
        """
        json_data = {"data": {}, "function": "getAccountInfo"}
        try:
            response: Response = self.session.post(
                f"{self.base_url}/api/v1/cabinet/querydata",
                headers=HEADERS_JSON,
                json=json_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка запроса getAccountInfo: {exc}") from exc

        try:
            payload = response.json()
        except Exception as exc:
            LOGGER.error("Не удалось разобрать ответ getAccountInfo: %s\nТело ответа: %.500s", exc, response.text)
            raise BCNNConnectionError(f"Неверный формат ответа getAccountInfo: {exc}") from exc

        LOGGER.debug("getAccountInfo ответ: %s", payload)
        if payload.get("errors"):
            errors = payload["errors"]
            LOGGER.warning("API вернул ошибки getAccountInfo: %s", errors)
            raise BCNNConnectionError(f"Ошибка API: {errors}")

        return payload

    def authenticate(self) -> None:
        try:
            auth_page = self._session.get(
                f"{self.base_url}/node/4?destination=/node/4", timeout=REQUEST_TIMEOUT
            )
            auth_page.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Не удалось загрузить страницу авторизации: {exc}") from exc

        soup = BeautifulSoup(auth_page.text, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "авторизация")

        auth_data = {
            "name": self.login,
            "pass": self.password,
            "form_build_id": self.form_build_id,
            "form_id": "user_login_form",
            "op": "Войти",
        }
        try:
            self._session.post(
                f"{self.base_url}/node/4?destination=/node/4",
                data=auth_data,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка при отправке формы авторизации: {exc}") from exc

        if "Drupal.visitor.autologout_login" not in self._session.cookies:
            raise BCNNAuthError("Неверный логин или пароль")

        self.start_session = int(self._session.cookies.get("Drupal.visitor.autologout_login"))
        LOGGER.info("Успешная авторизация.")

    def navigate_to_readings(self) -> None:
        try:
            response = self.session.get(f"{self.base_url}/readings", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Не удалось загрузить страницу показаний: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "/readings")
        self.form_token = _require_input(soup, "form_token", "/readings")
        LOGGER.info("Загружена форма передачи показаний.")

    def select_account(self, account_number: str) -> None:
        account_data = {
            "account_number": account_number,
            "find_account": "OK",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form",
        }
        try:
            response = self.session.post(
                f"{self.base_url}/readings", data=account_data, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка при выборе аккаунта {account_number}: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "select_account")
        self.form_token = _require_input(soup, "form_token", "select_account")
        LOGGER.info("Аккаунт %s выбран.", account_number)

    def change_readings_form(self, account_number: str) -> Response:
        readings_data = {
            "account_number": account_number,
            "op": "Изменить показания",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form",
        }
        try:
            response = self.session.post(
                f"{self.base_url}/readings", data=readings_data, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка при открытии формы показаний: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = _require_input(soup, "form_build_id", "change_readings_form")
        self.form_token = _require_input(soup, "form_token", "change_readings_form")
        LOGGER.info("Форма для ввода показаний загружена.")
        return response

    def enter_readings(self, account_number: str, readings: dict[str, str]) -> None:
        self.change_readings_form(account_number)

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
            response = self.session.post(
                f"{self.base_url}/readings", data=final_data, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка при отправке показаний: {exc}") from exc

        LOGGER.debug("Отправленные данные: %s", pformat(readings))
        if "распечатать" in response.text:
            LOGGER.info("Показания успешно переданы.")
        else:
            LOGGER.warning("Ответ сервера не содержит признака успешной передачи показаний.")

    def get_information_on_water_meters(self, account: str | int) -> list[dict[str, str]]:
        self.navigate_to_readings()
        self.select_account(str(account))
        response = self.change_readings_form(str(account))

        self.devices[str(account)] = set()
        soup = BeautifulSoup(response.text, "lxml")
        water_meters: list[dict[str, str]] = []

        for row in soup.find_all("tr"):
            columns = row.find_all("td")
            if not columns:
                continue

            device_type = columns[0].text.strip()
            device_number = columns[1].text.strip()
            prev_value = columns[3].text.strip()
            cur_value = columns[4].text.strip()
            amount_water = columns[5].text.strip()

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
                    "prev_value": prev_value,
                    "cur_value": cur_value,
                    "amount_water": amount_water,
                    "repr_number": repr_number,
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

    def send_meter_readings(
        self,
        account: str | int,
        readings: tuple[tuple[str, str], ...] | None = None,
    ) -> str:
        if not readings:
            readings = ()

        for device_number, value in readings:
            self.add_meter_reading(account, device_number, value)

        self.navigate_to_readings()
        self.select_account(str(account))
        readings_payload = {
            device.repr_number: device.send_value()
            for device in self.devices.get(str(account), set())
        }
        self.enter_readings(str(account), readings_payload)
        LOGGER.info("Показания переданы для аккаунта %s", account)
        return "Показания успешно переданы"

    def get_address(self, account: str | int) -> dict[str, Any]:
        occ = self._parse_account_number(account)
        json_data = {"function": "getAddress", "data": {"occ": occ}}
        try:
            response = self.session.post(
                f"{self.base_url}/api/v1/cabinet/querydata",
                json=json_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка запроса getAddress: {exc}") from exc
        return response.json()

    def get_chart_data(self, account: str | int) -> dict[str, Any]:
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
            response = self.session.post(
                f"{self.base_url}/api/v1/cabinet/querydata",
                json=json_data,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка запроса getChartData: {exc}") from exc
        return response.json()

    def add_meter_reading(self, account: str | int, device_number: str, value: str) -> None:
        for device in self.devices.get(str(account), set()):
            if device.device_number == device_number:
                device.new_value = value

    def get_bill(self, account: str | int) -> bytes:
        self.get_chart_data(account)
        try:
            response = self.session.get(f"{self.base_url}/to_payment_pdf", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка получения PDF: {exc}") from exc
        return response.content

    def get_charges(self, account: str | int) -> list[dict[str, Any]]:
        self.get_chart_data(account)

        try:
            response = self.session.get(f"{self.base_url}/payments", timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BCNNConnectionError(f"Ошибка загрузки страницы платежей: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
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
            current_period = dict(zip(column_names, first_row))
            period_col = next(
                (k for k, v in current_period.items() if convert_period_to_date(v) != date.today()),
                None,
            )
            if period_col:
                period["period"] = convert_period_to_date(current_period.pop(period_col))
            period.update(current_period)

            for row in batch[1:]:
                columns = [elem.text.strip() for elem in row.find_all("td")]
                period.setdefault("services", []).append(dict(zip(column_names, columns)))
            data.append(period)

        return data

    def get_current_payment(self, account: str | int) -> dict[str, Any]:
        payments = self.get_charges(account)
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
