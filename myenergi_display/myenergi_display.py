#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import threading
import requests

from requests.auth import HTTPDigestAuth
from queue import Queue
from time import time

from datetime import timedelta, datetime, timezone
import urllib.request
import json
from copy import deepcopy

import plotly.graph_objects as go

from p3lib.uio import UIO
from p3lib.helper import logTraceBack
from p3lib.pconfig import DotConfigManager
from p3lib.boot_manager import BootManager
from p3lib.ngt import TabbedNiceGui, YesNoDialog

from nicegui import ui, html


class MyEnergi(object):
    """@brief An interface to MyEnergi products.
              This is not meant to be a comprehensive interface.
              It provides the functionality required by this application."""
    TANK_TOP = 1
    TANK_BOTTOM = 2
    BASE_URL = 'https://s18.myenergi.net/'
    VALID_ZAPPI_SLOT_ID_LIST = (11, 12, 13, 14)

    def __init__(self, api_key):
        """@brief Constuctor
           @param api_key Your myenergi API key.
                          You must create this on the myenergi web site.
                          See https://support.myenergi.com/hc/en-gb/articles/5069627351185-How-do-I-get-an-API-key for more information."""
        self._api_key = api_key
        self._eddi_serial_number = None
        self._zappi_serial_number = None

    def set_eddi_serial_number(self, eddi_serial_number):
        """@brief set the eddi serial number.
           @param eddi_serial_number The serial number of the eddi unit of interest."""
        self._eddi_serial_number = eddi_serial_number

    def set_zappi_serial_number(self, zappi_serial_number):
        """@brief set the zappi serial number.
           @param zappi_serial_number The serial number of the zappi unit of interest."""
        self._zappi_serial_number = zappi_serial_number

    def _check_eddi_serial_number(self):
        """@brief Check that the eddi serial number has been set."""
        if self._eddi_serial_number is None:
            raise Exception("BUG: The eddi serial number has not been set.")

    def _check_zappi_serial_number(self):
        """@brief Check that the zappi serial number has been set."""
        if self._zappi_serial_number is None:
            raise Exception("BUG: The zappi serial number has not been set.")

    def get_eddi_stats(self):
        """@brief Get the stats of the eddi unit."""
        self._check_eddi_serial_number()
        url = MyEnergi.BASE_URL + "cgi-jstatus-E"
        return self._exec_api_cmd(url)

    def get_zappi_stats(self):
        """@brief Get the stats of the eddi unit."""
        self._check_eddi_serial_number()
        self._check_zappi_serial_number()
        url = MyEnergi.BASE_URL + "cgi-boost-time-Z"+self._zappi_serial_number
        return self._exec_api_cmd(url)

    def get_tank_stats(self):
        """@brief Get the hot water tank temperatures and heater load. Two temp sensors can be fitted to the eddi
                  units. Both will be returned even if the temperature sensors are not connected.
           @return A tuple containing
                   0 = The top tank temperature.
                   1 = The bottom tank temperature.
                   2 = The power drawn in kW when a heater is on.
                   3 = The number of the heater that is currently on. This is only valid if there is power drawn by the heater."""
        top_tank_temp = None
        bottom_tank_temp = None
        heater_kwh = None
        response_dict = self.get_eddi_stats()
        if 'eddi' in response_dict:
            eddi_dict = response_dict['eddi'][0]
            # Top tank temperature
            if 'tp1' in eddi_dict:
                top_tank_temp = eddi_dict['tp1']
            # Bottom tank temperature
            if 'tp2' in eddi_dict:
                bottom_tank_temp = eddi_dict['tp2']
            # Heater load power kw
            if 'div' in eddi_dict:
                heater_kwh = eddi_dict['div']
            # The number of the heater that is on.
            # If no heater is on then this stays at the last value.
            # 1 = top tank, 2 = bottom tank
            if 'hno' in eddi_dict:
                heater_number = eddi_dict['hno']

        if top_tank_temp is None:
            raise Exception("Failed to read the top of tank temperature from the eddi unit.")

        if bottom_tank_temp is None:
            raise Exception("Failed to read the bottom of tank temperature from the eddi unit.")

        if heater_kwh is None:
            raise Exception("Failed to read the heater power (kW) from the eddi unit.")

        if heater_number is None:
            raise Exception("Failed to read the heater number (1 or 2) from the eddi unit.")

        return (top_tank_temp, bottom_tank_temp, heater_kwh, heater_number)

    def set_boost(self, on, mins, relay=None):
        """@brief Set emersion switch on/off
           @param on True sets switch on. If False then switch does not need to be set as both switches are turned off.
           @param mins The number of minutes to boost for.
           @param relay  1 = Top tank heater.
                         2 = bottom tank heater.
                         """
        self._check_eddi_serial_number()
        if on:
            if relay not in (1, 2):
                raise Exception("BUG: set_boost() switch must be 1 or 2.")
            url = MyEnergi.BASE_URL + "cgi-eddi-boost-E"+self._eddi_serial_number+f"-10-{relay}-{mins}"
        else:
            url = MyEnergi.BASE_URL + "cgi-eddi-boost-E"+self._eddi_serial_number+"-1-1-0"
            self._exec_api_cmd(url)

            url = MyEnergi.BASE_URL + "cgi-eddi-boost-E"+self._eddi_serial_number+"-1-2-0"

        self._exec_api_cmd(url)

    def set_all_zappi_schedules_off(self):
        """@brief Set all zappi charge schedules off.
                  We set charge schedules that have no on time and are not enabled for any days of the week.
                  This causes the 4 possible schedules on the zappi to be removed."""
        self._check_eddi_serial_number()
        self._check_zappi_serial_number()

        for sched in MyEnergi.VALID_ZAPPI_SLOT_ID_LIST:
            url = MyEnergi.BASE_URL + f"cgi-boost-time-Z{self._zappi_serial_number}-{sched}-0000-000-00000000"
            self._exec_api_cmd(url)

    def _get_zappi_charge_string(self, charge_slot_dict, slot_id):
        """@detail Get a string that is formated as required by the myenergi zappi api.
           https://github.com/twonk/MyEnergi-App-Api details the api for setting zappi boost times

           From the above page

           'Set boost times

            cgi-boost-time-E10077777-<slot id>-<start time>-<duration>-<day spec>

                start time and duration are both numbers like 60*hours+minutes
                day spec is as bdd above'

            This method returns part of the above string as detailed below.

            '<slot id>-<start time>-<duration>-<day spec>'

           @param charge_slot_dict The dict holding the start stop details of the charge as generated by
                                   GUIServer._set_zappi_charge_thread()
           @param slot_id The slot ID (one of MyEnergi.VALID_ZAPPI_SLOT_ID_LIST).
        """
        start_datetime = charge_slot_dict[RegionalElectricity.SLOT_START_DATETIME]
        stop_datetime = charge_slot_dict[RegionalElectricity.SLOT_STOP_DATETIME]
        duration_timedelta = stop_datetime-start_datetime
        duration_hours, remainder = divmod(duration_timedelta.seconds, 3600)
        duration_minutes, _ = divmod(remainder, 60)
        day_of_week = start_datetime.weekday()  # where Monday is 0 and Sunday is 6

        # We cannot charge for more than 8 hours 59 mins
        if duration_hours > 9:
            raise Exception("The charge time must be less than 9 hours.")

        on_time_string = f"{start_datetime.hour:02d}{start_datetime.minute:02d}"
        duration_string = f"{duration_hours:01d}{duration_minutes:02d}"
        if day_of_week == 0:
            day_of_week_string = "01000000"

        elif day_of_week == 1:
            day_of_week_string = "00100000"

        elif day_of_week == 2:
            day_of_week_string = "00010000"

        elif day_of_week == 3:
            day_of_week_string = "00001000"

        elif day_of_week == 4:
            day_of_week_string = "00000100"

        elif day_of_week == 5:
            day_of_week_string = "00000010"

        elif day_of_week == 6:
            day_of_week_string = "00000001"

        charge_string = f"{slot_id:02d}-{on_time_string}-{duration_string}-{day_of_week_string}"
        return charge_string

    def _exec_api_cmd(self, url):
        """@brief Run a command using the myenergi api and check for errors.
           @return The json response message."""
        response = requests.get(url, auth=HTTPDigestAuth(self._eddi_serial_number, self._api_key))
        if response.status_code != 200:
            raise Exception(f"{response.status_code} error code returned from myenergi server.")
        response_dict = response.json()
        if 'status' in response_dict and response_dict['status'] != 0:
            raise Exception(f"{response_dict['status']} status code returned from myenergi server (should be 0).")
        return response_dict

    def set_zappi_mode_fast_charge(self):
        """@brief Set the mode of the zappi charger to fast charge."""
        url = MyEnergi.BASE_URL + f"cgi-zappi-mode-Z{self._zappi_serial_number}-1-0-0-0000"
        self._exec_api_cmd(url)

    def set_zappi_mode_eco(self):
        """@brief Set the mode of the zappi charger to eco"""
        url = MyEnergi.BASE_URL + f"cgi-zappi-mode-Z{self._zappi_serial_number}-2-0-0-0000"
        self._exec_api_cmd(url)

    def set_zappi_mode_eco_plus(self):
        """@brief Set the mode of the zappi charger to eco+"""
        url = MyEnergi.BASE_URL + f"cgi-zappi-mode-Z{self._zappi_serial_number}-3-0-0-0000"
        self._exec_api_cmd(url)

    def set_zappi_mode_stop(self):
        """@brief Set the mode of the zappi charger to stop"""
        url = MyEnergi.BASE_URL + f"cgi-zappi-mode-Z{self._zappi_serial_number}-4-0-0-0000"
        self._exec_api_cmd(url)

    def set_zappi_charge_schedule(self, charge_slot_dict_list):
        """@brief Set the charge schedule for the zappi.
           @param charge_slot_dict_list A list of dicts holding the start stop details of the charge as generated by
                                   GUIServer._set_zappi_charge_thread()."""
        if len(charge_slot_dict_list) > 4:
            raise Exception("Unable to set zappi charge schedule as only 4 schedules can be set.")

        charge_str_list = []
        for charge_slot_dict, slot_id in zip(charge_slot_dict_list, MyEnergi.VALID_ZAPPI_SLOT_ID_LIST):
            charge_str = self._get_zappi_charge_string(charge_slot_dict, slot_id)
            charge_str_list.append(charge_str)

        # Remove any existing charge schedules.
