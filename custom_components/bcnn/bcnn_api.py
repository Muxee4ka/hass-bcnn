import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from itertools import islice
from logging import getLogger
from time import sleep
from typing import Union, Tuple, Dict, Optional, List, Set, Any, Final
from pprint import pformat

from bs4 import BeautifulSoup
from requests import Response, Session

from custom_components.bcnn.helpers import convert_period_to_date

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
HEADERS_HTML = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": USER_AGENT,
}
HEADERS_JSON = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "User-Agent": USER_AGENT,
}
LOGGER = getLogger(__name__)


def format_number(number, total_digits_before=5, digits_after=2):
    formatted_number = f"{number:0{total_digits_before + digits_after + 1}.{digits_after}f}"
    return formatted_number


@dataclass(unsafe_hash=True)
class DeviceInfo:
    account_number: str
    device_type: str
    device_number: str
    repr_number: str
    prev_value: str
    cur_value: str
    amount_water: str
    new_value: str = None
    formatter: tuple = (5, 5)

    def send_value(self):
        return format_number(max(float(self.new_value or 0), float(self.cur_value or 0), float(self.prev_value or 0)),
                             *[len(elem) for elem in self.formatter])


def batched(iterable, n):
    # batched('ABCDEFG', 3) → ABC DEF G
    if n < 1:
        raise ValueError("n must be at least one")
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch


