[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

![bcnn 1](images/icons/logo.png)

Этот репозиторий содержит настраиваемый компонент для Home Assistant для отображения данных из сервиса Центр СБК.

# Установка

**Способ 1.** Через [HACS](https://hacs.xyz/) &rarr; Интеграции &rarr; Добавить пользовательский
репозиторий &rarr; https://github.com/Muxee4ka/hass-bcnn &rarr; **bcnn** &rarr; Установить

**Способ 2.** Вручную скопируйте папку `tns_energo`
из [latest release](https://github.com/Muxee4ka/hass-bcnn/releases/latest) в
директорию `/config/custom_components`.

После установки необходимо перегрузить Home Assistant

# Настройка

[Настройки](https://my.home-assistant.io/redirect/config) &rarr; Устройства и службы
&rarr; [Интеграции](https://my.home-assistant.io/redirect/integrations)
&rarr; [Добавить интеграцию](https://my.home-assistant.io/redirect/config_flow_start?domain=bcnn) &rarr; Поиск &rarr; **bcnn**

или нажмите:

[![Добавить интеграцию](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=bcnn)

# Автоматизации

```yaml
alias: Отправить показания за воду
description: ""
triggers:
  - at: "22:00:00"
    trigger: time
conditions:
  - condition: template
    value_template: "{{ now().day == 10 }}"
actions:
  - data:
      device_id: 276c91f0d2ff43d7b0650a66b24cce3b # Уникальный идентификатор координатора для передачи данных
      cw1: sensor.bcnn_123456789_hvs_1 # Ссылка на датчик холодной воды для счетчика №1.
      hw1: sensor.bcnn_123456789_gvs_1 # Ссылка на датчик горячей воды для счетчика №1.
      cw2: sensor.bcnn_123456789_hvs_2 # Ссылка на датчик холодной воды для счетчика №2.
      hw2: sensor.bcnn_123456789_gvs_2 # Ссылка на датчик горячей воды для счетчика №2.
      cw1val: input_text.hvs_1 # Значение холодной воды для счетчика №1.
      hw1val: input_text.gvs_1 # Значение горячей воды для счетчика №1.
      cw2val: sensor.watermeter_hvs_2 # Значение холодной воды для счетчика №2.
      hw2val: sensor.watermeter_gvs_2 # Значение горячей воды для счетчика №2.
    action: bcnn.send_readings
  - delay:
      hours: 0
      minutes: 0
      seconds: 30
      milliseconds: 0
  - metadata: {}
    data:
      device_id: 276c91f0d2ff43d7b0650a66b24cce3b
    action: bcnn.refresh # Обновление данных
```

