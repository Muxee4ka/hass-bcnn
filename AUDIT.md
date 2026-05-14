# Аудит интеграции hass-bcnn (Center-SБК)

> Дата: 2026-05-14  
> Версия интеграции: 0.1.3  
> Аналитик: Claude Sonnet 4.6

---

## A. Краткое резюме состояния проекта

Интеграция **работоспособна** и решает реальную задачу: снимает данные с Drupal-сайта lk.bcnn.ru, публикует показания водосчётчиков и платёжные данные в Home Assistant. Это нетривиальная задача — нет публичного API, только HTML-скрапинг с цепочкой форм. Базовая структура (coordinator + entity + sensor + button) выбрана правильно.

Однако по шкале **HA Integration Quality Scale** интеграция сейчас находится ниже Bronze:

| Критерий                              | Статус                  |
|---------------------------------------|-------------------------|
| config_flow                           | ✅ есть                 |
| DataUpdateCoordinator                 | ✅ есть                 |
| runtime_data вместо hass.data         | ❌ нет                  |
| Обработка ошибок в config_flow        | ❌ нет (падает исключением) |
| async-only (нет блокирующего IO)      | ⚠️ частично (через executor) |
| diagnostics.py                        | ❌ нет                  |
| strings.json                          | ❌ нет (только translations/) |
| options_flow / reauth                 | ❌ нет                  |
| repairs                               | ❌ нет                  |
| pytest тесты                          | ❌ нет                  |
| mypy / ruff / pre-commit              | ❌ нет                  |
| GitHub Actions CI                     | ❌ нет                  |
| HACS validation workflow              | ❌ нет                  |
| lxml в requirements                   | ❌ отсутствует в manifest.json |
| sleep(30) в основном коде             | 🔴 критично             |
| locale.setlocale на уровне модуля     | 🔴 критично             |
| Пароль в coordinator.data             | 🔴 утечка данных        |

**Главные боли:**
1. `sleep(30)` в `BCNNApi.send_meter_readings` — заблокирует event loop на 30 секунд (вызывается через executor, но всё равно монопольно занимает поток из пула).
2. `locale.setlocale` при импорте модуля ломает любую другую интеграцию, использующую дату с локалью.
3. Пароль хранится открытым текстом в `config_entry.data` и логируется в `__init__.py` строкой `_LOGGER.info([..., config_entry.data, ...])`.
4. Отсутствие тестов делает любой рефакторинг рискованным.
5. `hass.data[DOMAIN]` вместо `config_entry.runtime_data` — устаревший паттерн с HA 2024.x.

---

## B. Таблица найденных проблем

### 🔴 Critical

| # | Проблема | Файл:строка | Почему плохо | Как исправить |
|---|----------|-------------|--------------|---------------|
| 1 | `sleep(30)` в синхронном коде | `bcnn_api.py:268` | Занимает поток executor на 30 с; при нескольких аккаунтах или частых вызовах исчерпывает пул потоков HA | Убрать sleep; после отправки достаточно сделать refresh через coordinator, а не GET на readings |
| 2 | `locale.setlocale(LC_TIME, "ru_RU.UTF-8")` при импорте модуля | `helpers.py:22` | `locale` — глобальное состояние процесса; ломает любую другую интеграцию, которая парсит даты | Заменить на словарь `MONTHS` (уже есть!) — парсить месяцы вручную без locale; locale вообще не нужен |
| 3 | Пароль логируется в `info`-уровне | `__init__.py:28` | `config_entry.data` содержит пароль; попадает в журнал HA | Убрать логирование `config_entry.data`, использовать только `config_entry.entry_id` |
| 4 | `raise` без аргумента в `get_accounts` | `bcnn_api.py:120` | `raise` без аргумента вне `except` — `RuntimeError: No active exception to re-raise` | Заменить на `raise ValueError(...)` с явным сообщением |
| 5 | `lxml` используется, но не в `requirements` | `bcnn_api.py:218`, `manifest.json` | HA не установит lxml; упадёт с `ModuleNotFoundError` на системах без него | Добавить `lxml>=4.9.0` в `manifest.json:requirements` |

### 🟠 High