class BCNNApi:
    VERSION: Final[str] = "0.0.1"

    def __init__(self, login, password):
        self._session = None
        self.login = login
        self.password = password
        self.base_url = "https://lk.bcnn.ru"
        self.form_build_id = None
        self.form_token = None
        self.start_session = None
        self.devices: Dict[str, Set[DeviceInfo]] = {}

    @property
    def session(self) -> Session:
        if not self._session or self.session_is_expired():
            self._session = Session()
            self._session.headers = HEADERS_HTML
            self.authenticate()
        return self._session

    def session_is_expired(self):
        if (
                self.start_session
                and self.start_session + 1800 > datetime.now().timestamp()
        ):
            return False
        return True

    def get_accounts(self) -> dict:
        """
        return:
        {'code': 0,
         'data': {'accountInfo': {'accounts': [123456789, 987654321],
                                  'occ': 123456789,
                                  'view': 'few'},
                  'errors': []},
         'message': 'Данные успешно получены'}
        """

        json_data = {"data": {}, "function": "getAccountInfo"}
        response: Response = self.session.post(
            f"{self.base_url}/api/v1/cabinet/querydata",
            headers=HEADERS_JSON,
            json=json_data,
        )
        response.raise_for_status()
        if response.json().get("errors"):
            LOGGER.warning(response.json().get("errors"))
            raise

        return response.json()

    def authenticate(self):
        # Получаем страницу авторизации и извлекаем form_build_id
        auth_page = self._session.get(f"{self.base_url}/node/4?destination=/node/4")
        soup = BeautifulSoup(auth_page.text, "html.parser")
        self.form_build_id = soup.find("input", {"name": "form_build_id"})["value"]

        # Отправляем данные авторизации
        auth_data = {
            "name": self.login,
            "pass": self.password,
            "form_build_id": self.form_build_id,
            "form_id": "user_login_form",
            "op": "Войти"
        }
        self._session.post(f"{self.base_url}/node/4?destination=/node/4", data=auth_data)
        if "Drupal.visitor.autologout_login" not in self._session.cookies:
            raise Exception("Не удалось авторизоваться.")
        self.start_session = int(self._session.cookies.get("Drupal.visitor.autologout_login"))
        LOGGER.info("Успешная авторизация.")

    def navigate_to_readings(self):
        # Переход на страницу передачи показаний
        response = self.session.get(f"{self.base_url}/readings")
        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = soup.find("input", {"name": "form_build_id"})["value"]
        self.form_token = soup.find("input", {"name": "form_token"})["value"]
        LOGGER.info("Загружена форма передачи показаний.")

    def select_account(self, account_number):
        # Смена лицевого счета
        account_data = {
            "account_number": account_number,
            "find_account": "OK",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form"
        }
        response = self.session.post(f"{self.base_url}/readings", data=account_data)
        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = soup.find("input", {"name": "form_build_id"})["value"]
        self.form_token = soup.find("input", {"name": "form_token"})["value"]
        LOGGER.info(f"Аккаунт {account_number} выбран.")

    def change_readings_form(self, account_number):
        # Переход на ввод показаний
        readings_data = {
            "account_number": account_number,
            "op": "Изменить показания",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form"
        }
        response = self.session.post(f"{self.base_url}/readings", data=readings_data)
        soup = BeautifulSoup(response.text, "html.parser")
        self.form_build_id = soup.find("input", {"name": "form_build_id"})["value"]
        self.form_token = soup.find("input", {"name": "form_token"})["value"]
        LOGGER.info("Форма для ввода показаний загружена.")
        return response

    def enter_readings(self, account_number, readings):

        self.change_readings_form(account_number)

        # Передаем показания
        final_data = {
            "account_number": account_number,
            **readings,
            "ok": "1",
            "op": "Передать показания",
            "form_build_id": self.form_build_id,
            "form_token": self.form_token,
            "form_id": "readings_form"
        }
        response = self.session.post(f"{self.base_url}/readings", data=final_data)
        LOGGER.debug("sent data %s", pformat(readings))
        if "распечатать" in response.text:
            LOGGER.info("Показания успешно переданы.")
        else:
            LOGGER.warning("Ошибка при передаче показаний.")

    def get_information_on_water_meters(self, account: Union[str, int]) -> List[Dict[str, str]]:
        """
        Получение информации о водомерах для конкретного аккаунта и передача новых показаний.

        :param account: Номер аккаунта
        :return: Список словарей с информацией о водомерах
        """
        self.navigate_to_readings()
        self.select_account(str(account))
        response = self.change_readings_form(str(account))
        if not response.ok:
            raise Exception("Не удалось обновить данные формы после отправки")

        # Парсинг ответа для извлечения информации о водомерах
        soup = BeautifulSoup(response.text, "lxml")
        water_meters = []
        for row in soup.find_all("tr"):
            columns = row.find_all("td")
            if columns:
                device_type = columns[0].text.strip()
                device_number = columns[1].text.strip()
                prev_value = columns[3].text.strip()
                cur_value = columns[4].text.strip()
                amount_water = columns[5].text.strip()
                input_tag = row.find("input", {"name": re.compile(".+")})
                repr_number = input_tag["name"] if input_tag else None
                cabinet_change = row.find('input', {'onchange': re.compile('.+')})
                pattern = r'cabinet_change\((\d+\.\d+)'
                formatter = tuple(re.match(pattern, cabinet_change["onchange"]).group(1).split("."))
                water_meters.append(
                    {
                        "device_type": device_type,
                        "device_number": device_number,
                        "prev_value": prev_value,
                        "cur_value": cur_value,
                        "amount_water": amount_water,
                        "repr_number": repr_number
                    }
                )
                self.devices.setdefault(str(account), set()).add(
                    DeviceInfo(account, device_type, device_number, repr_number, prev_value, cur_value, amount_water,
                               formatter=formatter)
                )
        return water_meters

    def send_meter_readings(
            self,
            account: Union[str, int],
            readings: Optional[Tuple[Tuple[str, str], ...]] = None,
    ):
        if not readings:
            readings = tuple()

        for device_number, value in readings:
            self.add_meter_reading(account, device_number, value)

        self.navigate_to_readings()
        self.select_account(str(account))  # Подставьте нужный номер ЛС
        readings = {
            device.repr_number: device.send_value()
            for device in self.devices[account]
        }
        self.enter_readings(str(account), readings)
        sleep(30)
        response = self.session.get(f"{self.base_url}/readings")
        LOGGER.debug("response %s", response.text)

        return "Показания успешно переданы"

    def get_address(self, account: Union[str, int]):
        json_data = {"function": "getAddress", "data": {"occ": int(account)}}
        response = self.session.post(
            f"{self.base_url}/api/v1/cabinet/querydata", json=json_data
        )
        response.raise_for_status()
        return response.json()

    def get_chart_data(self, account: Union[str, int]):
        today = date.today()
        prev_month = today - timedelta(days=today.day)

        end_period = today.strftime("%Y%m")

        begin_period = prev_month.strftime("%Y%m")
        json_data = {
            "function": "getChartData",
            "data": {
                "occ": int(account),
                "beginPeriod": begin_period,
                "endPeriod": end_period,
            },
        }

        response = self.session.post(
            f"{self.base_url}/api/v1/cabinet/querydata", json=json_data
        )
        return response.json()

    def add_meter_reading(
            self, account: Union[str, int], device_number: str, value: str
    ):
        for device in self.devices.get(account, set()):
            if device_number != device.device_number:
                continue
            device.new_value = value

    def get_bill(self, account: Union[str, int]) -> Response.content:
        """Getting pdf bill"""
        self.get_chart_data(account)

        response = self.session.get(f"{self.base_url}/to_payment_pdf")
        return response.content

    def get_charges(self, account: Union[str, int]) -> List[Dict[str, Any]]:
        self.get_chart_data(account)

        response = self.session.get(f"{self.base_url}/payments")
        soup = BeautifulSoup(response.text, "html.parser")

        # Находим таблицу с начислениями по ее классу или другим уникальным атрибутам
        table = soup.find("table", {"data-drupal-selector": "edit-table1"})

        # Создаем список для хранения данных
        data = []
        translation_mapper = {
            "Период / Услуга": "period_or_service",
            "Входящее сальдо": "opening_balance",
            "Начислено": "accrued",
            "Оплачено": "paid",
            "К оплате": "due_payment",
        }

        column_names = [
            translation_mapper.get(elem.text.strip(), elem.text.strip())
            for elem in table.find_all("tr")[0].find_all("th")
            if elem
        ]
        LOGGER.debug("Column names: %s", column_names)
        count_rows = len(table.find_all("tr")[1:])

        for batch in batched(table.find_all("tr")[1:], int(count_rows / 3)):
            period = {}
            first_row = [elem.text.strip() for elem in batch[0].find_all("td")]
            current_period = dict(zip(column_names, first_row))
            period_col = next(
                (k for k, v in current_period.items() if convert_period_to_date(v) != date.today()),
                None
            )
            if period_col:
                period["period"] = convert_period_to_date(current_period.pop(period_col))
            period.update(current_period)

            for row in batch[1:]:
                columns = [elem.text.strip() for elem in row.find_all("td")]
                period.setdefault("services", []).append(
                    dict(zip(column_names, columns))
                )
            data.append(period)
        return data

    def get_current_payment(self, account: Union[str, int]) -> dict:
        payments = self.get_charges(account)
        LOGGER.debug(payments)
        if not payments:
            return {}
        res = list(
            filter(
                lambda x: x.get("period") == max(map(lambda y: y.get("period"), payments)),
                payments,
            )
        )
        return res.pop()