# PJA If this is executed then the charge schedule fails to get set !!!
#        self.set_all_zappi_schedules_off()

        # Zappi must be in eco+ mode to use schedule
        self.set_zappi_mode_eco_plus()

        # Set each schedule.
        for charge_str in charge_str_list:
            url = MyEnergi.BASE_URL + f"cgi-boost-time-Z{self._zappi_serial_number}-"+charge_str
            self._exec_api_cmd(url)


class ColorButton(ui.button):

    def __init__(self, callBack=None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._state = False
        self.on('click', callBack)

    def set_on(self, on):
        """@brief Set state on/off
           @param on If True set button color to green, else grey."""
        self._state = on
        self.update()

    def update(self) -> None:
        """@brief Update the button state."""
        self.props(f'color={"green" if self._state else GUIServer.DEFAULT_BUTTON_COLOR}')
        super().update()


class RegionalElectricity(object):
    """@brief Responsible for reading and processing octopus agile tariff data.
    """
    VALID_REGION_CODE_LIST = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P']
    VALID_REGION_CODE_LIST_WITH_REGIONS = ['A Eastern England',
                                           'B East Midlands',
                                           'C London',
                                           'D North Wales, Merseyside and Cheshire',
                                           'E West Midlands',
                                           'F North East England',
                                           'G North West England',
                                           'H Southern England',
                                           'J South East England',
                                           'K South Wales',
                                           'L South West England',
                                           'M Yorkshire',
                                           'N Southern Scotland',
                                           'P Northern Scotland']
    BOKEH_TOOLS = "box_zoom,reset,save,box_select"
    SLOT_START_DATETIME = "SLOT_START_DATETIME"
    SLOT_STOP_DATETIME = "SLOT_STOP_DATETIME"
    SLOT_COST = "SLOT_COST"

    def __init__(self, uio):
        """@brief Constructor
           @param uio A UIO instance."""
        self._uio = uio

    def _get_cost_dict(self, region_code):
        """@brief Get a dict of the cost of electricity based on region. See https://mysmartenergy.uk/Electricity-Region for region code list."""
        if region_code not in RegionalElectricity.VALID_REGION_CODE_LIST:
            raise Exception(f'{region_code} is an invalid region code ({",".join(RegionalElectricity.VALID_REGION_CODE_LIST)} are valid).')
        url_str = f'https://api.octopus.energy/v1/products/AGILE-FLEX-22-11-25/electricity-tariffs/E-1R-AGILE-FLEX-22-11-25-{region_code}/standard-unit-rates/'

        self._uio.debug(f"Energy cost request URL: {url_str}")
        with urllib.request.urlopen(url_str) as url:
            data = json.load(url)

        resultsDict = data['results']
        costDict = {}
        for record in resultsDict:
            costPence = record["value_inc_vat"]
            startT = datetime.strptime(record["valid_from"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            costDict[startT] = costPence
        return costDict

    def get_prices(self, region_code, end_charge_time):
        """@brief Get the price of electricity over the next day or so as a dict.
           @param region_code The region of the UK for the electricity prices.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed.
           @return Two lists
                   0 = A list of timestamps. This includes the start and end of each 1/2 hour slot.
                   1 = The price of electricity in £ in that 1/2 hour slot.
                   2 = The end of charge date time object or None if not defined."""

        costDict = self._get_cost_dict(region_code)
        now = datetime.now().astimezone()
        _timeStampList = list(costDict.keys())
        _timeStampList.sort()
        # If the user requires the charge to be complete by a certain time
        end_charge_datetime = None
        if end_charge_time:
            last_time_stamp = _timeStampList[-1]
            end_charge_datetime = last_time_stamp.replace(hour=end_charge_time[0], minute=end_charge_time[1], second=0, microsecond=0)
        timeStampList = []
        costList = []
        for ts in _timeStampList:
            # Ignore all times that are in the past
            if ts < now:
                continue
            # Ignore times after the end charge time
            if end_charge_datetime and ts > end_charge_datetime:
                continue
            timeStampList.append(ts)
            cost = costDict[ts]/100.0
            # Add the end of this 1/2 hour slot
            costList.append(cost)
#            timeStampList.append(ts++ timedelta(minutes=30))
#            costList.append(costDict[ts]/100.0)
        return (timeStampList, costList, end_charge_datetime)


class GUIServer(object):

    MYENERGI_API_KEY = 'MYENERGI_API_KEY'
    EDDI_SERIAL_NUMBER = 'EDDI_SERIAL_NUMBER'
    ZAPPI_SERIAL_NUMBER = 'ZAPPI_SERIAL_NUMBER'
    ZAPPI_MAX_CHARGE_RATE = 'ZAPPI_MAX_CHARGE_RATE'
    ELECTRICITY_REGION_CODE = 'ELECTRICITY_REGION_CODE'
    OCTOPUS_AGILE_TARIFF = 'OCTOPUS_AGILE_TARIFF'
    TARIFF_POINT_LIST = "TARIFF_POINT_LIST"

    DEFAULT_CONFIG = {MYENERGI_API_KEY: "",
                      EDDI_SERIAL_NUMBER: "",
                      ZAPPI_SERIAL_NUMBER: "",
                      ZAPPI_MAX_CHARGE_RATE: "7.4",
                      ELECTRICITY_REGION_CODE: "",
                      OCTOPUS_AGILE_TARIFF: True,
                      TARIFF_POINT_LIST: []}

    TAB_BAR_STYLE = 'font-size: 20px; color: lightgreen;'
    TEXT_STYLE_A = 'font-size: 40px; color: white;'
    TEXT_STYLE_A_SIZE = 'font-size: 20px;'
    TEXT_STYLE_B = 'font-size: 40px; color: lightgreen;'
    TEXT_STYLE_C = 'font-size: 15px; color: lightgreen;'

    BOOST_1_ON = "BOOST_1_SET_ON"
    BOOST_2_ON = "BOOST_2_SET_ON"
    BOOST_OFF = "BOOST_OFF"
    TANK_TEMPERATURES = "TANK_TEMPERATURES"
    INFO_MESSAGE = "INFO_MESSAGE"
    ERROR_MESSAGE = "ERROR_MESSAGE"
    TEMP_UPDATE_SECONDS = 5.0                 # We don't want to poll the myenergi server to fast as it will load it unnecessarily.
    DEFAULT_SERVER_PORT = 20000
    GUI_POLL_SECONDS = 0.1
    TARIFF_LIST = ["Octopus Agile Tarrif", 'Other Tarrif']
    SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE = "Set zappi charge schedule"
    DEFAULT_BUTTON_COLOR = "blue"
    CLEARED_ALL_CHARGING_SCHEDULES = "Cleared all zappi charging schedules."

    def __init__(self, uio, port):
        """@brief Constructor
           @param uio A UIO instance.
           @param port The TCP port to bind the nicegui server."""
        self._uio = uio
        self._port = port
        # This queue is used to send commands from any thread to the GUI thread.
        self._to_gui_queue = Queue()
        self._my_energi = MyEnergi('')
        self._eddi_update_seconds = GUIServer.TEMP_UPDATE_SECONDS
        self._next_temp_update_time = time()+self._eddi_update_seconds
        self._heater_load = 0.0
        self._relay_on = 0
        self._eddi_heater_button_selected = 0
        self._electricity_region_code = ''
        self._charge_slot_dict_list = None
        self._octopus_agile_tariff = True
        self._other_tariff_values = []
        self._read_temp_thread = None
        self._cfg_mgr = DotConfigManager(GUIServer.DEFAULT_CONFIG, uio=self._uio)
        self._load_config()

    def _load_config(self):
        """@brief Load the config from a config file."""
        try:
            self._cfg_mgr.load()
            self._create_myenergi()
            self._other_tariff_values = self._cfg_mgr.getAttr(GUIServer.TARIFF_POINT_LIST)
        except Exception:
            # If config does not exist we use the defaults
            pass

    def _create_myenergi(self):
        """@brief Create an object to talk to the myenergi products."""
        self._my_energi = MyEnergi(self._cfg_mgr.getAttr(GUIServer.MYENERGI_API_KEY))
        self._my_energi.set_eddi_serial_number(self._cfg_mgr.getAttr(GUIServer.EDDI_SERIAL_NUMBER))
        self._my_energi.set_zappi_serial_number(self._cfg_mgr.getAttr(GUIServer.ZAPPI_SERIAL_NUMBER))

    def _save_config(self):
        """@brief Save some parameters to a local config file."""

        region_code = self._electricity_region_code.value
        if region_code is None or region_code not in RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS:
            ui.notify("ERROR: Electricity region code not set.", type='negative')

        else:
            if self._check_eddi_access_ok():
                self._cfg_mgr.addAttr(GUIServer.ELECTRICITY_REGION_CODE, region_code)
                self._cfg_mgr.addAttr(GUIServer.MYENERGI_API_KEY,    self._api_key.value)
                self._cfg_mgr.addAttr(GUIServer.EDDI_SERIAL_NUMBER,  self._eddi_serial_number.value)
                # If a zappi serial number has been entered and the zappi cannot be reached.
                if len(self._zappi_serial_number.value) > 0 and not self._check_zappi_access_ok():
                    # Don't proceed with saving
                    return
                self._cfg_mgr.addAttr(GUIServer.ZAPPI_SERIAL_NUMBER, self._zappi_serial_number.value)
                # The user may leave the zappi charge rate field empty
                if len(self._zappi_max_charge_rate.value) > 0:
                    try:
                        float(self._zappi_max_charge_rate.value)
                    except ValueError:
                        ui.notify(f"ERROR: {self._zappi_max_charge_rate.value} is an invalid zappi charge rate (kW).", type='negative')
                        # Don't proceed with saving
                        return
                self._cfg_mgr.addAttr(GUIServer.ZAPPI_MAX_CHARGE_RATE, self._zappi_max_charge_rate.value)

                octopus_agile_tariff = self._is_octopus_agile_tariff_enabled()
                self._cfg_mgr.addAttr(GUIServer.OCTOPUS_AGILE_TARIFF, octopus_agile_tariff)
                self._cfg_mgr.addAttr(GUIServer.TARIFF_POINT_LIST, self._other_tariff_values)
                self._cfg_mgr.store()
                # Create a new instance of the interface to talk to the myenergi products
                self._create_myenergi()
                ui.notify(f"Saved to {self._cfg_mgr._getConfigFile()}")

    def _is_octopus_agile_tariff_enabled(self):
        """@brief Determine if the user has selectedt the Octopus agile tariff.
           @return True if enabled false if not."""
        octopus_agile_tariff = False
        if self._tarrif_radio.value == GUIServer.TARIFF_LIST[0]:
            octopus_agile_tariff = True
        return octopus_agile_tariff

    def _info(self, msg):
        """@brief Show an info level message."""
        if self._uio:
            self._uio.info(msg)

    def _error(self, msg):
        """@brief Show an error level message."""
        if self._uio:
            self._uio.error(msg)

    def _debug(self, msg):
        """@brief Show an debug level message."""
        if self._uio:
            self._uio.debug(msg)

    def create_gui(self, debugEnabled, reload=False, show=False):
        """@brief Create the GUI elements
           @param debugEnabled True enables debug.
           @param reload If True restart when this file is updated. Useful for dev.
           @param show If True show the GUI on startup, ie open a browser window."""
        self._temp1 = 60
        self._temp2 = 40
        self._buttonList = []

        pageTitle = f"myenergi display (V{TabbedNiceGui.GetProgramVersion()})"
        address = "0.0.0.0"
        tabNameList = ('EDDI',
                       'ZAPPI',
                       'SETTINGS')
        iconList = ('home',
                    'electric_car',
                    'settings')
        # This must have the same number of elements as the above list
        tabMethodInitList = [self._init_eddi_tab,
                             self._init_zappi_tab,
                             self._init_settings_tab]
        tabObjList = []
        with ui.row().style(GUIServer.TAB_BAR_STYLE):
            with ui.tabs().classes('w-full') as tabs:
                for tabName, iconName in zip(tabNameList, iconList):
                    tabObj = ui.tab(tabName, icon=iconName)
                    tabObjList.append(tabObj)

            with ui.tab_panels(tabs, value=tabObjList[0]).classes('w-full'):
                for tabObj in tabObjList:
                    with ui.tab_panel(tabObj):
                        tabIndex = tabObjList.index(tabObj)
                        tabMethodInitList[tabIndex]()

        guiLogLevel = "warning"
        if debugEnabled:
            guiLogLevel = "debug"

        ui.timer(interval=0.1, callback=self._gui_timer_callback)
        ui.run(host=address,
               port=self._port,
               title=pageTitle,
               dark=True,
               uvicorn_logging_level=guiLogLevel,
               reload=reload,
               show=show)

    def _get_heater_on(self):
        """@brief Determine if a lod is being drawn by heater 1 or heater 2 (relay 1 or relay 2 on).
           @return 1 If top relay is on and power is being drawn by the heater.
                   2 If bottom relay is on and power is being drawn by the heater.
                   else return 0."""
        relay_on = 0
        # We use a 2.6 kW threshold to determine of the heater is on.
        if self._heater_load > 2600:
            if self._relay_on == 1:
                relay_on = 1
            elif self._relay_on == 2:
                relay_on = 2
        return relay_on

    def _gui_timer_callback(self):
        """@called periodically (quickly) to allow updates of the GUI."""

        while not self._to_gui_queue.empty():
            rxMessage = self._to_gui_queue.get()
            if isinstance(rxMessage, dict):
                self._process_rx_dict(rxMessage)

        if time() >= self._next_temp_update_time:
            # Don't update the tank temperatures in the gui thread or the gui thread will block
            # if there are issues getting data over the internet.
            # Only start a new thread if we haven't started one yet or the old one has completed.
            # This stops many threads backing up if there are internet connectivity issues.
            if self._read_temp_thread is None or not self._read_temp_thread.isAlive():
                self._read_temp_thread = threading.Thread(target=self._update_tank_temperatures).start()
            self._next_temp_update_time = time()+self._eddi_update_seconds

        heater_on = self._get_heater_on()
        if heater_on == 1:
            self._boost_top_button.set_on(True)
        elif heater_on == 2:
            self._boost_bottom_button.set_on(True)
        else:
            self._boost_top_button.set_on(False)
            self._boost_bottom_button.set_on(False)

    def _process_rx_dict(self, rxDict):
        """@brief Process the dicts received from the GUI message queue.
           @param rxDict The dict received from the GUI message queue."""

        if GUIServer.BOOST_1_ON in rxDict:
            self._boost_top_button.set_on(True)

        elif GUIServer.BOOST_2_ON in rxDict:
            self._boost_bottom_button.set_on(True)

        elif GUIServer.BOOST_OFF in rxDict:
            self._boost_top_button.set_on(False)
            self._boost_bottom_button.set_on(False)

        elif GUIServer.ERROR_MESSAGE in rxDict:
            error_message = rxDict[GUIServer.ERROR_MESSAGE]
            ui.notify(f"ERROR: {error_message}", type='negative')

        elif GUIServer.INFO_MESSAGE in rxDict:
            info_message = rxDict[GUIServer.INFO_MESSAGE]
            ui.notify(info_message)
            # If we have confirmation from myenergi that the charge schedule was applied
            if info_message == GUIServer.SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE:
                self._set_zappi_charge_active(True)
            # If we have confirmation from myenergi that all charge schedules were removed
            if info_message == GUIServer.CLEARED_ALL_CHARGING_SCHEDULES:
                self._set_zappi_charge_active(False)

        elif GUIServer.TANK_TEMPERATURES in rxDict:
            top_tank_temp, bottom_tank_temp = rxDict[GUIServer.TANK_TEMPERATURES]
            self._topTankTempLabel.text = top_tank_temp
            self._bottomTankTempLabel.text = bottom_tank_temp

    def _init_eddi_tab(self):
        """@brief Init the tab used for access to EDDI stats and control."""
        with ui.row().style(GUIServer.TEXT_STYLE_A):
            with ui.column():
                ui.label("Tank")
                ui.label("Top")
                ui.label("Bottom")
            with ui.column():
                ui.label('°C')
                self._topTankTempLabel = ui.label("").style(GUIServer.TEXT_STYLE_B)
                self._bottomTankTempLabel = ui.label("").style(GUIServer.TEXT_STYLE_B)
        html.hr()

        with ui.row():
            ui.label('Boost Control').style(GUIServer.TEXT_STYLE_A)

        with ui.row():
            self._boost_top_button = ColorButton(self._top_boost, 'Top').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            self._boost_bottom_button = ColorButton(self._bottom_boost, 'Bottom').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            self._boost_stop_button = ColorButton(self._stop_boost, 'Off').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            self._buttonList.append(self._boost_top_button)
            self._buttonList.append(self._boost_bottom_button)
            # We don't add the _boost_stop_button to this list so that we can always issue a stop boost command
            # as the button will never be disabled.

        with ui.row():
            ui.label('Boost Minutes').style(GUIServer.TEXT_STYLE_A)

        with ui.row().classes('w-full'):
            self._bootMinsSlider = ui.slider(min=15, max=120, value=30, step=15)
            ui.label().bind_text_from(self._bootMinsSlider, 'value').style(GUIServer.TEXT_STYLE_B)

    def _enable_buttons(self, enabled):
        for _button in self._buttonList:
            if enabled:
                _button.enable()
            else:
                _button.disable()

    def _top_boost(self):
        self._eddi_heater_button_selected = 1
        self._enable_buttons(False)
        ui.notify("Setting top boost on.", position='center', type='ongoing', timeout=15000)
        threading.Thread(target=self._set_boost, args=(True, MyEnergi.TANK_TOP)).start()

    def _bottom_boost(self):
        self._eddi_heater_button_selected = 2
        self._enable_buttons(False)
        ui.notify("Setting bottom boost on.", position='center', type='ongoing', timeout=15000)
        threading.Thread(target=self._set_boost, args=(True, MyEnergi.TANK_BOTTOM)).start()

    def _stop_boost(self):
        self._eddi_heater_button_selected = 0
        self._enable_buttons(True)
        self._boost_top_button.set_on(False)
        self._boost_bottom_button.set_on(False)
        ui.notify("Turning off boost.", position='center', type='ongoing', timeout=11000)
        threading.Thread(target=self._set_boost, args=(False, None)).start()

    def _update_gui(self, msg_dict):
        """@brief Send a message to the GUI to update it.
           @param msg_dict A dict containing details of how to update the GUI."""
        # Record the seconds when we received the message
        msg_dict[GUIServer.GUI_POLL_SECONDS] = time()
        self._to_gui_queue.put(msg_dict)

    def _set_boost(self, on, relay):
        """@brief Called in a separate thread to talk to the eddi unit and set the hot water boost state.
           @param on If True turn boost on. If False turn boost off on both top and bottom tanks.
           @param relay 1 = top tank relay, 2 = bottom tank relay.
           """
        try:
            self._my_energi.set_boost(on, self._bootMinsSlider.value, relay=relay)
            if on:
                if relay == 1:
                    retDict = {GUIServer.BOOST_1_ON: True}

                elif relay == 2:
                    retDict = {GUIServer.BOOST_2_ON: True}

            else:
                retDict = {GUIServer.BOOST_OFF: True}

            self._update_gui(retDict)

        except Exception as ex:
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _update_tank_temperatures(self):
        """@brief Update the tank temperatures."""
        try:
            top_temp, bottom_temp, self._heater_load, self._relay_on = self._my_energi.get_tank_stats()
            msg_dict = {}
            msg_dict[GUIServer.TANK_TEMPERATURES] = [top_temp, bottom_temp]
            self._update_gui(msg_dict)
        except Exception as ex:
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _init_settings_tab(self):
        """@brief Init the tab used to hold app settings."""
        with ui.row():
            self._api_key = ui.input(label='myenergi API Key').style("width: 300px; "+GUIServer.TEXT_STYLE_A_SIZE)
        with ui.row():
            self._eddi_serial_number = ui.input(label='eddi serial number').style("width: 300px; "+GUIServer.TEXT_STYLE_A_SIZE)
        with ui.row():
            self._zappi_serial_number = ui.input(label='zappi serial number').style("width: 300px; "+GUIServer.TEXT_STYLE_A_SIZE)
        with ui.row():
            self._zappi_max_charge_rate = ui.select(options=["7.4", "22"],
                                                    value="7.4",
                                                    with_input=True,
                                                    label='Zappi charge rate')
        with ui.row():
            self._electricity_region_code = ui.select(options=RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS,
                                                      value=RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS[0],
                                                      with_input=True,
                                                      label='Electricity region code')

        with ui.row():
            self._tarrif_radio = ui.radio(GUIServer.TARIFF_LIST,
                                          on_change=self._tariff_changed,
                                          value=GUIServer.TARIFF_LIST[0])

        with ui.row():
            # A plot of energy costs is added to this container when the users requests it
            self._other_tariff_plot_container = ui.element('div')

        with ui.row():
            self._add_tariff_value_button = ui.button('Add', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._add_tariff_value)
# PJA           self._plot_tariff_button = ui.button('Plot', on_click=self._plot_tariff)
            self._clear_tariff_value_button = ui.button('Clear', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._clear_tariff)

        with ui.row():
            self._config_save_button = ui.button('Save', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._save_config)

        self._api_key.value = self._cfg_mgr.getAttr(GUIServer.MYENERGI_API_KEY)
        self._eddi_serial_number.value = self._cfg_mgr.getAttr(GUIServer.EDDI_SERIAL_NUMBER)
        self._zappi_serial_number.value = self._cfg_mgr.getAttr(GUIServer.ZAPPI_SERIAL_NUMBER)
        self._zappi_max_charge_rate.value = self._cfg_mgr.getAttr(GUIServer.ZAPPI_MAX_CHARGE_RATE)
        self._electricity_region_code.value = self._cfg_mgr.getAttr(GUIServer.ELECTRICITY_REGION_CODE)
        self._octopus_agile_tariff = self._cfg_mgr.getAttr(GUIServer.OCTOPUS_AGILE_TARIFF)
        self._set_octopus_agile_tariff(self._octopus_agile_tariff)
        self._enable_octopus_agile_tariff(self._octopus_agile_tariff)

    def _set_octopus_agile_tariff(self, enabled):
        """@brief Set the radio buttons to enable the octopus agile tariff or the other (manually entered) tariff."""
        if enabled:
            self._tarrif_radio.value = GUIServer.TARIFF_LIST[0]
        else:
            self._tarrif_radio.value = GUIServer.TARIFF_LIST[1]

    def _enable_octopus_agile_tariff(self, enabled):
        """@brief Called when the octopus agile tariff is enabled."""
        if enabled:
            self._add_tariff_value_button.disable()
# PJA           self._plot_tariff_button.disable()
            self._clear_tariff_value_button.disable()
        else:
            self._add_tariff_value_button.enable()
# PJA           self._plot_tariff_button.enable()
            self._clear_tariff_value_button.enable()

    def _tariff_changed(self):
        """@brief Called when the tarrif radio button is selected."""
        octopus_agile_tariff = self._is_octopus_agile_tariff_enabled()
        self._enable_octopus_agile_tariff(octopus_agile_tariff)
        if octopus_agile_tariff:
            self._add_tariff_value_button.disable()
#            self._plot_tariff_button.disable()
            self._clear_tariff_value_button.disable()
            if self._other_tariff_plot_container:
                self._other_tariff_plot_container.clear()

        else:
            self._add_tariff_value_button.enable()
#            self._plot_tariff_button.enable()
            self._clear_tariff_value_button.enable()
            self._plot_tariff()

    def _add_tariff_value(self):
        """@brief Add a tariff value to the displayed other tariff."""
        self._add_tariff_dialog = YesNoDialog("Add one tarrif point.",
                                              self._tariff_value_entered,
                                              successButtonText="OK",
                                              failureButtonText="Cancel")
        self._add_tariff_dialog.addField("Start time", YesNoDialog.HOUR_MIN_INPUT_FIELD_TYPE)
        self._add_tariff_dialog.addField("Price (£)", YesNoDialog.NUMBER_INPUT_FIELD_TYPE, minNumber=0, maxNumber=2, step=0.01)
        self._add_tariff_dialog.show()

    def _get_hour_min(self, tstr):
        """@brief Get the hour and min from a single tariff point.
           @return A tuple containing
                   0 = hour
                   1 = min"""
        hour = -1
        min = -1
        elems = tstr.split(':')
        if len(elems) == 2:
            try:
                hour = int(elems[0])
                min = int(elems[1])
            except ValueError:
                pass
        if hour == -1 or min == -1:
            raise Exception(f"{tstr} is invalid (HH:MM expected).")
        return (hour, min)

    def _tariff_value_entered(self):
        start_time = self._add_tariff_dialog.getValue('Start time')
        price = self._add_tariff_dialog.getValue("Price (£)")
        try:
            if start_time and len(start_time) > 0 and price > 0.0:
                hour, min = self._get_hour_min(start_time)
                # If this is the first tariff data then it must start at the start of the day.
                if len(self._other_tariff_values) == 0 and (hour != 0 or min != 0):
                    raise Exception("The first tariff value must start at 00:00 (HH:MM).")

                if len(self._other_tariff_values) > 0:
                    this_hour, this_min = self._get_hour_min(start_time)
                    last_hour, last_min = self._get_hour_min(self._other_tariff_values[-1][0])
                    in_seq = False
                    if last_hour < this_hour:
                        in_seq = True

                    elif last_hour == this_hour:
                        if last_min < this_min:
                            in_seq = True

                    if not in_seq:
                        raise Exception(f"tariff list is not ascending ({this_hour:02d}:{this_min:02d} is not after the previous one, {last_hour:02d}:{last_min:02d}).")

                tariff_point = (start_time, price)
                # PJA Add checks for duplicate start times
                self._other_tariff_values.append(tariff_point)
                self._plot_tariff()

        except Exception as ex:
            logTraceBack(self._uio)
            ui.notify(f"{str(ex)}", type='negative')

    def _get_tariff(self):
        """@brief get a list of the tariff string values converted to datetime instances.
           @return tariff_datetime_list A list. Each element has two elements.
                   0: A datetime instance at incrementing times during the day.
                   1: The price of the electricity at that point in the day."""
        if len(self._other_tariff_values) == 0:
            raise Exception("No tariff values found.")

        # Convert the tariff times into datetime instances
        tariff_list = []
        index = 0
        for other_tariff_value in self._other_tariff_values:
            hour, min = self._get_hour_min(other_tariff_value[0])
            price = other_tariff_value[1]
            dt = datetime.now().astimezone()
            dt = dt.replace(minute=min, hour=hour, second=0, microsecond=0)
            # Check the datetime is not in the list twice
            if dt in tariff_list:
                raise Exception(f"{hour:02d}:{min:02d} is in the tariff list twice.")

            tariff_list.append((deepcopy(dt), price))
            index = index + 1
        return tariff_list

    def _get_price(self, _datetime):
        """@brief Get the price of the electricity at the given time.
           @param _datetime The datetime of interest.
           @return The price of electricity per kWh at the given time of day or None if no tariff data is available."""
        tariff_data = self._get_tariff()
        if tariff_data and len(tariff_data) > 0:
            price = tariff_data[0][1]
            for data in tariff_data:
                dt = data[0]
#                if _datetime < dt:
#                    break

                if _datetime.hour < dt.hour:
                    break
                elif _datetime.hour == dt.hour and _datetime.minute < dt.minute:
                    break
#                elif _datetime.hour == dt.hour and datetime.minute < dt.minute:
#                    break
                price = data[1]
        return price

    def _plot_tariff(self):
        """@brief Plot the available tariff data."""
        try:
            ui.notify("Plotting the tariff data.", position='center', type='ongoing', timeout=2000)
            now = datetime.now().astimezone()
            start_of_this_day = now.replace(minute=0, hour=0, second=0)
            # Get a value for every 1/2 hour through the day
            time_intervals = [start_of_this_day + timedelta(minutes=30 * i) for i in range((24*2))]
            price_list = []
            for time_interval in time_intervals:
                price = self._get_price(time_interval)
                price_list.append(price)

            prices = price_list

            fig = go.Figure()
            max_cost = max(prices)
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0),
                              width=350,
                              height=150,
                              showlegend=False,
                              plot_bgcolor="black",       # Background for the plot area
                              paper_bgcolor="black",      # Background for the entire figure
                              font=dict(color="yellow"),  # Font color for labels and title
                              xaxis=dict(
                                  title='Day (HH:MM)',
                                  tickformat='%H:%M',     # Format as hours:minutes
                                  color="yellow",         # Axis label color
                                  gridcolor="gray",       # Gridline color
                                  zerolinecolor="gray"    # Zero line color
                              ),
                              yaxis=dict(
                                  title="£ per kWh",
                                  color="yellow",         # Axis label color
                                  gridcolor="gray",       # Gridline color
                                  zerolinecolor="gray",   # Zero line color
                                  range=[0, max_cost*1.5]
                              ),)
    #        fig.add_trace(go.Scatter(x=time_intervals, y=prices, marker=dict(color='green')))
            fig.add_trace(go.Bar(x=time_intervals, y=prices, marker=dict(color='green')))
            if self._other_tariff_plot_container:
                self._other_tariff_plot_container.clear()
                # Add the new plot to the container
                with self._other_tariff_plot_container:
                    ui.plotly(fig)

        except Exception as ex:
            ui.notify(f"ERROR: {str(ex)}", type='negative')

    def _clear_tariff(self):
        """@brief Clear the other tariff values."""
        self._other_tariff_values = []
        if self._other_tariff_plot_container:
            self._other_tariff_plot_container.clear()

    def _check_eddi_access_ok(self):
        """@brief Check that the stats can be read from the myenergi eddi unit.
           @return True if eddi access ok."""
        ok = False
        try:
            myEnergi = MyEnergi(self._api_key.value)
            myEnergi.set_eddi_serial_number(self._eddi_serial_number.value)
            myEnergi.get_eddi_stats()
            ui.notify("Successfully read eddi stats.", position='center')
            ok = True
        except Exception as ex:
            ui.notify(f"EDDI ERROR: {str(ex)}", type='negative')
        return ok

    def _check_zappi_access_ok(self):
        """@brief Check that the stats can be read from the myenergi zappi unit.
           @return True if eddi access ok."""
        ok = False
        try:
            myEnergi = MyEnergi(self._api_key.value)
            myEnergi.set_eddi_serial_number(self._eddi_serial_number.value)
            myEnergi.set_zappi_serial_number(self._zappi_serial_number.value)
            myEnergi.get_zappi_stats()
            ui.notify("Successfully read zappi stats.", position='center')
            ok = True
        except Exception as ex:
            ui.notify(f"ZAPPI ERROR: {str(ex)}", type='negative')
        return ok

    def _show_regional_codes(self):
        """@brief Show the regional electricity codes.
                  Not used."""
        ui.html('<style>.multi-line-notification { white-space: pre-line; }</style>')
        ui.notify(
            'A 	Eastern England. \n'
            'B 	East Midlands \n'
            'C 	London \n'
            'D 	North Wales, Merseyside and Cheshire \n'
            'E 	West Midlands \n'
            'F 	North East England \n'
            'G 	North West England \n'
            'H 	Southern England \n'
            'J 	South East England \n'
            'K 	South Wales \n'
            'L 	South West England \n'
            'M 	Yorkshire \n'
            'N 	Southern Scotland \n'
            'P 	Northern Scotland \n',
            multi_line=True,
            classes='multi-line-notification',
            position='center'
        )

    def _init_zappi_tab(self):
        """@brief Init the tab used for access to ZAPPI stats and control."""
        ui.label('Charge (kWh)')
        with ui.row().classes('w-full'):
            self._charge_slider = ui.slider(min=0, max=100, value=0, step=1).style("width: 250px;")
            with ui.column():
                ui.label().bind_text_from(self._charge_slider, 'value').style(GUIServer.TEXT_STYLE_B)

        ui.label('Charge (minutes)')
        with ui.row().classes('w-full'):
            self._charge_time_mins_slider = ui.slider(min=0, max=539, value=0, step=15).style("width: 250px;")
            with ui.column():
                ui.label().bind_text_from(self._charge_time_mins_slider, 'value').style(GUIServer.TEXT_STYLE_B)

        with ui.row():
            # A plot of energy costs is added to this container when the users requests it
            self._plot_container = ui.element('div')

        with ui.row():
            self._calc_button = ColorButton(self._calc_optimal_charge_times, 'Calc Charge')
            self._calc_button.tooltip("Calculate the optimal charge time/s.")
            self._set_button = ColorButton(self._set_zappi_charge, 'Set')
            self._set_button.tooltip('Set the displayed charge schedule on your zappi charger.\nGreen when the charger has accepted the schedule.')
            reset_button = ui.button('Clear', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._reset_zappi_charge)
            reset_button.tooltip('Clear all charge schedules from your zappi charger.')

        # Put this off the bottom of the mobile screen as most times it will not be needed
        # and there is not enough room on the mobile screen above the plot pane.
        self._end_charge_time_input = self._get_input_time_field('Ready by')

    def _set_zappi_charge_active(self, active):
        """@brief Set the indicator to the user that shows that the zappi charge is active/inactive.
           @param active If True then a zappi charge schedule has been set."""
        self._set_button.set_on(active)
        if active:
            self._calc_button.disable()
        else:
            self._calc_button.enable()

    def _get_input_time_field(self, label):
        """@brief Add a control to allow the user to enter the time as an hour and min.
           @param label The label for the time field.
           @return The input field containing the hour and minute entered."""
        # Put this off the bottom of the mobile screen as most times it will not be needed
        # and there is not enough room on the mobile screen above the plot pane.
        with ui.row().classes('w-full'):
            ui.label(label)
            time_input = ui.input("Time (HH:MM)")
            with time_input as time:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.time().bind_value(time):
                        with ui.row().classes('justify-end'):
                            ui.button('Close', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=menu.close).props('flat')
                with time.add_slot('append'):
                    ui.icon('access_time').on('click', menu.open).classes('cursor-pointer')
        return time_input

    def _get_end_charge_time(self):
        """@brief Get the end charge time.
           @return A tuple
                   0 = Hours
                   1 = mins"""
        hours = None
        mins = None
        elems = self._end_charge_time_input.value.split(':')
        if len(elems) == 2:
            hours_str = elems[0]
            mins_str = elems[1]
            try:
                hours = int(hours_str)
                mins = int(mins_str)
            except ValueError:
                pass
        if hours is not None and mins is not None:
            return (hours, mins)
        return None

    def _calc_optimal_charge_times(self):
        """@brief Calculate the optimal charge times."""
        charge = float(self._charge_slider.value)
        charge_time_mins = float(self._charge_time_mins_slider.value)

        if charge == 0 and charge_time_mins == 0 or \
           charge != 0 and charge_time_mins != 0:
            ui.notify("You must set either the charge or charge time greater than 0.", type='negative')
            return

        if charge > 0:
            charge_time_mins = int((charge/float(self._zappi_max_charge_rate.value))*60)
            # Ensure a multiple of 15 mins as we don't want to be turning the charger on/off
            # any more quickly than this.
            remainder = charge_time_mins % 15
            if remainder > 0:
                charge_time_mins = charge_time_mins - remainder

        region_code = self._get_region_code()
        ui.notify("Calculating optimal charge time/s.", position='center', type='ongoing', timeout=2000)
        self._set_zappi_charge_active(False)
        threading.Thread(target=self.calc_optimal_charge_times_thread, args=(region_code,
                                                                             self._plot_container,
                                                                             charge_time_mins,
                                                                             float(self._zappi_max_charge_rate.value),
                                                                             self._get_end_charge_time())).start()

    def _get_region_code(self):
        """@brief Get the electricity region code.
           @return The single letter electricity region code or None if not set."""
        region_code = self._electricity_region_code.value
        if region_code:
            elems = region_code.split()
            region_code = elems[0]
        return region_code

    def _get_tariff_data(self, end_charge_time):
        """@brief Get the tariff data needed to calculate the best charge times when not
                  one octopus agile tariff.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed."""
        now = datetime.now().astimezone()

        # Ensure we start from a time at least 30 mins in the future
        start_datetime = now + timedelta(minutes=60)
        start_datetime = start_datetime.replace(minute=0, second=0, microsecond=0)

        # Get a value for every 1/2 hour through the day and into the next
        time_intervals = [start_datetime + timedelta(minutes=30 * i) for i in range((48*2))]

        # If the end charge time is defined then ensure we don't have time after this in the list.
        if end_charge_time:
            then = now.replace(hour=end_charge_time[0], minute=end_charge_time[1], second=0, microsecond=0)
            # If this time is in the past
            if then < now:
                # Move the hour:min time to next day
                then = now.replace(day=now.day+1, hour=end_charge_time[0], minute=end_charge_time[1], second=0, microsecond=0)
            tmp_time_intervals = []
            for time_interval in time_intervals:
                if then < time_interval:
                    break
                tmp_time_intervals.append(time_interval)
            time_intervals = tmp_time_intervals

        price_list = []
        for time_interval in time_intervals:
            price = self._get_price(time_interval)
            price_list.append(price)

        return (time_intervals, price_list)

    def _get_charge_details(self, charge_mins, end_charge_time, charge_rate_kw, region_code):
        """@brief Get the requested charge details.
           @param charge_mins The required charge time in mins.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed.
           @param charge_rate_kw The rate at which the charger will charge the EV in kW.
           @param region_code The regional electricity code.
           @return A tuple containing
                   0: A list of charge details dicts.
                   1: The end charge time (datetime instance)
                   2: A list of the charge slot start times.
                   3: A list of the costs for each charge slot.
                   4: The total charge time in mins.
                   5: The total charge cost"""
        if self._is_octopus_agile_tariff_enabled():
            regional_electricity = RegionalElectricity(self._uio)
            plot_time_stamp_list, plot_cost_list, end_charge_datetime = regional_electricity.get_prices(region_code, end_charge_time)
        else:
            plot_time_stamp_list, plot_cost_list = self._get_tariff_data(end_charge_time)
            end_charge_datetime = plot_time_stamp_list[-1]
            if end_charge_time:
                end_charge_datetime = plot_time_stamp_list[-1].replace(hour=end_charge_time[0], minute=end_charge_time[1], second=0, microsecond=0)

        # Check we have enough time to add the required charge
        available_charge_time = end_charge_datetime - plot_time_stamp_list[0]
        available_mins = available_charge_time.total_seconds()/60
        if charge_mins > available_mins:
            ect = end_charge_datetime.strftime("%H:%M on %d %B")
            raise Exception(f"Unable to charge for {charge_mins} minutes before {ect}")

        # Determine the slot duration (30mins ?)
        slot_start_t = plot_time_stamp_list[0]
        slot_end_t = plot_time_stamp_list[1]
        slot_duration = slot_end_t-slot_start_t
        slot_duration_mins = slot_duration.total_seconds()/60.0

        time_stamp_list = plot_time_stamp_list
        cost_list = plot_cost_list

        # Pair dates with costs and sort by cost
        sorted_pairs = sorted(zip(cost_list, time_stamp_list))

        # Unzip into separate sorted lists
        sorted_costs, sorted_dates = zip(*sorted_pairs)

        # Convert to lists (optional)
        sorted_costs = list(sorted_costs)
        sorted_dates = list(sorted_dates)

        cost = 0
        total_charge_mins = 0
        charge_slot_dict_list = []
        charge_mins_left = charge_mins
        for index in range(0, len(sorted_costs)):
            if index < len(sorted_dates):
                slot_start_t = sorted_dates[index]
                slot_end_t = slot_start_t+timedelta(minutes=slot_duration_mins)
                # If we need the entire charge slot
                if charge_mins_left >= slot_duration_mins:
                    charge_slot_dict = {}
                    charge_slot_dict[RegionalElectricity.SLOT_START_DATETIME] = slot_start_t
                    charge_slot_dict[RegionalElectricity.SLOT_STOP_DATETIME] = slot_end_t
                    charge_slot_dict[RegionalElectricity.SLOT_COST] = sorted_costs[index]
                    charge_slot_dict_list.append(charge_slot_dict)
                    charge_mins_left = charge_mins_left - slot_duration_mins
                    total_charge_mins = total_charge_mins + slot_duration_mins
                    cost = cost + (((slot_duration_mins/60.0)*charge_rate_kw)*charge_slot_dict[RegionalElectricity.SLOT_COST])

                else:
                    # If we need part of another slot to complete the charge.
                    # The minimum time we will turn the charger on is 15 mins.
                    # This governs the max charge error.
                    if charge_mins_left >= 15:
                        slot_end_t = slot_start_t+timedelta(minutes=charge_mins_left)
                        charge_slot_dict = {}
                        charge_slot_dict[RegionalElectricity.SLOT_START_DATETIME] = slot_start_t
                        charge_slot_dict[RegionalElectricity.SLOT_STOP_DATETIME] = slot_end_t
                        charge_slot_dict[RegionalElectricity.SLOT_COST] = sorted_costs[index]
                        charge_slot_dict_list.append(charge_slot_dict)
                        total_charge_mins = total_charge_mins + charge_mins_left
                        slot_cost = charge_slot_dict[RegionalElectricity.SLOT_COST]
                        cost = cost + (((charge_mins_left/60.0)*charge_rate_kw)*slot_cost)
                        charge_mins_left = 0

                    break

        return (charge_slot_dict_list,
                end_charge_datetime,
                plot_time_stamp_list,
                plot_cost_list,
                total_charge_mins,
                cost)

    def calc_optimal_charge_times_thread(self,
                                         region_code,
                                         plot_container,
                                         charge_mins,
                                         charge_rate_kw,
                                         end_charge_time):
        """@brief Calculate optimal charge times.
           @param region_code The regional electricity code.
           @param plot_container The container that will hold the plot.
           @param charge_mins The required charge time in mins.
           @param charge_rate_kw The EV charge rate in kW.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed.
           @return A dict containing the slots that the car should charge in."""
        try:
            charge_slot_dict_list, end_charge_datetime, plot_time_stamp_list, plot_cost_list, total_charge_mins, cost = self._get_charge_details(charge_mins,
                                                                                                                                                 end_charge_time,
                                                                                                                                                 charge_rate_kw,
                                                                                                                                                 region_code)

            # Clear the old plot
            plot_container.clear()

            fig = go.Figure()
            max_cost = max(plot_cost_list)
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0),
                              width=350,
                              height=250,
                              showlegend=False,
                              plot_bgcolor="black",       # Background for the plot area
                              paper_bgcolor="black",      # Background for the entire figure
                              font=dict(color="yellow"),   # Font color for labels and title
                              xaxis=dict(
                                  title="",
                                  color="yellow",          # Axis label color
                                  gridcolor="gray",       # Gridline color
                                  zerolinecolor="gray"    # Zero line color
                              ),
                              yaxis=dict(
                                  title="£ per kWh",
                                  color="yellow",         # Axis label color
                                  gridcolor="gray",       # Gridline color
                                  zerolinecolor="gray",   # Zero line color
                                  range=[0, max_cost*1.25]
                              ),)
            fig.add_trace(go.Bar(x=plot_time_stamp_list, y=plot_cost_list, opacity=0.5, marker=dict(color='green')))

            for charge_slot_dict in charge_slot_dict_list:
                startT = charge_slot_dict[RegionalElectricity.SLOT_START_DATETIME]
                stopT = charge_slot_dict[RegionalElectricity.SLOT_STOP_DATETIME]
                x = [startT, stopT]
                y = [charge_slot_dict[RegionalElectricity.SLOT_COST], charge_slot_dict[RegionalElectricity.SLOT_COST]]
                fig.add_trace(go.Scatter(x=x, y=y, line=dict(width=5), marker=dict(size=10, color='red')))

            # Add the new plot to the container
            with plot_container:
                ui.plotly(fig)

            with plot_container:
                hours_charge_factor = total_charge_mins/60.0
                kwh = hours_charge_factor*charge_rate_kw
                ui.label(f"{kwh:.1f} kWh over {total_charge_mins:.0f} mins (£{cost:.2f})")

            self._charge_slot_dict_list = charge_slot_dict_list

        except Exception as ex:
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _set_zappi_charge(self):
        """@brief """
        if self._charge_slot_dict_list is None:
            ui.notify("No charge schedule found.", type='negative')
        else:
            ui.notify("Setting zappi charge schedule", position='center')
            threading.Thread(target=self._set_zappi_charge_thread).start()

    def _set_zappi_charge_thread(self):
        # Sort the dicts in the list on the slot start time. The slot closest in time will be first in the list.
        sorted_charge_slot_dict_list = sorted(deepcopy(self._charge_slot_dict_list), key=lambda x: x[RegionalElectricity.SLOT_START_DATETIME])

        # merge any consecutive slots together to reduce the number of zappi charge schedules which is limited to 4 on the my energi system.
        index = 0
        merged_charge_slot_dict_list = []
        list_size = len(sorted_charge_slot_dict_list)
        current_slot_start_dict = current_slot_end_dict = None
        for index in range(0, list_size):
            current_slot_dict = sorted_charge_slot_dict_list[index]
            if current_slot_start_dict is None:
                current_slot_start_dict = current_slot_end_dict = current_slot_dict
            # If not on the last slot dict
            if index < list_size-1:
                next_slot_dict = sorted_charge_slot_dict_list[index+1]

                # If the next slot starts when this slot ends
                if current_slot_end_dict[RegionalElectricity.SLOT_STOP_DATETIME] == next_slot_dict[RegionalElectricity.SLOT_START_DATETIME]:
                    current_slot_end_dict = next_slot_dict

                else:
                    current_slot_start_dict[RegionalElectricity.SLOT_STOP_DATETIME] = current_slot_end_dict[RegionalElectricity.SLOT_STOP_DATETIME]
                    merged_charge_slot_dict_list.append(current_slot_start_dict)
                    current_slot_start_dict = current_slot_end_dict = None

            else:
                current_slot_start_dict[RegionalElectricity.SLOT_STOP_DATETIME] = current_slot_end_dict[RegionalElectricity.SLOT_STOP_DATETIME]
                merged_charge_slot_dict_list.append(current_slot_start_dict)

        try:
            self._my_energi.set_zappi_charge_schedule(merged_charge_slot_dict_list)
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = GUIServer.SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE
            self._update_gui(msg_dict)

        except Exception as ex:
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _reset_zappi_charge(self):
        """@brief Reset/disable all zappi charge schedules. Called from the GUI thread. This starts the thread that actually does the work."""
        ui.notify("Clearing all zappi charge schedules", position='center', type='ongoing', timeout=3000)
        self._plot_container.clear()
        self._charge_slot_dict_list = None
        threading.Thread(target=self._reset_zappi_charge_thread).start()

    def _reset_zappi_charge_thread(self):
        """@brief Reset/disable all zappi charge schedules. This must be called outside the GUI thread."""
        try:
            self._my_energi.set_all_zappi_schedules_off()
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = GUIServer.CLEARED_ALL_CHARGING_SCHEDULES
            self._update_gui(msg_dict)
        except Exception as ex:
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)