| # | Проблема | Файл:строка | Почему плохо | Как исправить |
|---|----------|-------------|--------------|---------------|
| 6 | `hass.data[DOMAIN][entry_id]` вместо `entry.runtime_data` | `__init__.py:39`, `sensor.py:235`, `button.py:114` | Устарело с HA 2024.x; нарушает изоляцию entry; не работает при multi-instance | Перейти на `config_entry.runtime_data = coordinator` |
| 7 | `config_flow.py` не обрабатывает исключения — бросает их наружу | `config_flow.py:69-71` | Необработанное исключение в config_flow = крэш потока setup, пустой экран ошибки | Поймать `Exception`, вернуть `errors["base"] = "cannot_connect"` / `"invalid_auth"` |
| 8 | `BCNNApi.devices` — изменяемое глобальное состояние внутри сессии | `bcnn_api.py:71`, `243` | При повторных вызовах `get_information_on_water_meters` устройства накапливаются в `set` без очистки; `send_meter_readings` будет читать устаревшие данные | Очищать `self.devices[account] = set()` перед каждым `get_information_on_water_meters` |
| 9 | `async_unload_services` всегда снимает сервисы при первом unload | `services.py:207-213` | Если установлено несколько аккаунтов, unload одного снимет сервисы для всех | Проверять `len(hass.data[DOMAIN]) == 0` перед удалением сервисов |
| 10 | `async_setup_services` вызывается при каждом `setup_entry` | `__init__.py:43` | Регистрация сервисов — глобальная операция; при нескольких аккаунтах — повторная регистрация | Проверка `hass.services.has_service` уже есть, но архитектурно лучше вызывать один раз в `async_setup` |
| 11 | `BCNNMeterSensor._get_data` вызывает `.pop()` на потенциально пустом списке | `sensor.py:211` | `IndexError` если счётчик пропал из данных (например, сервер вернул пустой список) | Заменить `.pop()` на `next(filter(...), None)` и обработать `None` |
| 12 | Динамические sensor `translation_key` не существуют в переводах | `sensor.py:258` | `translation_key=_get_meter_slug(...)` генерирует slug вида `kholodnaia_voda_12345678` которого нет в `en.json`/`ru.json` | Для динамических сенсоров не задавать `translation_key`, использовать `name` напрямую, или использовать один общий ключ `meter` |
| 13 | `services.yaml` дублирует `translations/*/services` | `services.yaml`, `translations/en.json:56-119` | В современном HA `services.yaml` устарел; нужен только `strings.json` + `translations/` | Удалить `services.yaml`, перенести всё в `strings.json` |
| 14 | Нет `strings.json` | корень `custom_components/bcnn/` | HA ищет `strings.json` как источник для инструментов разработки и HACS-валидации | Создать `strings.json` как копию `translations/en.json` |
| 15 | `send_meter_readings` зависит от side-effect предыдущего вызова | `bcnn_api.py:263` | `self.devices[account]` должен быть заполнен заранее; если вызвать сервис без предшествующего refresh — `KeyError` | Добавить явный вызов `get_information_on_water_meters` внутри `send_meter_readings` если `account not in self.devices` |

### 🟡 Medium

