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
