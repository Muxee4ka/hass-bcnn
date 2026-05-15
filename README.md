[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

![bcnn 1](images/icons/logo.png)

Этот репозиторий содержит настраиваемый компонент для Home Assistant для отображения данных из сервиса Центр СБК.

# Установка

**Способ 1.** Через [HACS](https://hacs.xyz/) &rarr; Интеграции &rarr; Добавить пользовательский
репозиторий &rarr; https://github.com/Muxee4ka/hass-bcnn &rarr; **bcnn** &rarr; Установить

**Способ 2.** Вручную скопируйте папку `bcnn`
из [latest release](https://github.com/Muxee4ka/hass-bcnn/releases/latest) в
директорию `/config/custom_components`.

После установки необходимо перегрузить Home Assistant

# Настройка

[Настройки](https://my.home-assistant.io/redirect/config) &rarr; Устройства и службы
&rarr; [Интеграции](https://my.home-assistant.io/redirect/integrations)
&rarr; [Добавить интеграцию](https://my.home-assistant.io/redirect/config_flow_start?domain=bcnn) &rarr; Поиск &rarr; **bcnn**

или нажмите:

[![Добавить интеграцию](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=bcnn)

# Сущности

После добавления ЛС интеграция создаёт устройство «ЛС №…» со следующими сущностями:

- **Сенсоры:** «Лицевой счёт», «Сумма к оплате», «Задолженность», «Дата начисления», «Последнее обновление», а также по одному сенсору на каждый прибор учёта (Холодная / Горячая вода) с текущими и предыдущими показаниями.
- **Поля ввода (`number`):** на каждый прибор учёта создаётся «… — новое показание». В этом поле можно вручную задать показание прямо со страницы устройства, значение сохраняется после рестарта.
- **Кнопки:** «Обновить сведения», «Получить счёт», «Отправить показания». Кнопка «Отправить показания» берёт значения из соответствующих полей `number` этого ЛС и отсылает их одним пакетом.

# Сервисы

| Сервис | Назначение |
|--------|------------|
| `bcnn.refresh` | Обновить данные ЛС. |
| `bcnn.get_bill` | Скачать PDF-счёт в `config/tmp/bill_<ЛС>.pdf`. |
| `bcnn.send_readings` | Передать показания. Поддерживает три способа задать значения (приоритет сверху вниз): слоты `meter_N` + `meter_N_value` (выбор сенсора + значение, удобно в Dev Tools), словарь `readings` вида `{ "<номер_счётчика>": <показание> }` (удобно в автоматизациях), либо ничего — тогда берутся значения из `number`-сущностей ЛС (так работает кнопка «Отправить показания»). Все выбранные счётчики проверяются на принадлежность указанному ЛС — иначе ошибка. |

# Автоматизации

## Вариант 1 — показания приходят из другой интеграции (рекомендуется)

Передаём словарь `readings`: ключ — номер счётчика (виден в атрибуте `Номер счетчика` у сенсора прибора учёта или в кабинете lk.bcnn.ru), значение — текущее показание из вашего источника.

```yaml
alias: Отправить показания за воду
triggers:
  - trigger: time
    at: "22:00:00"
conditions:
  - condition: template
    value_template: "{{ now().day == 10 }}"
actions:
  - action: bcnn.send_readings
    data:
      device_id: 276c91f0d2ff43d7b0650a66b24cce3b   # устройство ЛС
      readings:
        "12345678": "{{ states('sensor.watermeter_cold') | float }}"
        "87654321": "{{ states('sensor.watermeter_hot') | float }}"
  - delay: "00:00:30"
  - action: bcnn.refresh
    data:
      device_id: 276c91f0d2ff43d7b0650a66b24cce3b
```

## Вариант 2 — выбор счётчиков в Dev Tools

В Dev Tools у сервиса `bcnn.send_readings` есть до четырёх слотов: «Счётчик N» (выпадающий список со всеми счётчиками интеграции) и «Показание счётчика N, м³». Выберите ЛС, нужные счётчики и введите значения. Если случайно выберете счётчик из другого ЛС — сервис вернёт ошибку с указанием неподходящего счётчика.

## Вариант 3 — значения уже заполнены в `number`-сущностях ЛС

Например, через `number.set_value` или вручную на странице устройства. Тогда дополнительные аргументы не нужны:

```yaml
alias: Отправить показания за воду
triggers:
  - trigger: time
    at: "22:00:00"
conditions:
  - condition: template
    value_template: "{{ now().day == 10 }}"
actions:
  - action: bcnn.send_readings
    data:
      device_id: 276c91f0d2ff43d7b0650a66b24cce3b
```