| # | Проблема | Файл:строка | Почему плохо | Как исправить |
|---|----------|-------------|--------------|---------------|
| 16 | Нет `options_flow` / `reauth_flow` | `config_flow.py` | Пользователь не может изменить пароль без удаления интеграции; при смене пароля entry падает в unavailable навсегда | Добавить `async_step_reauth` и `OptionsFlow` для смены пароля |
| 17 | Нет `diagnostics.py` | — | Quality Scale требует; нет способа собрать диагностику без доступа к логам | Создать `diagnostics.py` с редактированием пароля и логина |
| 18 | `BCNNApi.VERSION = "0.0.1"` захардкожена | `bcnn_api.py:61` | Версия интеграции и версия API-клиента расходятся; HACS показывает версию из `manifest.json` | Читать версию из `manifest.json` или убрать `VERSION` из API-класса |
| 19 | `import re` внутри метода `_parse_account_number` | `bcnn_api.py:78` | `re` уже импортирован на уровне модуля (строка 1); двойной импорт | Удалить вложенный `import re` |
| 20 | Старый стиль `Union[str, int]` вместо `str \| int` | `bcnn_api.py` повсюду | Python 3.10+ / `from __future__ import annotations` позволяет `str \| int`; `Union` — legacy | Заменить `Union[X, Y]` → `X \| Y`, `Optional[X]` → `X \| None` |
| 21 | `OPTIONS_SCHEMA` в `__init__.py` не используется | `__init__.py:18-22` | Мёртвый код; запутывает читающего | Удалить |
| 22 | `get_upbdate_interval` опечатка в имени (upbdate) | `helpers.py:72` | Опечатка в публичном API; функция не используется нигде в коде | Удалить или исправить имя |
| 23 | `BCNNButtonEntityDescription` — не frozen dataclass | `button.py:33` | `BCNNButtonRequiredKeysMixin` содержит callable; frozen нужен для hashability и иммутабельности | Добавить `frozen=True` или перейти на `@dataclass(frozen=True, kw_only=True)` |
| 24 | `attr_fn` в `cost` sensor может упасть с `TypeError` | `sensor.py:96-100` | `data[CONF_PAYMENT].get("services")` может вернуть `None`; итерация по `None` — `TypeError` | Добавить `or []` после `.get("services")` |
| 25 | `verify_domain_control` на `_async_handle_service` избыточен | `services.py:158` | `verify_domain_control` предназначен для проверки config в YAML-интеграциях; для config_flow интеграций не нужен | Убрать `@verify_domain_control` |
| 26 | `get_bill` пишет файл в `/tmp` блокирующим `open()` | `services.py:133` | Блокирующий IO в async-контексте; `/tmp` — Linux-специфично, не работает в HA OS | Использовать `hass.async_add_executor_job` для записи или `aiofiles`; путь брать из `hass.config.path()` |
| 27 | Нет retry/backoff при сетевых ошибках | `bcnn_api.py` | Временная недоступность сайта = `UpdateFailed` = красный баннер; нет автовосстановления | Добавить `tenacity` или ручной retry с экспоненциальным backoff в coordinator |
| 28 | `BCNNApi.authenticate` не обрабатывает ошибки парсинга HTML | `bcnn_api.py:128` | Если форма изменится — `TypeError: 'NoneType' is not subscriptable`; нет контекста в исключении | Добавить `if not soup.find(...)` с явным исключением `AuthenticationError` |

### 🔵 Low

| # | Проблема | Файл:строка | Почему плохо | Как исправить |
|---|----------|-------------|--------------|---------------|
| 29 | `batched()` — велосипед; есть в `itertools` (Python 3.12+) | `bcnn_api.py:51-56` | В Python 3.12+ есть `itertools.batched`; для 3.10/3.11 можно взять из `more-itertools` | Оставить как есть или добавить `try/except ImportError` fallback |
| 30 | Нет `__all__` ни в одном модуле | все файлы | Затрудняет статический анализ | Некритично для HA-интеграций, можно пропустить |
| 31 | `CONF_DATA`, `CONF_LINK` в `const.py` не используются | `const.py:20-21` | Мёртвые константы | Удалить |
| 32 | `manifest.json` не содержит `lxml` в requirements | `manifest.json` | Уже в #5 (Critical) | — |
| 33 | Нет `CHANGELOG.md` | корень репо | HACS показывает changelog; пользователи не знают, что изменилось | Создать `CHANGELOG.md` в формате Keep-a-Changelog |

---

## C. Целевая архитектура интеграции

### Целевая файловая структура

```
custom_components/bcnn/
├── __init__.py              # async_setup_entry / async_unload_entry / runtime_data
├── manifest.json            # + lxml, + requests в requirements
├── strings.json             # = копия translations/en.json (источник истины)
├── const.py                 # только константы, без импортов HA
├── exceptions.py            # 🆕 BCNNAuthError, BCNNConnectionError, BCNNParseError
├── bcnn_api.py              # синхронный HTTP-клиент (без sleep, без locale)
├── coordinator.py           # DataUpdateCoordinator + retry logic
├── config_flow.py           # UserStep + ReauthStep + OptionsFlow
├── entity.py                # BCNNBaseCoordinatorEntity
├── sensor.py                # SENSOR_TYPES + BCNNSensor + BCNNMeterSensor
├── button.py                # BUTTON_DESCRIPTIONS + BCNNButtonEntity
├── services.py              # async_setup_services (без services.yaml)
├── diagnostics.py           # 🆕 async_get_config_entry_diagnostics
├── repairs.py               # 🆕 (опционально) создание ремонтных задач
├── helpers.py               # только чистые утилиты (убрать locale)
└── translations/
    ├── en.json
    └── ru.json
```

### Ключевые архитектурные решения

#### 1. `runtime_data` вместо `hass.data`

```python
# __init__.py — ДО (устаревший паттерн)
hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

# __init__.py — ПОСЛЕ
config_entry.runtime_data = coordinator

# sensor.py / button.py — ПОСЛЕ
coordinator: BCNNCoordinator = entry.runtime_data
```