def main():
    """@brief Program entry point"""
    uio = UIO()
    options = None

    try:
        parser = argparse.ArgumentParser(description="ngt examples.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-d", "--debug",  action='store_true', help="Enable debugging.")
        parser.add_argument("-s", "--syslog", action='store_true', help="Enable syslog.")
        parser.add_argument("-p", "--port",   type=int, help=f"The TCP server port to which the GUI server is bound to (default={GUIServer.DEFAULT_SERVER_PORT}).", default=GUIServer.DEFAULT_SERVER_PORT)
        parser.add_argument("--reload",       action='store_true', help="Reload/Restart GUI when python file is updated. USeful for in dev env.")
        parser.add_argument("--show",         action='store_true', help="Show the GUI (open browser window) on startup.")
        BootManager.AddCmdArgs(parser)

        options = parser.parse_args()
        uio.enableDebug(options.debug)
        uio.logAll(True)
        uio.enableSyslog(options.syslog, programName="ngt")
        if options.syslog:
            uio.info("Syslog enabled")

        handled = BootManager.HandleOptions(uio, options, options.syslog)
        if not handled:
            gui = GUIServer(uio, options.port)
            gui.create_gui(options.debug,
                           reload=options.reload,
                           show=options.show)

    # If the program throws a system exit exception
    except SystemExit:
        pass
    # Don't print error information if CTRL C pressed
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        logTraceBack(uio)

        if not options or options.debug:
            raise
        else:
            uio.error(str(ex))


# Note __mp_main__ is used by the nicegui module
if __name__ in {"__main__", "__mp_main__"}:
    main()
