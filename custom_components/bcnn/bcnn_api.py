import re
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from itertools import islice
from logging import getLogger
from typing import Union, Tuple, Dict, Optional, List, Set, Any, Final

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


@dataclass(unsafe_hash=True)
class DeviceInfo:
    account_number: str
    device_type: str
    device_number: str
    repr_number: str
    value: str
    new_value: str = None

    def send_value(self):
        return str(self.new_value or self.value)


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
        self._login: str = login
        self._password: str = password
        self._form_build_id: Optional[str] = None
        self._form_token: Optional[str] = None
        self._session: Optional[Session] = None
        self.devices: Dict[str, Set[DeviceInfo]] = {}
        self.start_session = None

    @property
    def session(self) -> Session:
        if not self._session or self.session_is_expired():
            self._session = Session()
            self._session.headers = HEADERS_HTML
            data = {
                "name": self._login,
                "pass": self._password,
                "form_id": "user_login_form",
                "op": "Войти",
            }

            response = self._session.post(
                "https://lk.bcnn.ru/node/4?destination=/node/4", data=data
            )
            cookies = self._session.cookies.get_dict()
            self.start_session = int(cookies.get("Drupal.visitor.autologout_login"))
            if not response.ok:
                raise
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
            "https://lk.bcnn.ru/api/v1/cabinet/querydata",
            headers=HEADERS_JSON,
            json=json_data,
        )
        response.raise_for_status()
        if response.json().get("errors"):
            LOGGER.warning(response.json().get("errors"))
            raise

        return response.json()

    def get_form_info(self, account: Union[str, int]) -> Tuple[str, str]:
        tag = "input"
        attrs_form_build_id = {"name": "form_build_id"}
        attrs_form_token = {"name": "form_token"}

        def get_form_info_from_soup(response: Response):
            soup = BeautifulSoup(response.text, "lxml")
            form_build_id = soup.find(tag, attrs_form_build_id)["value"]
            form_token = soup.find(tag, attrs_form_token)["value"]
            return form_build_id, form_token

        response = self.session.get("https://lk.bcnn.ru/readings")
        form_build_id, form_token = get_form_info_from_soup(response)
        data = {
            "account_number": str(account),
            "find_account": "OK",
            "form_build_id": form_build_id,
            "form_token": form_token,
            "form_id": "readings_form",
        }

        response = self.session.post("https://lk.bcnn.ru/readings", data=data)
        return get_form_info_from_soup(response)

    def get_information_on_water_meters(
        self, account: Union[str, int]
    ) -> List[Dict[str, str]]:
        """

        :param account:
        :return:
        [{'device_type': 'ГВС',
          'device_number': '000000001',
          'repr_number': 'cur_386538',
          'value': '00106.608001'},
         {'device_type': 'ГВС',
          'device_number': '000000002',
          'repr_number': 'cur_386541',
          'value': '00106.608001'},
         {'device_type': 'ХВС',
          'device_number': '000000003',
          'repr_number': 'cur_404612',
          'value': '00150.00000'},
         {'device_type': 'ХВС',
          'device_number': '000000004',
          'repr_number': 'cur_404614',
          'value': '00081.00000'}]}
        """
        form_build_id, form_token = self.get_form_info(account)

        data = {
            "account_number": str(account),
            "op": "Изменить показания",
            "form_build_id": form_build_id,
            "form_token": form_token,
            "form_id": "readings_form",
        }
        self.session.post("https://lk.bcnn.ru/readings", data=data)

        response = self.session.get("https://lk.bcnn.ru/readings")
        if not response.ok:
            raise
        soup = BeautifulSoup(response.text, "lxml")
        water_meters = []
        for row in soup.find_all("tr"):
            columns = row.find_all("td")
            if columns:
                device_type = columns[0].text.strip()
                device_number = columns[1].text.strip()
                value = columns[3].text.strip()
                input_tag = row.find("input", {"name": re.compile(".+")})
                repr_number = input_tag["name"] if input_tag else None
                water_meters.append(
                    {
                        "device_type": device_type,
                        "device_number": device_number,
                        "value": value,
                        "repr_number": repr_number,
                    }
                )
                self.devices.setdefault(account, set()).add(
                    DeviceInfo(account, device_type, device_number, repr_number, value)
                )
        return water_meters

    def send_meter_readings(
        self,
        account: Union[str, int],
        readings: Optional[Tuple[Tuple[str, str], ...]] = None,
    ):
        if not readings:
            readings = tuple()
        self.get_information_on_water_meters(account)
        for device_number, value in readings:
            self.add_meter_reading(account, device_number, value)
        form_build_id, form_token = self.get_form_info(account)
        data = {
            "account_number": str(account),
            "ok": "1",
            "op": "Передать показания",
            "form_build_id": form_build_id,
            "form_token": form_token,
            "form_id": "readings_form",
            **{
                device.repr_number: device.send_value()
                for device in self.devices[account]
            },
        }
        response = self.session.post("https://lk.bcnn.ru/readings", data=data)
        response.raise_for_status()
        LOGGER.debug("sent data %s", data)
        LOGGER.debug(response.text)
        return "Показания успешно переданы"

    def get_address(self, account: Union[str, int]):
        json_data = {"function": "getAddress", "data": {"occ": int(account)}}
        response = self.session.post(
            "https://lk.bcnn.ru/api/v1/cabinet/querydata", json=json_data
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
            "https://lk.bcnn.ru/api/v1/cabinet/querydata", json=json_data
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

        response = self.session.get("https://lk.bcnn.ru/to_payment_pdf")
        return response.content

    def get_charges(self, account: Union[str, int]) -> List[Dict[str, Any]]:
        self.get_chart_data(account)

        response = self.session.get("https://lk.bcnn.ru/payments")
        # Используем BeautifulSoup для парсинга HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Находим таблицу с начислениями по ее классу или другим уникальным атрибутам
        table = soup.find("table", {"data-drupal-selector": "edit-table1"})

        # Создаем список для хранения данных
        translation_mapper = {
            "Период/ Услуга": "period_or_service",
            "Входящее сальдо": "opening_balance",
            "Начислено": "accrued",
            "Оплачено": "paid",
            "К оплате": "due_payment",
        }

        data = []
        column_names = [
            translation_mapper[elem.text.strip()]
            for elem in table.find_all("tr")[0].find_all("th")
            if elem
        ]
        count_rows = len(table.find_all("tr")[1:])

        for batch in batched(table.find_all("tr")[1:], int(count_rows / 3)):
            period = {}
            first_row = [elem.text.strip() for elem in batch[0].find_all("td")]
            current_period = dict(zip(column_names, first_row))
            period["period"] = convert_period_to_date(
                current_period.pop("period_or_service")
            )
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
                lambda x: x.get("period")
                == max(map(lambda y: y.get("period"), payments)),
                payments,
            )
        )
        return res.pop()