#### 2. Собственная иерархия исключений

```python
# exceptions.py
class BCNNError(Exception):
    """Base exception."""

class BCNNAuthError(BCNNError):
    """Authentication failed."""

class BCNNConnectionError(BCNNError):
    """Network error."""

class BCNNParseError(BCNNError):
    """HTML parsing failed — site structure may have changed."""
```

#### 3. Coordinator с правильным типом

```python
# coordinator.py
type BCNNConfigEntry = ConfigEntry[BCNNCoordinator]  # Python 3.12 / HA 2024.x
```

#### 4. Корректный `config_flow` с обработкой ошибок

```python
async def async_step_user(self, user_input=None):
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            info = await validate_input(self.hass, user_input)
        except BCNNAuthError:
            errors["base"] = "invalid_auth"
        except BCNNConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(info["title"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)
    return self.async_show_form(step_id="user", data_schema=..., errors=errors)
```

#### 5. `diagnostics.py` с редактированием чувствительных данных

```python
# diagnostics.py
from homeassistant.components.diagnostics import async_redact_data

TO_REDACT = {"password", "login"}

async def async_get_config_entry_diagnostics(hass, entry):
    coordinator: BCNNCoordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": coordinator.data,
    }
```

#### 6. `send_readings` — переработка сервиса

Текущий API сервиса неудобен: требует передавать entity_id счётчика и entity_id с его значением по отдельности. Целевой вариант:

```python
# services.yaml / strings.json
send_readings:
  fields:
    device_id:
      selector: {device: {filter: {integration: bcnn}}}
    readings:
      # список пар {device_number, value}
      selector: {object: {}}
```

---

## D. Пошаговый roadmap рефакторинга по PR-ам

### PR 1: «Безопасная подготовка» (hotfix, ~2 часа)

**Цель:** устранить критические баги без изменения архитектуры. Безопасно мёрджить прямо сейчас.

**Изменения:**
- [ ] Убрать `sleep(30)` из `bcnn_api.py:268`; заменить на простой GET без ожидания (или убрать совсем — результат уже залогирован)
- [ ] Убрать `locale.setlocale` из `helpers.py:22`; оставить только словарь `MONTHS`
- [ ] Исправить `raise` → `raise ValueError(...)` в `bcnn_api.py:120`
- [ ] Убрать логирование `config_entry.data` в `__init__.py:28`
- [ ] Добавить `lxml>=4.9.0` в `manifest.json:requirements`
- [ ] Исправить `BCNNMeterSensor._get_data`: `.pop()` → `next(filter(...), None)`; добавить guard на `None`
- [ ] Добавить `or []` в `sensor.py:98` для `data[CONF_PAYMENT].get("services")`
- [ ] Очищать `self.devices[account]` в начале `get_information_on_water_meters`

**Файлы:** `bcnn_api.py`, `helpers.py`, `__init__.py`, `manifest.json`, `sensor.py`

---

### PR 2: «Архитектура и coordinator» (~4 часа)

**Цель:** перевести на современные паттерны HA, не ломая функциональность.

**Изменения:**
- [ ] Создать `exceptions.py` с иерархией `BCNNError / BCNNAuthError / BCNNConnectionError / BCNNParseError`
- [ ] Заменить `Exception("...")` на типизированные исключения во всём `bcnn_api.py`
- [ ] Перейти с `hass.data[DOMAIN]` на `config_entry.runtime_data` в `__init__.py`, `sensor.py`, `button.py`, `helpers.py`
- [ ] Добавить `type BCNNConfigEntry = ConfigEntry[BCNNCoordinator]` в `coordinator.py`
- [ ] Удалить `OPTIONS_SCHEMA` из `__init__.py`
- [ ] Удалить неиспользуемые `CONF_DATA`, `CONF_LINK` из `const.py`
- [ ] Исправить `async_unload_services`: проверять количество оставшихся entry перед удалением сервисов
- [ ] Убрать `@verify_domain_control` из `services.py`
- [ ] Перенести `PDF_PATH` в `const.py`; использовать `hass.config.path()` вместо `/tmp`
- [ ] Заменить `Union[X, Y]` / `Optional[X]` на `X | Y` / `X | None` во всех файлах

**Файлы:** `exceptions.py` (новый), `__init__.py`, `coordinator.py`, `sensor.py`, `button.py`, `helpers.py`, `services.py`, `const.py`, `bcnn_api.py`

---

### PR 3: «Config flow / Options flow / Reauth» (~3 часа)

**Цель:** нормальная UX установки, смена пароля без пересоздания интеграции.

**Изменения:**
- [ ] Переписать `async_step_user` в `config_flow.py`: ловить `BCNNAuthError` → `invalid_auth`, `BCNNConnectionError` → `cannot_connect`, `Exception` → `unknown`
- [ ] Добавить `async_step_reauth` для повторной аутентификации при смене пароля
- [ ] Добавить `BCNNOptionsFlow` (хотя бы заглушку; можно вынести polling interval если добавится)
- [ ] Создать `strings.json` (= `translations/en.json` + секции `reauth` + `init`)
- [ ] Обновить `translations/en.json` и `translations/ru.json`: добавить ключи `reauth`, ошибки `invalid_auth` / `cannot_connect` / `unknown`
- [ ] Удалить `services.yaml` (дубликат; всё уже в `strings.json`)

**Файлы:** `config_flow.py`, `strings.json` (новый), `translations/en.json`, `translations/ru.json`

---

### PR 4: «Diagnostics / Repairs / Translations» (~2 часа)

**Цель:** Quality Scale Bronze → начало Silver.

**Изменения:**
- [ ] Создать `diagnostics.py` с `async_get_config_entry_diagnostics`; редактировать `password`, `login`
- [ ] Добавить `"diagnostics"` в `PLATFORMS` в `const.py`
- [ ] Исправить динамические `translation_key` у `BCNNMeterSensor`: убрать или использовать один ключ `"meter"` из переводов
- [ ] Добавить в `translations/ru.json` и `en.json` пропущенные ключи (сейчас `meter` есть в переводах, но `_get_meter_slug` генерирует другие ключи)
- [ ] Добавить `"attribution"` в translations
- [ ] (Опционально) создать `repairs.py`: при `BCNNAuthError` создавать `RepairIssue` с предложением пройти reauth

**Файлы:** `diagnostics.py` (новый), `const.py`, `sensor.py`, `translations/en.json`, `translations/ru.json`

---

### PR 5: «Тесты / Tooling / CI» (~8 часов)

**Цель:** покрытие тестами, линтинг, GitHub Actions.

**Структура тестов:**
```
tests/
├── conftest.py              # fixtures: hass, mock_config_entry, mock_bcnn_api
├── test_config_flow.py      # happy path, wrong password, wrong account, duplicate
├── test_coordinator.py      # успешный update, UpdateFailed, retry
├── test_sensor.py           # значения сенсоров, available/unavailable
├── test_button.py           # нажатие кнопок
├── test_services.py         # refresh, send_readings, get_bill
├── test_bcnn_api.py         # unit-тесты парсинга HTML (с фикстурами HTML-страниц)
└── fixtures/
    ├── readings_page.html
    ├── payments_page.html
    └── auth_page.html
```

**Обязательные сценарии:**
- [ ] Успешный config_flow → entry создан, entities доступны
- [ ] Неверный пароль → `invalid_auth` в форме
- [ ] Недоступен сайт → `cannot_connect`
- [ ] Дублирующий аккаунт → `already_configured`
- [ ] `_async_update_data` выбрасывает `BCNNConnectionError` → сенсоры `unavailable`
- [ ] `send_readings` без предшествующего refresh → корректная ошибка
- [ ] `_get_data` в `BCNNMeterSensor` — счётчик исчез из данных

**Dev tooling:**
- [ ] Создать `pyproject.toml` с секциями `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`
- [ ] Создать `.pre-commit-config.yaml` с ruff, mypy, trailing-whitespace, end-of-file-fixer
- [ ] Создать `.github/workflows/ci.yml`: lint + tests на Python 3.12 + 3.13
- [ ] Создать `.github/workflows/hacs-validation.yml` с `hacs/action@v1.1.x`

**Файлы:** `pyproject.toml` (новый), `.pre-commit-config.yaml` (новый), `.github/workflows/ci.yml` (новый), `.github/workflows/hacs-validation.yml` (новый), `tests/` (новая директория)

---

### PR 6: «Новые функции» (~6 часов)

**Цель:** расширить полезность интеграции для пользователей HA.

**Идеи:**
- [ ] **`binary_sensor.py`** — сенсор «Есть задолженность» (`due_payment > 0`); триггер для автоматизации «напомни оплатить»
- [ ] **`number.py`** — `NumberEntity` для каждого счётчика: пользователь вводит показание прямо в UI, без сервиса; кнопка «Отправить» активируется
- [ ] **`event.py`** — события `bcnn_readings_sent`, `bcnn_bill_received` как `EventEntity` (HA 2024.x+)
- [ ] **Sensor: предыдущие показания** — отдельный сенсор `prev_value` для каждого счётчика
- [ ] **Sensor: потребление за месяц** — `amount_water` как отдельный сенсор с `state_class=TOTAL_INCREASING`
- [ ] **Sensor: сальдо** — `opening_balance`, `accrued`, `paid` как отдельные сенсоры (сейчас только атрибуты)
- [ ] **`send_readings` через UI**: переработать сервис — принимать `{device_number: str, value: float}[]` вместо hardcoded cw1/hw1/...
- [ ] **Notify при успешной отправке** — вызывать `hass.components.persistent_notification` после `send_readings`
- [ ] **Поддержка нескольких аккаунтов** — архитектурно уже возможна через multi-entry; проверить и задокументировать
- [ ] **Получение адреса как атрибута устройства** — добавить `configuration_url` с адресом квартиры в `DeviceInfo`

---

## E. Конкретный список файлов для создания/изменения

### Создать с нуля
| Файл | PR | Назначение |
|------|----|------------|
| `exceptions.py` | PR 2 | Иерархия исключений |
| `diagnostics.py` | PR 4 | Диагностика с редактированием |
| `strings.json` | PR 3 | Источник истины для переводов |
| `repairs.py` | PR 4 | Ремонтные задачи (опционально) |
| `pyproject.toml` | PR 5 | Конфигурация инструментов |
| `.pre-commit-config.yaml` | PR 5 | Pre-commit хуки |
| `.github/workflows/ci.yml` | PR 5 | GitHub Actions CI |
| `.github/workflows/hacs-validation.yml` | PR 5 | HACS валидация |
| `tests/conftest.py` | PR 5 | Фикстуры тестов |
| `tests/test_config_flow.py` | PR 5 | Тесты config flow |
| `tests/test_coordinator.py` | PR 5 | Тесты coordinator |
| `tests/test_sensor.py` | PR 5 | Тесты сенсоров |
| `tests/test_services.py` | PR 5 | Тесты сервисов |
| `tests/test_bcnn_api.py` | PR 5 | Тесты парсинга |
| `tests/fixtures/` | PR 5 | HTML-фикстуры |
| `CHANGELOG.md` | PR 1 | История версий |

### Изменить
| Файл | PR | Что изменить |
|------|----|--------------|
| `manifest.json` | PR 1 | Добавить `lxml`, `requests` в requirements |
| `bcnn_api.py` | PR 1+2 | Убрать sleep, locale, raise без аргумента; типизированные исключения |
| `helpers.py` | PR 1+2 | Убрать locale.setlocale; убрать неиспользуемые функции |
| `__init__.py` | PR 2 | runtime_data; убрать OPTIONS_SCHEMA; убрать логирование data |
| `const.py` | PR 2 | Убрать CONF_DATA, CONF_LINK; добавить PDF_PATH |
| `coordinator.py` | PR 2 | Тип BCNNConfigEntry; retry logic |
| `sensor.py` | PR 2+4 | runtime_data; исправить _get_data; translation_key |
| `button.py` | PR 2 | runtime_data |
| `services.py` | PR 2 | Убрать verify_domain_control; исправить unload; hass.config.path() |
| `config_flow.py` | PR 3 | Обработка ошибок; reauth; options |
| `translations/en.json` | PR 3+4 | Добавить reauth, исправить ключи |
| `translations/ru.json` | PR 3+4 | Синхронизировать с en.json |

### Удалить
| Файл | PR | Причина |
|------|----|---------|
| `services.yaml` | PR 3 | Дубликат; заменён strings.json |

---

## F. Примеры кода для ключевых мест

### F.1 exceptions.py

```python
"""Center-SBK exceptions."""


class BCNNError(Exception):
    """Base exception for Center-SBK integration."""


class BCNNAuthError(BCNNError):
    """Raised when authentication fails."""


class BCNNConnectionError(BCNNError):
    """Raised when the site is unreachable."""


class BCNNParseError(BCNNError):
    """Raised when HTML structure doesn't match expectations."""
```

### F.2 bcnn_api.py — authenticate без голого Exception

```python
def authenticate(self) -> None:
    from .exceptions import BCNNAuthError, BCNNParseError
    try:
        auth_page = self._session.get(f"{self.base_url}/node/4?destination=/node/4")
        auth_page.raise_for_status()
    except requests.RequestException as exc:
        raise BCNNConnectionError(f"Не удалось получить страницу авторизации: {exc}") from exc

    soup = BeautifulSoup(auth_page.text, "html.parser")
    form_build = soup.find("input", {"name": "form_build_id"})
    if form_build is None:
        raise BCNNParseError("Не найден form_build_id на странице авторизации")
    self.form_build_id = form_build["value"]

    auth_data = {
        "name": self.login,
        "pass": self.password,
        "form_build_id": self.form_build_id,
        "form_id": "user_login_form",
        "op": "Войти",
    }
    self._session.post(f"{self.base_url}/node/4?destination=/node/4", data=auth_data)
    if "Drupal.visitor.autologout_login" not in self._session.cookies:
        raise BCNNAuthError("Неверный логин или пароль")
    self.start_session = int(
        self._session.cookies.get("Drupal.visitor.autologout_login")
    )
    LOGGER.info("Успешная авторизация.")
```

### F.3 __init__.py — runtime_data

```python
async def async_setup_entry(hass: HomeAssistant, entry: BCNNConfigEntry) -> bool:
    api = BCNNApi(
        login=entry.data[CONF_LOGIN],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = BCNNCoordinator(hass, api=api, account=entry.data[CONF_ACCOUNT])
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator  # ← современный паттерн

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BCNNConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

### F.4 config_flow.py — корректная обработка ошибок

```python
async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            info = await validate_input(self.hass, user_input)
        except BCNNAuthError:
            errors["base"] = "invalid_auth"
        except BCNNConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during setup")
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(info["title"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=info["title"], data=user_input)

    return self.async_show_form(
        step_id="user",
        data_schema=vol.Schema({
            vol.Required(CONF_LOGIN): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_ACCOUNT): str,
        }),
        errors=errors,
    )

async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
    """Handle re-authentication."""
    errors: dict[str, str] = {}
    if user_input is not None:
        try:
            await validate_input(self.hass, {**self._get_reauth_entry().data, **user_input})
        except BCNNAuthError:
            errors["base"] = "invalid_auth"
        except BCNNConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during reauth")
            errors["base"] = "unknown"
        else:
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(),
                data_updates=user_input,
            )
    return self.async_show_form(
        step_id="reauth",
        data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
        errors=errors,
    )
```

### F.5 coordinator.py — retry при сетевых ошибках

```python
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .exceptions import BCNNAuthError, BCNNConnectionError

MAX_RETRIES = 3

class BCNNCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: BCNNConfigEntry

    async def _async_update_data(self) -> dict[str, Any]:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self.lock:
                    return await self._fetch_all()
            except BCNNAuthError as exc:
                # При ошибке аутентификации сразу создаём reauth issue
                self.config_entry.async_start_reauth(self.hass)
                raise UpdateFailed(f"Ошибка аутентификации: {exc}") from exc
            except BCNNConnectionError as exc:
                if attempt == MAX_RETRIES:
                    raise UpdateFailed(f"Сервис недоступен: {exc}") from exc
                await asyncio.sleep(2 ** attempt)  # 2, 4 секунды
        raise UpdateFailed("Превышено число попыток")
```

### F.6 diagnostics.py

```python
"""Diagnostics for Center-SBK."""
from __future__ import annotations

from typing import Any
from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from .coordinator import BCNNConfigEntry

TO_REDACT = {"password", "login", "name", "pass"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BCNNConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator_data": coordinator.data,
        "last_update_success": coordinator.last_update_success,
    }
```

### F.7 pyproject.toml

```toml
[tool.ruff]
target-version = "py312"
line-length = 100
select = ["E", "F", "I", "UP", "ANN", "B", "SIM"]
ignore = ["ANN101", "ANN102"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["custom_components/bcnn"]
omit = ["tests/*"]
```

### F.8 tests/conftest.py (скелет)

```python
"""Test fixtures for bcnn integration."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.bcnn.const import DOMAIN, CONF_LOGIN, CONF_PASSWORD, CONF_ACCOUNT

MOCK_CONFIG = {
    CONF_LOGIN: "test@example.com",
    CONF_PASSWORD: "secret",
    CONF_ACCOUNT: "123456789",
}

MOCK_READINGS = [
    {
        "device_type": "Холодная вода",
        "device_number": "12345678",
        "prev_value": "100.00",
        "cur_value": "105.00",
        "amount_water": "5.00",
        "repr_number": "readings[0]",
    }
]

MOCK_PAYMENT = {
    "period": "2026-04-01",
    "opening_balance": "0.00",
    "accrued": "500.00",
    "paid": "0.00",
    "due_payment": "500.00",
    "services": [],
}

@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test_entry_id")

@pytest.fixture
def mock_api():
    with patch("custom_components.bcnn.bcnn_api.BCNNApi") as mock:
        instance = mock.return_value
        instance.get_information_on_water_meters = MagicMock(return_value=MOCK_READINGS)
        instance.get_address = MagicMock(return_value={"data": {"address": "ул. Тестовая, 1"}})
        instance.get_current_payment = MagicMock(return_value=MOCK_PAYMENT)
        yield instance
```

---

## G. Что лучше НЕ делать и почему

| Антипаттерн | Почему НЕ надо |
|-------------|---------------|
| Вынести `BCNNApi` в `async`-класс с `aiohttp` | Сайт — Drupal с форм-токенами и состоянием сессии. Реализация на `requests` проще, надёжнее и уже работает. Переписывать на `aiohttp` — большой риск, мало выгоды. Достаточно оборачивать в `executor_job`. |
| Добавить `update_interval` в coordinator | Сайт — не IoT-устройство; данные обновляются раз в месяц. Постоянный polling = нагрузка на Drupal-сайт + риск бана по IP. Правильно — только ручной refresh + reauth при потере сессии. |
| Хранить PDF в HA media directory | `/media` — медиа-хранилище HA, не для счётов. Лучше использовать `hass.config.path("tmp")` или отдать URL через `media_source`. Но проще всего — отправлять уведомление с base64 или ссылкой. |
| Переходить на `ConfigEntry.async_migrate_entry` сразу | Нет смысла пока `VERSION=1` и нет старых entry на продакшне (или их немного). Добавить только в PR 3 если изменится структура `data`. |
| Добавлять `scan_interval` в `options_flow` | Coordinator без `update_interval` — намеренное решение (см. CLAUDE.md). Не нарушать. |
| Использовать `entity_platform.async_add_entities(..., True)` | Второй аргумент `update_before_add=True` устарён с HA 2024.4; entities теперь обновляются через coordinator. Убрать `True`. |
| Называть сенсоры через `name=` вместо `translation_key=` | После `_attr_has_entity_name = True` имя должно приходить из перевода; hardcoded `name` в description будет переопределять перевод непредсказуемо. Использовать только `translation_key`. |

---

## H. Финальный чеклист готовности интеграции

### Bronze (минимум для HACS)
- [ ] `config_flow: true` в manifest.json ✅ (уже есть)
- [ ] Корректный `config_flow` с обработкой всех ошибок
- [ ] `strings.json` существует и синхронизирован с `translations/`
- [ ] `async_unload_entry` корректно убирает все ресурсы
- [ ] Нет блокирующего IO в async-контексте (кроме executor)
- [ ] Нет `sleep()` в коде
- [ ] Нет утечек паролей в логах
- [ ] `unique_id` задан для каждой entry и каждой entity
- [ ] `device_info` корректно заполнен
- [ ] HACS validation workflow проходит

### Silver
- [ ] `diagnostics.py` с редактированием чувствительных данных
- [ ] `options_flow` или `reauth_flow`
- [ ] Типизированные исключения (`BCNNAuthError`, etc.)
- [ ] `runtime_data` вместо `hass.data`
- [ ] Retry logic в coordinator
- [ ] Покрытие тестами > 70%
- [ ] `mypy --strict` без ошибок
- [ ] `ruff check` без ошибок

### Gold
- [ ] Покрытие тестами > 90%
- [ ] Все entity используют `translation_key` (нет hardcoded name)
- [ ] `repairs.py` для actionable ошибок
- [ ] Полные логи с `_LOGGER.debug` на каждом шаге
- [ ] `CHANGELOG.md` в формате Keep-a-Changelog
- [ ] Документация в `README.md` актуальна
- [ ] GitHub Actions проходят на PR
- [ ] Нет закомментированного кода (раскомментировать кнопку `send_readings` или удалить)
