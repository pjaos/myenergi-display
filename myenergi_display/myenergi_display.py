#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Many thanks to Andy Twonk (https://github.com/twonk/MyEnergi-App-Api) for details the myenergi api
# used in this project.

import argparse
import threading
import requests
import traceback

from requests.auth import HTTPDigestAuth
from queue import Queue
from time import time, sleep

from datetime import timedelta, datetime, timezone
import urllib.request
import json
from copy import deepcopy

from p3lib.pconfig import ConfigManager, ConfigAttrDetails

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
    TOP_TANK_ID = 1
    BOTTOM_TANK_ID = 2
    TANK_1_BOOST_SCHEDULE_SLOT_ID = 14
    TANK_2_BOOST_SCHEDULE_SLOT_ID = 24
    VALID_EDDI_SLOT_ID_LIST = (11, 12, 13, TANK_1_BOOST_SCHEDULE_SLOT_ID, 21, 22, 23, TANK_2_BOOST_SCHEDULE_SLOT_ID)
    VALID_ZAPPI_SLOT_ID_LIST = (11, 12, 13, 14)
    ZAPPI_CHARG_MODE_FAST = 1
    ZAPPI_CHARGE_MODE_ECO = 2
    ZAPPI_CHARGE_MODE_ECO_PLUS = 3
    ZAPPI_CHARGE_MODE_STOPPED = 4

    def __init__(self, api_key, uio=None):
        """@brief Constuctor
           @param api_key Your myenergi API key.
                          You must create this on the myenergi web site.
                          See https://support.myenergi.com/hc/en-gb/articles/5069627351185-How-do-I-get-an-API-key for more information.
           @param uio An UIO instance."""
        self._api_key = api_key
        self._eddi_serial_number = None
        self._zappi_serial_number = None
        self._eddi_stats_dict = None
        self._zappi_stats_dict = None
        self._uio = uio
        self._lock = threading.Lock()

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

    def get_stats(self):
        """@brief Get the stats of the eddi unit."""
        self._check_eddi_serial_number()
        url = MyEnergi.BASE_URL + "cgi-jstatus-*"
        return self._exec_api_cmd(url)

    def update_stats(self):
        """@brief update all the stats."""
        stats_list = self.get_stats()
        for stats_dict in stats_list:
            if 'eddi' in stats_dict:
                eddi_dict_list = stats_dict['eddi']
                for eddi_dict in eddi_dict_list:
                    if 'sno' in eddi_dict:
                        serial_number = eddi_dict['sno']
                        # Check the eddi serial number matches
                        if str(serial_number) == str(self._eddi_serial_number):
                            # Assign the eddi dict
                            self._eddi_stats_dict = eddi_dict

            elif 'zappi' in stats_dict:
                zappi_dict_list = stats_dict['zappi']
                for zappi_dict in zappi_dict_list:
                    if 'sno' in zappi_dict:
                        serial_number = zappi_dict['sno']
                        # Check the zappi serial number matches
                        if str(serial_number) == str(self._zappi_serial_number):
                            # Assign the zappi dict
                            self._zappi_stats_dict = zappi_dict

    def _get_eddi_stat(self, name, throw_error=True):
        """@brief Get a eddi stat after update_stats() has been called.
           @param name The name of the stat of interest.
           @param throw_error True if this method should throw an error if the stats is not found.
           @return The stat or None if not found."""
        stat = None
        # If the stats have not been read yet, read them
        if not self._eddi_stats_dict or name not in self._eddi_stats_dict:
            self.update_stats()

        if self._eddi_stats_dict:
            if name in self._eddi_stats_dict:
                stat = self._eddi_stats_dict[name]

        if throw_error and stat is None:
            raise Exception(f"Failed to read myenergi eddi '{name}={stat}'.")

        return stat

    def _get_zappi_stat(self, name, throw_error=True):
        """@brief Get a zappi stat after update_stats() has been called.
           @param name The name of the stat of interest.
           @param throw_error True if this method should throw an error if the stats is not found.
           @return The stat or None if not found."""
        stat = None
        # If the stats have not been read yet, read them
        if not self._zappi_stats_dict or name not in self._zappi_stats_dict:
            self.update_stats()

        if self._zappi_stats_dict:
            if name in self._zappi_stats_dict:
                stat = self._zappi_stats_dict[name]

        if throw_error and stat is None:
            raise Exception(f"Failed to read myenergi zappi '{name}={stat}'.")

        return stat

    def get_eddi_top_tank_temp(self):
        """@return The eddi top tank temperature or None if not known."""
        return self._get_eddi_stat('tp1')

    def get_eddi_bottom_tank_temp(self):
        """@return The eddi bottom tank temperature or None if not known."""
        return self._get_eddi_stat('tp2')

    def get_eddi_heater_watts(self):
        """@return The eddi heater power in kw or None if not known."""
        return self._get_eddi_stat('ectp1')

    def get_eddi_heater_number(self):
        """@return The eddi heater number that is on.
                   If no heater is on then this stays at the last value.
                   1 = top tank, 2 = bottom tank"""
        return self._get_eddi_stat('hno')

    def get_zappi_charge_mode(self):
        """@return The zappi charge mode or None if not known."""
        return self._get_zappi_stat('zmo')

    def get_zappi_charge_watts(self):
        """@return Get the current charge rate of the zappi in watts."""
        return self._get_zappi_stat('ectp1')

    def get_eddi_stats(self):
        """@brief Get the stats of the eddi unit."""
        self._check_eddi_serial_number()
        url = MyEnergi.BASE_URL + "cgi-jstatus-E"
        return self._exec_api_cmd(url)

    def get_zappi_schedule_list(self):
        """@brief Get the zappi charge schedule list.
           @return A list with four elements. Each element is a list
                   that contains the following three elements
                   0 = The time as HH:MM
                   1 = The duration as HH:MM
                   2 = A comma separated list of days of the week. Each day as three letters."""
        table_row_list = []
        zappi_stats_dict = self.get_zappi_stats()
        if GUIServer.BOOST_TIMES_KEY in zappi_stats_dict:
            for boost_dict in zappi_stats_dict[GUIServer.BOOST_TIMES_KEY]:
                if self._is_valid_boost_dict(boost_dict):
                    """A boost dict contains the following
                        0: bdd The days of the week in the form 01111111.
                            The first 1 indicates that the schedule applies to Mon
                            The next is Tue and so on until Sun.
                            Therefore 01111111 indicate the schedule applies to
                            every day of the week.
                        1: bdh Duration in hours.
                        2: bdm Duration in minutes.
                        3: bsh Time in hours.
                        4: bsm Time in minutes.
                        5: slt The slot. An integer to indicate the schedule slot (11,12,13 or 14)."""
                    bdd = boost_dict[GUIServer.BDD_BOOST_DICT_KEY]
                    bdh = boost_dict[GUIServer.BDH_BOOST_DICT_KEY]
                    bdm = boost_dict[GUIServer.BDM_BOOST_DICT_KEY]
                    bsh = boost_dict[GUIServer.BSH_BOOST_DICT_KEY]
                    bsm = boost_dict[GUIServer.BSM_BOOST_DICT_KEY]
                    table_row = self._get_sched_table_row(bdd,
                                                          bdh,
                                                          bdm,
                                                          bsh,
                                                          bsm)
                    table_row_list.append(table_row)
        return table_row_list

    def _is_valid_boost_dict(self, boost_dict):
        """@brief Determine if the boost dict is valid.
           @return True if all the required keys are present in the boost dict."""
        key_count = 0
        for key in GUIServer.BOOST_DICT_KEYS:
            if key in boost_dict:
                key_count = key_count + 1
        valid = False
        if key_count == 6:
            valid = True
        return valid

    def _get_sched_table_row(self,
                             bdd,
                             bdh,
                             bdm,
                             bsh,
                             bsm):
        """@return A list/row of values from the myenergi zappi charge schedules.
                   0 = start time (HH:MM)
                   1 = duration (HH:MM)
                   2 = Comma separated list of days of the week. Each day in three letter format."""
        day_list = self._get_sched_day_list(bdd)
        duration = f"{bdh:02d}:{bdm:02d}"
        start_time = f"{bsh:02d}:{bsm:02d}"
        table_row = None
        table_row = (start_time, duration, day_list)
        return table_row

    def _get_sched_day_list(self, bdd):
        """@brief Get a list of days that a schedule applies to.
           @param bdd The bdd field from the zappi schedule.
           @return A comma separated list of three letter day names."""
        day_list = []
        if len(bdd) == 8:
            if bdd[1] == '1':
                day_list.append('Mon')
            elif bdd[2] == '1':
                day_list.append('Tue')
            elif bdd[3] == '1':
                day_list.append('Wed')
            elif bdd[4] == '1':
                day_list.append('Thu')
            elif bdd[5] == '1':
                day_list.append('Fri')
            elif bdd[6] == '1':
                day_list.append('Sat')
            elif bdd[7] == '1':
                day_list.append('Sun')
        return ",".join(day_list)

    def get_zappi_stats(self):
        """@brief Get the stats of the eddi unit."""
        self._check_eddi_serial_number()
        self._check_zappi_serial_number()
        url = MyEnergi.BASE_URL + "cgi-boost-time-Z"+self._zappi_serial_number
        return self._exec_api_cmd(url)

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

    def set_tank_schedule(self, on, on_datetime, duration_timedelta, tank):
        """@brief Set a schedule on the hot water tank.
           @param on If True add a schedule. If False delete a schedule.
           @param on_datetime A datetime instance that defines the on time for the tank heater.
           @param duration_timedelta A timedelta instance that defines ho long the tank heater should stay on.
           @param tank The hot water tank (1=top, 2 = bottom)."""
        sched_sub_str = self._get_eddi_schedule_string(on, on_datetime, duration_timedelta, tank)
        url = MyEnergi.BASE_URL + f"cgi-boost-time-E{self._eddi_serial_number}-{sched_sub_str}"
        self._exec_api_cmd(url)

    def set_water_tank_boost_schedules_off(self):
        """@brief Set the boost tank water schedule off. We reserve the fourth schedule timer for this boost setting, leaving the other timers untouched.
                  Note, we use MyEnergi.TANK_1_BOOST_SCHEDULE_SLOT_ID and MyEnergi.TANK_2_BOOST_SCHEDULE_SLOT_ID schedules for boost purposes
                  rather than using the boost interface commands for the reason details in the _set_boost() method."""
        self.set_tank_schedule(False, None, None, MyEnergi.TOP_TANK_ID)
        self.set_tank_schedule(False, None, None, MyEnergi.BOTTOM_TANK_ID)

    def _get_eddi_schedule_string(self, on, on_datetime, duration_timedelta, tank):
        """@brief Get a timed schedule for a hot water tank.

            cgi-boost-time-E<eddi serial number>-<slot id>-<start time>-<duration>-<day spec>

                start time and duration are both numbers like 60*hours+minutes
                day spec is as bdd above'

            This method returns part of the above string as detailed below.

            '<slot id>-<start time>-<duration>-<day spec>'

           @param on_datetime A datetime instance that defines the on time for the tank heater.
           @param duration_timedelta A timedelta instance that defines ho long the tank heater should stay on.
           @param tank The hot water tank (1=top, 2 = bottom)."""

        self._check_eddi_serial_number()
        if tank not in [MyEnergi.TOP_TANK_ID, MyEnergi.BOTTOM_TANK_ID]:
            raise Exception(f"{tank} is an invalid water tank. Must be {MyEnergi.TOP_TANK_ID} (top) or {MyEnergi.BOTTOM_TANK_ID} (bottom).")

        if tank == 1:
            slot_id = MyEnergi.TANK_1_BOOST_SCHEDULE_SLOT_ID
        else:
            slot_id = MyEnergi.TANK_2_BOOST_SCHEDULE_SLOT_ID

        if on:
            on_time_string = f"{on_datetime.hour:02d}{on_datetime.minute:02d}"
            duration_hours, remainder = divmod(duration_timedelta.seconds, 3600)
            duration_minutes, _ = divmod(remainder, 60)
            duration_string = f"{duration_hours:01d}{duration_minutes:02d}"

            day_of_week = on_datetime.weekday()
            day_of_week_string = self._get_day_of_week_string(day_of_week)

            schedule_string = f"{slot_id:02d}-{on_time_string}-{duration_string}-{day_of_week_string}"

        else:
            schedule_string = f"{slot_id:02d}-0000-000-00000000"

        return schedule_string

    def set_all_zappi_schedules_off(self):
        """@brief Set all zappi charge schedules off.
                  We set charge schedules that have no on time and are not enabled for any days of the week.
                  This causes the 4 possible schedules on the zappi to be removed."""
        self._check_eddi_serial_number()
        self._check_zappi_serial_number()

        for slot_id in MyEnergi.VALID_ZAPPI_SLOT_ID_LIST:
            url = MyEnergi.BASE_URL + f"cgi-boost-time-Z{self._zappi_serial_number}-{slot_id}-0000-000-00000000"
            self._exec_api_cmd(url)
            # The myenergi system does not always delete the schedule unless a delay occurs between each command
            sleep(1)

    def _get_zappi_charge_string(self, charge_slot_dict, slot_id):
        """@detail Get a string that is formated as required by the myenergi zappi api.

            cgi-boost-time-Z<zappi serial number>-<slot id>-<start time>-<duration>-<day spec>

                start time and duration are both numbers like 60*hours+minutes
                day spec is as bdd above'

            This method returns part of the above string as detailed below.

            '<slot id>-<start time>-<duration>-<day spec>'

           @param charge_slot_dict The dict holding the start stop details of the charge as generated by
                                   GUIServer._set_zappi_charge_thread()
           @param slot_id The slot ID (one of MyEnergi.VALID_ZAPPI_SLOT_ID_LIST).
        """
        if slot_id not in MyEnergi.VALID_ZAPPI_SLOT_ID_LIST:
            valid_list = ",".join(MyEnergi.VALID_ZAPPI_SLOT_ID_LIST)
            raise Exception(f"{slot_id} is an invalid slot id (value = {valid_list})")

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
        day_of_week_string = self._get_day_of_week_string(day_of_week)

        charge_string = f"{slot_id:02d}-{on_time_string}-{duration_string}-{day_of_week_string}"
        return charge_string

    def _get_day_of_week_string(self, day_of_week):
        """@brief Get the day of the week string used in the command sent to the myenergi server.
           @param day_of_week A single day of the week as an integer 0 - 6.
           @return The day of the week string in the format accepted by the myenergi server."""
        day_of_week_string = None
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

        if day_of_week_string is None:
            raise Exception("{day_of_week} is an invalid day of the week. Must be 0-6")

        return day_of_week_string

    def _debug(self, msg):
        if self._uio:
            self._uio.debug(f"myenergi API DEBUG: {msg}")

    def _exec_api_cmd(self, url):
        """@brief Run a command using the myenergi api and check for errors.
           @return The json response message."""
        # As this maybe called from multiple threads ensure we use acquire a thread lock each time
        # we communicate with the myenergi server.
        with self._lock:
            self._debug(f"_exec_api_cmd: url={url}")
            response = requests.get(url, auth=HTTPDigestAuth(self._eddi_serial_number, self._api_key))
            if response.status_code != 200:
                raise Exception(f"{response.status_code} error code returned from myenergi server.")
            self._debug(f"_exec_api_cmd: response.status_code={response.status_code}")
            response_dict = response.json()

            if response_dict:
                index = 0
                for elem in response_dict:
                    pstr = json.dumps(elem, sort_keys=True, indent=4)
                    self._debug(f"_exec_api_cmd: index={index}, elem={pstr}")
                    index = index+1

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

        # I tried removing any existing charge schedules.
        # However if this is executed then the charge schedule fails to get set.
        # Not sure why this occurs.
#        self.set_all_zappi_schedules_off()

        # The zappi charger must be in eco+ mode.
        # We don't need to set eco+ mode as this is checked at a higher level

        # Set each schedule.
        for charge_str in charge_str_list:
            url = MyEnergi.BASE_URL + f"cgi-boost-time-Z{self._zappi_serial_number}-"+charge_str
            self._exec_api_cmd(url)


class ColorButton(ui.button):
    """@brief A button that can change it's background color to one of a number of states."""
    DEFAULT_COLORS = ["blue", 'purple', 'green']

    def __init__(self, callBack=None, *args, **kwargs) -> None:
        """@brief Constructor.
                  This sets 3 default colors that the button can be in."""
        super().__init__(*args, **kwargs)
        self._color_index = 0
        self.set_button_colors(ColorButton.DEFAULT_COLORS)
        self.on('click', callBack)

    def set_button_colors(self, color_list):
        """@brief Set a list of background colors for the button.
           @param color_list A list of colors (strings) for each state the button can be in."""
        if len(color_list) < 1:
            raise Exception("The list of button colors must include at least one color.")
        self._color_list = color_list

    def set_color_index(self, color_index):
        """@brief Set the first of the three button states (low).
           @param color_index The index of the current color"""
        max_index = len(self._color_list)-1
        if self._color_index > max_index:
            raise Exception(f"{color_index} is an invalid button color index. The maximum color index is {max_index}.")
        self._color_index = color_index
        self.update()

    def update(self) -> None:
        """@brief Update the button state."""
        button_color = self._color_list[self._color_index]
        self.props(f'color={button_color}')
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

    @staticmethod
    def GET_NEXT_30_MIN_TIME():
        """@brief Get the next time on a 30 minute boundary. On the hour or half hour.
           @return A datetime instance on the next hour or half hour boundary."""
        now = datetime.now().astimezone()
        # Add 30 mins in the future
        next_dt = now + timedelta(minutes=30)
        if next_dt.minute > 30:
            next_dt = next_dt.replace(minute=30, second=0, microsecond=0)
        else:
            next_dt = next_dt.replace(minute=00, second=0, microsecond=0)

        return next_dt

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
        next_30_min_datetime = RegionalElectricity.GET_NEXT_30_MIN_TIME()
        _timeStampList = list(costDict.keys())
        _timeStampList.sort()
        # If the user requires the charge to be complete by a certain time
        end_charge_datetime = None
        if end_charge_time:
            end_charge_datetime = GUIServer.GET_END_CHARGE_DATETIME(end_charge_time)

        timeStampList = []
        costList = []
        for ts in _timeStampList:
            # Ignore all times that are in the past
            if ts < next_30_min_datetime:
                continue
            # Ignore times after the end charge time
            if end_charge_datetime and ts > end_charge_datetime:
                continue
            timeStampList.append(ts)
            cost = costDict[ts]/100.0
            # Add the end of this 1/2 hour slot
            costList.append(cost)

        # If we don't have an end of charge time defined
        if not end_charge_datetime:
            # Ensure we have a defined end time (2 days in the future on an hour boundary)
            # This should not interfere with the charge calculation if the octopus agile tariff is selected.
            now = datetime.now().astimezone()
            end_charge_datetime = now + timedelta(hours=48)
            end_charge_datetime = end_charge_datetime.replace(minute=0, second=0, microsecond=0)

        return (timeStampList, costList, end_charge_datetime)


class GUIServer(object):

    MYENERGI_API_KEY = 'MYENERGI_API_KEY'
    EDDI_SERIAL_NUMBER = 'EDDI_SERIAL_NUMBER'
    ZAPPI_SERIAL_NUMBER = 'ZAPPI_SERIAL_NUMBER'
    ZAPPI_MAX_CHARGE_RATE = 'ZAPPI_MAX_CHARGE_RATE'
    ELECTRICITY_REGION_CODE = 'ELECTRICITY_REGION_CODE'
    OCTOPUS_AGILE_TARIFF = 'OCTOPUS_AGILE_TARIFF'
    TARIFF_POINT_LIST = "TARIFF_POINT_LIST"
    EV_BATTERY_KWH = "EV_BATTERY_KWH"
    CURRENT_EV_CHARGE_PERCENTAGE = "CURRENT_EV_CHARGE_PERCENTAGE"
    TARGET_EV_CHARGE_PERCENTAGE = "TARGET_EV_CHARGE_PERCENTAGE"
    READY_BY = "READY_BY"
    CLEAR_ZAPPI_SCHEDULE_TIME = "CLEAR_ZAPPI_SCHEDULE_TIME"
    CLEAR_EDDI_SCHEDULE_TIME = "CLEAR_EDDI_SCHEDULE_TIME"

    DEFAULT_CONFIG = {MYENERGI_API_KEY: "",
                      EDDI_SERIAL_NUMBER: "",
                      ZAPPI_SERIAL_NUMBER: "",
                      ZAPPI_MAX_CHARGE_RATE: "7.4",
                      ELECTRICITY_REGION_CODE: "",
                      OCTOPUS_AGILE_TARIFF: True,
                      TARIFF_POINT_LIST: [],
                      EV_BATTERY_KWH: "0",
                      CURRENT_EV_CHARGE_PERCENTAGE: 20,
                      TARGET_EV_CHARGE_PERCENTAGE: 80,
                      READY_BY: "",
                      CLEAR_ZAPPI_SCHEDULE_TIME: "",
                      CLEAR_EDDI_SCHEDULE_TIME: ""}

    TAB_BAR_STYLE = 'font-size: 20px; color: lightgreen;'
    TEXT_STYLE_A = 'font-size: 40px; color: white;'
    TEXT_STYLE_A_SIZE = 'font-size: 20px;'
    TEXT_STYLE_B = 'font-size: 40px; color: lightgreen;'
    TEXT_STYLE_C = 'font-size: 15px; color: lightgreen;'
    TEXT_STYLE_D_SIZE = 'font-size: 40px;'
    TEXT_STYLE_E_SIZE = 'font-size: 30px;'

    BOOST_1_ON = "BOOST_1_SET_ON"
    BOOST_2_ON = "BOOST_2_SET_ON"
    BOOST_OFF = "BOOST_OFF"
    TANK_TEMPERATURES = "TANK_TEMPERATURES"
    INFO_MESSAGE = "INFO_MESSAGE"
    ERROR_MESSAGE = "ERROR_MESSAGE"
    CLEAR_PLOT = "CLEAR_PLOT"
    MIN_STATS_UPDATE_SECONDS = 10.0                 # The minimum time between myenergi server stats reads.
    MAX_STATS_UPDATE_SECONDS = 60.0                 # The maximum time between myenergi server stats reads.
    STATS_READ_INC_FACTOR = 1.2                     # Choose a factor that will cause the stats read delay to reach maximum in about 6 minutes.
    DEFAULT_SERVER_PORT = 8080
    GUI_POLL_SECONDS = 0.1
    TARIFF_LIST = ["Octopus Agile Tariff", 'Other Tariff']
    SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE = "Set zappi charge schedule"
    DEFAULT_BUTTON_COLOR = "blue"
    CLEARED_ALL_CHARGING_SCHEDULES = "Cleared all zappi charging schedules."
    ZAPPI_CHARGE_SCHEDULE = "ZAPPI_CHARGE_SCHEDULE"

    BOOST_TIMES_KEY = "boost_times"
    BDD_BOOST_DICT_KEY = 'bdd'
    BDH_BOOST_DICT_KEY = 'bdh'
    BDM_BOOST_DICT_KEY = 'bdm'
    BSH_BOOST_DICT_KEY = 'bsh'
    BSM_BOOST_DICT_KEY = 'bsm'
    SLT_BOOST_DICT_KEY = 'slt'

    BOOST_DICT_KEYS = [BDD_BOOST_DICT_KEY,
                       BDH_BOOST_DICT_KEY,
                       BDM_BOOST_DICT_KEY,
                       BSH_BOOST_DICT_KEY,
                       BSM_BOOST_DICT_KEY,
                       SLT_BOOST_DICT_KEY
                       ]
    PLOT_OPTIMAL_CHARGE_TIMES = "PLOT_OPTIMAL_CHARGE_TIMES"

    BUTTON_LOW_INDEX = 0
    BUTTON_MID_INDEX = 1
    BUTTON_HIGH_INDEX = 2

    ADD_TARIFF_START_TIME = "Start time"
    ADD_TARIFF_PRICE = "Price (£)"

    ZERO_COST_ELEC_START_TIME = "Start time"
    ZERO_COST_ELEC_DURATION = "Duration"

    MAX_HEATER_WATTS = 2500
    MIN_HEATER_WATTS = 100

    ZAPPI_CHARGE_ADJUSTMENT_FACTOR_FLOAT = "ZAPPI_CHARGE_ADJUSTMENT_FACTOR_FLOAT"
    CMD_LINE_CONFIG_FILENAME = "myenergi_display_command_line.cfg"
    DEFAULT_CMD_LINE_CONFIG = {
        ZAPPI_CHARGE_ADJUSTMENT_FACTOR_FLOAT: "1.0",
    }
    CMD_LINE_CONFIG_ATTR_DICT = {
        ZAPPI_CHARGE_ADJUSTMENT_FACTOR_FLOAT: ConfigAttrDetails("Enter the ZAPPI charge adjustment factor (default = 1.0)", 0.0, 3.0),
    }

    @staticmethod
    def Print_Exception():
        """@brief Print an exception traceback."""
        lines = traceback.format_exc().split("\n")
        for line in lines:
            print(line)

    def __init__(self, uio, port):
        """@brief Constructor
           @param uio A UIO instance.
           @param port The TCP port to bind the nicegui server."""
        self._uio = uio
        self._port = port
        self._init_stats_read_delay = True            # A flag to initialize the stats read time
        self._to_gui_queue = Queue()    # This queue is used to send commands from any thread to the GUI thread.
        self._my_energi = MyEnergi('')
        self._heater_load_watts = 0
        self._zappi_charge_watts = 0
        self._relay_on = 0
        self._eddi_heater_button_selected = 0
        self._electricity_region_code = ''
        self._charge_slot_dict_list = None
        self._octopus_agile_tariff = True
        self._other_tariff_values = []
        self._read_temp_thread = None
        self._zappi_charge_schedule_active = False
        self._clear_zappi_button = None
        self._cfg_mgr = DotConfigManager(GUIServer.DEFAULT_CONFIG, uio=self._uio)
        self._load_config()
        # Attr used to convert boost time slider seconds into HH:MM
        self._boost_time_value = None
        self._cmd_line_config_manager = ConfigManager(self._uio, GUIServer.CMD_LINE_CONFIG_FILENAME, GUIServer.DEFAULT_CMD_LINE_CONFIG)
        self._cmd_line_config_manager.load(self)

    def _reset_polling_rate(self):
        """@brief This is called to reset the polling rate (set to min delay between reads)."""
        self._init_stats_read_delay = True

    def _read_stats_now(self):
        """@brief Determine if it's time to read the stats from the myenergi server.
           @return True if it's time, False if not."""
        read_stats_now = False
        if self._init_stats_read_delay:
            self._init_stats_read_delay = False
            self._next_stats_read_time = time() + GUIServer.MIN_STATS_UPDATE_SECONDS
            self._current_stats_read_delay = GUIServer.MIN_STATS_UPDATE_SECONDS
            read_stats_now = True
            self._debug(f"self._read_stats_now(): Read stats {GUIServer.MIN_STATS_UPDATE_SECONDS} seconds from now.")

        else:
            # When running the stats are read from the myenergi server. The delay between
            # each read starts at GUIServer.MIN_STATS_UPDATE_SECONDS and moves to
            # GUIServer.MAX_STATS_UPDATE_SECONDS as time passes.

            # If we are in a state where the read delay has reached the max, calc the next read time.
            if self._current_stats_read_delay >= GUIServer.MAX_STATS_UPDATE_SECONDS:
                self._current_stats_read_delay = GUIServer.MAX_STATS_UPDATE_SECONDS
                # If its time to read stats
                if time() >= self._next_stats_read_time:
                    read_stats_now = True
                    # Calc the next read time.
                    self._next_stats_read_time = time() + self._current_stats_read_delay
                    self._debug(f"self._read_stats_now(): Max stats read delay of {self._current_stats_read_delay} seconds reached.")

            else:
                # If its time to read stats
                if time() >= self._next_stats_read_time:
                    # Inc the delay between reads and calc the next read time.
                    new_stats_read_delay = self._current_stats_read_delay * GUIServer.STATS_READ_INC_FACTOR
                    self._next_stats_read_time = time() + new_stats_read_delay
                    read_stats_now = True
                    self._current_stats_read_delay = new_stats_read_delay
                    if self._current_stats_read_delay > GUIServer.MAX_STATS_UPDATE_SECONDS:
                        self._current_stats_read_delay = GUIServer.MAX_STATS_UPDATE_SECONDS
                    self._debug(f"self._read_stats_now(): Read stats in {self._current_stats_read_delay} seconds time.")

        return read_stats_now

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
        self._my_energi = MyEnergi(self._cfg_mgr.getAttr(GUIServer.MYENERGI_API_KEY), uio=self._uio)
        self._my_energi.set_eddi_serial_number(self._cfg_mgr.getAttr(GUIServer.EDDI_SERIAL_NUMBER))
        self._my_energi.set_zappi_serial_number(self._cfg_mgr.getAttr(GUIServer.ZAPPI_SERIAL_NUMBER))

    def _save_config(self, show_info=True):
        """@brief Save some parameters to a local config file.
           @param show_info If True then show info messages."""

        # If the API key and eddi serial number have been entered
        if len(self._api_key.value) > 0 and len(self._eddi_serial_number.value) > 0:
            self._cfg_mgr.addAttr(GUIServer.MYENERGI_API_KEY,    self._api_key.value)
            self._cfg_mgr.addAttr(GUIServer.EDDI_SERIAL_NUMBER,  self._eddi_serial_number.value)
            if not self._check_eddi_access_ok(show_info=show_info):
                return

        # If the API key and zappi serial number have been entered
        if len(self._api_key.value) > 0 and len(self._zappi_serial_number.value) > 0:
            self._cfg_mgr.addAttr(GUIServer.MYENERGI_API_KEY,    self._api_key.value)
            self._cfg_mgr.addAttr(GUIServer.ZAPPI_SERIAL_NUMBER, self._zappi_serial_number.value)
            if not self._check_zappi_access_ok(show_info=show_info):
                ui.notify("zappi access failed. Check API Key and zappi serial number.", type='negative')
                return

            if float(self._ev_kwh.value) <= 0:
                ui.notify("EV battery capacity must be greater than 0 kWh.", type='negative')
                return
            self._cfg_mgr.addAttr(GUIServer.EV_BATTERY_KWH, float(self._ev_kwh.value))

            region_code = self._electricity_region_code.value
            if region_code is None or region_code not in RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS:
                ui.notify("Electricity region code must be set.", type='negative')
                return
            self._cfg_mgr.addAttr(GUIServer.ELECTRICITY_REGION_CODE, region_code)

            # The user may leave the zappi charge rate field empty
            if len(self._zappi_max_charge_rate.value) > 0:
                try:
                    float(self._zappi_max_charge_rate.value)
                except ValueError:
                    ui.notify(f"{self._zappi_max_charge_rate.value} is an invalid zappi charge rate (kW).", type='negative')
                    # Don't proceed with saving
                    return
            self._cfg_mgr.addAttr(GUIServer.ZAPPI_MAX_CHARGE_RATE, self._zappi_max_charge_rate.value)

            octopus_agile_tariff = self._is_octopus_agile_tariff_enabled()
            self._cfg_mgr.addAttr(GUIServer.OCTOPUS_AGILE_TARIFF, octopus_agile_tariff)
            self._cfg_mgr.addAttr(GUIServer.TARIFF_POINT_LIST, self._other_tariff_values)

        # These are GUI fields that are saved persistently.
        self._cfg_mgr.addAttr(GUIServer.CURRENT_EV_CHARGE_PERCENTAGE, self._current_ev_charge_input.value)
        self._cfg_mgr.addAttr(GUIServer.TARGET_EV_CHARGE_PERCENTAGE, self._target_ev_charge_input.value)
        self._cfg_mgr.addAttr(GUIServer.READY_BY, self._end_charge_time_input.value)

        self._cfg_mgr.store()

        if show_info:
            ui.notify(f"Saved to {self._cfg_mgr._getConfigFile()}")

    def _is_octopus_agile_tariff_enabled(self):
        """@brief Determine if the user has selectedt the Octopus agile tariff.
           @return True if enabled false if not."""
        octopus_agile_tariff = False
        if self._tariff_radio.value == GUIServer.TARIFF_LIST[0]:
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

    def create_gui(self, nicegui_debug_enabled, reload=False, show=False):
        """@brief Create the GUI elements
           @param nicegui_debug_enabled True enables debug of the nicegui server.
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
        if nicegui_debug_enabled:
            guiLogLevel = "debug"

        ui.timer(interval=0.1, callback=self._gui_timer_callback)
        ui.run(host=address,
               port=self._port,
               title=pageTitle,
               dark=True,
               uvicorn_logging_level=guiLogLevel,
               reload=reload,
               show=show)

    def _get_heater_power(self, relay):
        """@brief Determine how much power the heater is taking and from this infer the
                  source of the power.
           @param relay 1 == top tank heater. 2 == Bottom tank heater.
           @return 2 >= AC Mains
                   1 >= Solar Power
                   0 = No detected power."""
        detected_power = 0
        # If the relay of interest is on
        if self._relay_on == relay:
            if self._heater_load_watts > GUIServer.MAX_HEATER_WATTS:
                detected_power = 2

            elif self._heater_load_watts > GUIServer.MIN_HEATER_WATTS:
                detected_power = 1
        return detected_power

    def _get_zappi_charging(self):
        """@brief Determine if the zappi is charging an EV.
           @return True if the EV is charging."""
        ev_charging = False
        # We use a threshold of 1400 watts as 1500 watts appears to be the min ev charge rate.
        if self._zappi_charge_watts > 1400:
            ev_charging = True
        return ev_charging

    def _gui_timer_callback(self):
        """@called periodically (quickly) to allow updates of the GUI."""

        while not self._to_gui_queue.empty():
            rxMessage = self._to_gui_queue.get()
            if isinstance(rxMessage, dict):
                self._process_rx_dict(rxMessage)

        # If it's time toe read the stats
        if self._read_stats_now():
            # Don't update the tank temperatures in the gui thread or the gui thread will block
            # if there are issues getting data over the internet.
            # Only start a new thread if we haven't started one yet or the old one has completed.
            # This stops many threads backing up if there are internet connectivity issues.
            self._read_temp_thread = threading.Thread(target=self._update_stats).start()

        relay_1_color_index = self._get_heater_power(1)
        self._boost_top_button.set_color_index(relay_1_color_index)

        relay_2_color_index = self._get_heater_power(2)
        # Ensure both heaters cannot be on at the same time
        # This should never happen.
        if relay_1_color_index != 0:
            relay_2_color_index = 0
        self._boost_bottom_button.set_color_index(relay_2_color_index)

        ev_charging = self._get_zappi_charging()
        if ev_charging:
            self._set_button.set_color_index(GUIServer.BUTTON_HIGH_INDEX)
        else:
            if self._zappi_charge_schedule_active:
                self._set_button.set_color_index(GUIServer.BUTTON_MID_INDEX)
            else:
                self._set_button.set_color_index(GUIServer.BUTTON_LOW_INDEX)

        now = datetime.now()
        clear_eddi_boost_schedule_time = self._get_clear_eddi_boost_schedule_time()
        if clear_eddi_boost_schedule_time and clear_eddi_boost_schedule_time <= now:
            self.clear_eddi_boost_schedule_time()

        clear_zappi_schedule_time = self._get_clear_zappi_schedule_time()
        if clear_zappi_schedule_time and clear_zappi_schedule_time <= now:
            self.clear_zappi_schedule_time()

    def _get_clear_eddi_boost_schedule_time(self):
        """@brief Get the time to clear the eddi boost schedule. If a schedule has been set
                  then it is cleared when the tank heating has completed.
           @return A datetime instance or None if not defined."""

        clear_datetime = None
        try:
            datetime_str = self._cfg_mgr.getAttr(GUIServer.CLEAR_EDDI_SCHEDULE_TIME)
            clear_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")
            self._debug("_get_clear_eddi_boost_schedule_time()")
        except ValueError:
            pass
        return clear_datetime

    def _get_clear_zappi_schedule_time(self):
        """@brief Get the time to clear the zappi schedule. If a schedule has been set
                  then it is cleared when the charge has been completed or when the
                  clear schedule button is selected.
           @return A datetime instance or None if not defined."""
        clear_datetime = None
        try:
            datetime_str = self._cfg_mgr.getAttr(GUIServer.CLEAR_ZAPPI_SCHEDULE_TIME)
            clear_datetime = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
        return clear_datetime

    def clear_eddi_boost_schedule_time(self):
        """@brief Set the clear eddi boost schedule time."""
        threading.Thread(target=self._clear_eddi_boost_schedule_time_thread).start()

    def _clear_eddi_boost_schedule_time_thread(self):
        """@brief Set the clear zappi charge schedule time."""
        self._cfg_mgr.addAttr(GUIServer.CLEAR_EDDI_SCHEDULE_TIME, "")
        # Save the time that the zappi schedule should be deleted
        self._save_config(show_info=False)
        # Call the method invoked when the user selects the eddi off button
        threading.Thread(target=self._set_boost, args=(False, None, None)).start()

    def clear_zappi_schedule_time(self):
        """@brief Set the clear zappi charge schedule time."""
        threading.Thread(target=self._clear_zappi_schedule_time_thread).start()

    def _clear_zappi_schedule_time_thread(self):
        """@brief Set the clear zappi charge schedule time."""
        self._cfg_mgr.addAttr(GUIServer.CLEAR_ZAPPI_SCHEDULE_TIME, "")
        # Save the time that the zappi schedule should be deleted
        self._save_config(show_info=False)
        # Reset this so that the Set button returns to it's original color.
        self._zappi_charge_schedule_active = False
        # Call the method invoked when the user selects the Clear zappi schedules button
        # to remove the schedules from the zappi.
        threading.Thread(target=self._clear_zappi_charge_schedules_thread).start()

    def _process_rx_dict(self, rxDict):
        """@brief Process the dicts received from the GUI message queue.
           @param rxDict The dict received from the GUI message queue."""

        if GUIServer.BOOST_1_ON in rxDict:
            ui.notify(f'Set top tank heater boost on for {self._bootMinsSlider.value} mins.')

        elif GUIServer.BOOST_2_ON in rxDict:
            ui.notify(f'Set bottom tank heater boost on for {self._bootMinsSlider.value} mins.')

        elif GUIServer.BOOST_OFF in rxDict:
            ui.notify('Set top and bottom tank heaters off.')

        elif GUIServer.ERROR_MESSAGE in rxDict:
            error_message = rxDict[GUIServer.ERROR_MESSAGE]
            self._clear_zappi_button.enable()
            ui.notify(f"{error_message}", type='negative')
            if error_message.startswith("-5 status code returned from myenergi server"):
                ui.notify("The myenergi system may still processing the previous command. Wait some time before trying again.")

        elif GUIServer.INFO_MESSAGE in rxDict:
            info_message = rxDict[GUIServer.INFO_MESSAGE]
            ui.notify(info_message)
            # If we have confirmation from myenergi that the charge schedule was applied
            if info_message == GUIServer.SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE:
                ui.notify("Wait a few mins before selecting the Get button to check the schedule is set on your ZAPPI.", type='warning', timeout=5000)
                self._set_zappi_charge_active(True)
            # If we have confirmation from myenergi that all charge schedules were removed
            if info_message == GUIServer.CLEARED_ALL_CHARGING_SCHEDULES:
                self._set_zappi_charge_active(False)
                self._clear_zappi_button.enable()

        elif GUIServer.TANK_TEMPERATURES in rxDict:
            top_tank_temp, bottom_tank_temp = rxDict[GUIServer.TANK_TEMPERATURES]
            self._topTankTempLabel.text = top_tank_temp
            self._bottomTankTempLabel.text = bottom_tank_temp

        elif GUIServer.ZAPPI_CHARGE_SCHEDULE in rxDict:
            zappi_charge_table = rxDict[GUIServer.ZAPPI_CHARGE_SCHEDULE]
            self._display_zappi_charge_table(zappi_charge_table)

        elif GUIServer.PLOT_OPTIMAL_CHARGE_TIMES in rxDict:
            argList = rxDict[GUIServer.PLOT_OPTIMAL_CHARGE_TIMES]
            self._plot_optimal_charge_times(argList)

        elif GUIServer.CLEAR_PLOT in rxDict:
            if self._plot_container:
                self._plot_container.clear()

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
            ui.label('Boost Until').style(GUIServer.TEXT_STYLE_A)

        with ui.row().classes('w-full'):
            self._bootMinsSlider = ui.slider(min=15, max=240, value=15, step=15)
            self._bootMinsSlider.on('update:model-value', self._update_boost_time)
            # We call a method to convert the slider value in minutes to a boost until time.
            ui.label().bind_text_from(self, '_boost_time_value').style(GUIServer.TEXT_STYLE_B)
            self._update_boost_time()

        with ui.row():
            ui.label('Boost Control').style(GUIServer.TEXT_STYLE_A)

        with ui.row():
            self._boost_top_button = ColorButton(self._top_boost, 'Top').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            self._boost_bottom_button = ColorButton(self._bottom_boost, 'Bottom').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            # Set the mid color to yellow when heater is powered from the sun.
            self._boost_top_button.set_button_colors(["blue", 'yellow', 'green'])
            self._boost_bottom_button.set_button_colors(["blue", 'yellow', 'green'])
            self._boost_stop_button = ColorButton(self._stop_boost, 'Off').style("width: 100px; "+GUIServer.TEXT_STYLE_A_SIZE)
            self._buttonList.append(self._boost_top_button)
            self._buttonList.append(self._boost_bottom_button)
            # We don't add the _boost_stop_button to this list so that we can always issue a stop boost command
            # as the button will never be disabled.

    def _update_boost_time(self):
        """@brief Called to update the boost until time."""
        dt = datetime.now().astimezone()
        dt = dt + timedelta(minutes=self._bootMinsSlider.value)
        mins_to_add = 15 - (dt.minute % 15)
        dt = dt + timedelta(minutes=mins_to_add)
        self._boost_time_value = f"{dt.hour:02d}:{dt.minute:02d}"
        self._boost_until_datetime = dt.replace(second=0, microsecond=0)

    def _enable_buttons(self, enabled):
        for _button in self._buttonList:
            if enabled:
                _button.enable()
            else:
                _button.disable()

    def _top_boost(self):
        """@brief Turn on the top tank boost"""
        self._update_boost_time()
        self._eddi_heater_button_selected = 1
        self._enable_buttons(True)
        ui.notify("Setting top boost on.", position='center')
        threading.Thread(target=self._set_boost, args=(True, MyEnergi.TANK_TOP, self._boost_until_datetime)).start()
        self._reset_polling_rate()

    def _bottom_boost(self):
        """@brief Turn on the bottom tank boost"""
        self._update_boost_time()
        self._eddi_heater_button_selected = 2
        self._enable_buttons(True)
        ui.notify("Setting bottom boost on.", position='center')
        threading.Thread(target=self._set_boost, args=(True, MyEnergi.TANK_BOTTOM, self._boost_until_datetime)).start()
        self._reset_polling_rate()

    def _stop_boost(self):
        """@brief disable all tank boost schedules."""
        self._update_boost_time()
        self._eddi_heater_button_selected = 0
        self._enable_buttons(True)
        ui.notify("Turning off boost.", position='center')
        threading.Thread(target=self._set_boost, args=(False, None, None)).start()
        self._reset_polling_rate()
        self.clear_eddi_boost_schedule_time()

    def _update_gui(self, msg_dict):
        """@brief Send a message to the GUI to update it.
           @param msg_dict A dict containing details of how to update the GUI."""
        # Record the seconds when we received the message
        msg_dict[GUIServer.GUI_POLL_SECONDS] = time()
        self._to_gui_queue.put(msg_dict)

    def _previous_quarter_hour(self, dt):
        """@brief Get a datetime instance that is aligned with the a quarter hour starting just before the current one."""
        # Subtract the number of mins
        spare_mins = dt.minute % 15
        new_minute = dt.minute - spare_mins
        rounded_time = dt.replace(minute=new_minute, second=0, microsecond=0)
        return rounded_time

    def _set_boost(self, on, relay, on_until_time):
        """@brief Called in a separate thread to talk to the eddi unit and set the hot water boost state.
                  We don't use the boost command because of the way the eddi works in boost mode. If boost
                  mode is set on and the thermostat in the hot water tank heater disconnects the heater
                  element the eddi assumes the hot water tank temperature has been reached and the boost
                  is halted. This may mean the target tank temperature is not reached.

                  The scheduled timers are set to turn on the heater for a predetermined time. If the
                  thermostat in the hot water tank heater disconnects the heater element then the hot
                  water stops heating as it should. If, subsequentally, the thermostat reconnects the
                  heating element and it is still withing the scheduled time then the hot water will
                  resume heating the water if the tank temperature is yet to be reached.

                  We reserve the 4'th timer for this purpose. 10 minutes after the schedule has
                  finished the schedule is removed from the schedule list.

           @param on If True turn boost on. If False turn boost off on both top and bottom tanks.
           @param relay 1 = top tank relay, 2 = bottom tank relay.
           @param on_until_time A datetime instance that details when the hot water heating element
                                should be turned off (if on=True).
           """
        self._debug("set_boost(on={on}, relay={relay}, on_until_time={on_until_time})")
        if on:
            now = datetime.now().astimezone()
            schedule_start_time = self._previous_quarter_hour(now)
            schedule_duration = on_until_time - schedule_start_time
            self._debug("schedule_start_time={schedule_start_time}, schedule_duration  ={schedule_duration}")
            on_time = on_until_time - now
            heater_name = "top"
            if relay == 2:
                heater_name = "bottom"
            seconds = on_time.seconds
            msg_dict = {}
            minutes = seconds / 60
            hours = int(minutes / 60)
            minutes = int(minutes-(hours*60))
            msg_dict[GUIServer.INFO_MESSAGE] = f"The {heater_name} tank heater should turn on for {hours:02d}:{minutes:02d}"
            self._update_gui(msg_dict)

            # Send the schedule to the eddi
            self._my_energi.set_tank_schedule(on, schedule_start_time, schedule_duration, relay)

            # Set the delete schedule time to be 10 minutes after the tank heating  finishes. 10 minutes was chosen
            # as I've seen the myenergi system take up to 5 minutes to delete a schedule after sending a
            # successfull command. We want to have it clear before then next 15 minute slot.
            clear_schedule_time = on_until_time + timedelta(minutes=10)
            self._cfg_mgr.addAttr(GUIServer.CLEAR_EDDI_SCHEDULE_TIME, clear_schedule_time.strftime("%Y-%m-%dT%H:%M:%SZ"))
            self._debug(GUIServer.CLEAR_EDDI_SCHEDULE_TIME + f"={clear_schedule_time}")

        else:
            self._my_energi.set_water_tank_boost_schedules_off()
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = "Set boost schedule off."
            self._update_gui(msg_dict)

    def _is_eddi_config_entered(self):
        """@return True if the eddi config has been entered."""
        eddi_config_set = False
        api_key = self._cfg_mgr.getAttr(GUIServer.MYENERGI_API_KEY)
        eddi_serial_number = self._cfg_mgr.getAttr(GUIServer.EDDI_SERIAL_NUMBER)
        if api_key and \
           len(api_key) > 0 and \
           eddi_serial_number and \
           len(eddi_serial_number) > 0:
            eddi_config_set = True
        return eddi_config_set

    def _update_stats(self):
        """@brief Update the stats read from the network.
                  This should not be called in the GUI thread as it will block if there are network issues."""
        try:
            if self._is_eddi_config_entered():
                self._my_energi.update_stats()
                top_temp = self._my_energi.get_eddi_top_tank_temp()
                bottom_temp = self._my_energi.get_eddi_bottom_tank_temp()
                self._heater_load_watts = self._my_energi.get_eddi_heater_watts()
                try:
                    self._zappi_charge_watts = self._my_energi.get_zappi_charge_watts()
                except Exception:
                    zappi_serial_number = self._cfg_mgr.getAttr(GUIServer.ZAPPI_SERIAL_NUMBER)
                    # If the zappi serial number has been set raise an errror to show to the user as
                    # we shopuld be able to communicate with the zappi charger.
                    if len(zappi_serial_number) > 0:
                        raise
                self._relay_on = self._my_energi.get_eddi_heater_number()
                msg_dict = {}
                msg_dict[GUIServer.TANK_TEMPERATURES] = [top_temp, bottom_temp]
                self._update_gui(msg_dict)
        except Exception as ex:
            GUIServer.Print_Exception()
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
            kwh = self._cfg_mgr.getAttr(GUIServer.EV_BATTERY_KWH)
            self._ev_kwh = ui.number(label='EV Battery (kWh)', value=kwh, format='%.1f')

        with ui.row():
            self._electricity_region_code = ui.select(options=RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS,
                                                      value=RegionalElectricity.VALID_REGION_CODE_LIST_WITH_REGIONS[0],
                                                      with_input=True,
                                                      label='Electricity region code')

        with ui.row():
            self._tariff_radio = ui.radio(GUIServer.TARIFF_LIST,
                                          on_change=self._tariff_changed,
                                          value=GUIServer.TARIFF_LIST[0])

        with ui.row():
            # A plot of energy costs is added to this container when the users requests it
            self._other_tariff_plot_container = ui.element('div')

        with ui.row():
            self._add_tariff_value_button = ui.button('Add', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._add_tariff_value)
            self._clear_tariff_value_button = ui.button('Clear', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._clear_tariff)

        with ui.row():
            self._config_save_button = ui.button('Save', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=self._save_config_button_selected)

        self._api_key.value = self._cfg_mgr.getAttr(GUIServer.MYENERGI_API_KEY)
        self._eddi_serial_number.value = self._cfg_mgr.getAttr(GUIServer.EDDI_SERIAL_NUMBER)
        self._zappi_serial_number.value = self._cfg_mgr.getAttr(GUIServer.ZAPPI_SERIAL_NUMBER)
        self._zappi_max_charge_rate.value = self._cfg_mgr.getAttr(GUIServer.ZAPPI_MAX_CHARGE_RATE)
        self._electricity_region_code.value = self._cfg_mgr.getAttr(GUIServer.ELECTRICITY_REGION_CODE)
        self._octopus_agile_tariff = self._cfg_mgr.getAttr(GUIServer.OCTOPUS_AGILE_TARIFF)
        self._set_octopus_agile_tariff(self._octopus_agile_tariff)
        self._enable_octopus_agile_tariff(self._octopus_agile_tariff)

    def _save_config_button_selected(self):
        """@brief Called when the save button is selected by the user in the Setting tab."""
        self._save_config()
        # Create a new instance of the interface to talk to the myenergi products
        self._create_myenergi()

    def _set_octopus_agile_tariff(self, enabled):
        """@brief Set the radio buttons to enable the octopus agile tariff or the other (manually entered) tariff."""
        if enabled:
            self._tariff_radio.value = GUIServer.TARIFF_LIST[0]
        else:
            self._tariff_radio.value = GUIServer.TARIFF_LIST[1]

    def _enable_octopus_agile_tariff(self, enabled):
        """@brief Called when the octopus agile tariff is enabled."""
        if enabled:
            self._add_tariff_value_button.disable()
            self._clear_tariff_value_button.disable()
        else:
            self._add_tariff_value_button.enable()
            self._clear_tariff_value_button.enable()

    def _tariff_changed(self):
        """@brief Called when the tariff radio button is selected."""
        octopus_agile_tariff = self._is_octopus_agile_tariff_enabled()
        self._enable_octopus_agile_tariff(octopus_agile_tariff)
        if octopus_agile_tariff:
            self._add_tariff_value_button.disable()
            self._clear_tariff_value_button.disable()
            if self._other_tariff_plot_container:
                self._other_tariff_plot_container.clear()

        else:
            self._add_tariff_value_button.enable()
            self._clear_tariff_value_button.enable()
            self._plot_tariff()

    def _add_tariff_value(self):
        """@brief Add a tariff value to the displayed other tariff."""
        self._add_tariff_dialog = YesNoDialog("Add one tariff point.",
                                              self._tariff_value_entered,
                                              successButtonText="OK",
                                              failureButtonText="Cancel")
        self._add_tariff_dialog.addField(GUIServer.ADD_TARIFF_START_TIME, YesNoDialog.HOUR_MIN_INPUT_FIELD_TYPE)
        self._add_tariff_dialog.addField(GUIServer.ADD_TARIFF_PRICE, YesNoDialog.NUMBER_INPUT_FIELD_TYPE, minNumber=0, maxNumber=2, step=0.01)
        self._add_tariff_dialog.show()

    def _calc_cost_initial_step(self):
        """@brief Octopus Energy (and maybe other providers) currently send notifications to some customers (in areas that have high levels of green energy)
                  that they can have periods of time with free energy (Octopus Energy refer to these as 'Power Ups').
                  If the user selected the 'Free energy period' dialog then the user can enter the up coming free energy period so that the calculation of
                  the optimal charge time takes this into account."""
        if self._free_energy_checkbox.value:
            self._add_free_elect_period_dialog = YesNoDialog("Add free energy period.",
                                                             self._free_period_entered,
                                                             successButtonText="OK",
                                                             failureButtonText="Cancel")
            self._add_free_elect_period_dialog.addField(GUIServer.ZERO_COST_ELEC_START_TIME, YesNoDialog.HOUR_MIN_INPUT_FIELD_TYPE)
            self._add_free_elect_period_dialog.addField(GUIServer.ZERO_COST_ELEC_DURATION, YesNoDialog.HOUR_MIN_INPUT_FIELD_TYPE)
            self._add_free_elect_period_dialog.show()
        else:
            self._calc_optimal_charge_times()

    def _free_period_entered(self):
        """@brief Called if the user enters a period of time when they should get free energy. E.G Octopus 'Power Ups'"""
        start_time = self._add_free_elect_period_dialog.getValue(GUIServer.ZERO_COST_ELEC_START_TIME)
        duration = self._add_free_elect_period_dialog.getValue(GUIServer.ZERO_COST_ELEC_DURATION)
        self._calc_optimal_charge_times(free_start_time=start_time, free_duration=duration)

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
        start_time = self._add_tariff_dialog.getValue(GUIServer.ADD_TARIFF_START_TIME)
        price = self._add_tariff_dialog.getValue(GUIServer.ADD_TARIFF_PRICE)
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
            GUIServer.Print_Exception()
            ui.notify(f"{str(ex)}", type='negative')

    def _get_tariff(self):
        """@brief get a list of the tariff string values converted to datetime instances.
           @return tariff_datetime_list A list. Each element has two elements.
                   0: A datetime instance at incrementing times during the day.
                   1: The price of the electricity at that point in the day."""
        if len(self._other_tariff_values) == 0:
            raise Exception("Use the add button in the settings tab to set the tariff values through the day.")

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

                if _datetime.hour < dt.hour:
                    break
                elif _datetime.hour == dt.hour and _datetime.minute < dt.minute:
                    break

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
            fig.add_trace(go.Bar(x=time_intervals, y=prices, marker=dict(color='green')))
            if self._other_tariff_plot_container:
                self._other_tariff_plot_container.clear()
                # Add the new plot to the container
                with self._other_tariff_plot_container:
                    ui.plotly(fig)

        except Exception as ex:
            GUIServer.Print_Exception()
            ui.notify(f"{str(ex)}", type='negative')

    def _clear_tariff(self):
        """@brief Clear the other tariff values."""
        self._other_tariff_values = []
        if self._other_tariff_plot_container:
            self._other_tariff_plot_container.clear()

    def _check_eddi_access_ok(self, show_info=True):
        """@brief Check that the stats can be read from the myenergi eddi unit.
           @param show_info If True then show info messages.
           @return True if eddi access ok."""
        ok = False
        try:
            myEnergi = MyEnergi(self._api_key.value)
            myEnergi.set_eddi_serial_number(self._eddi_serial_number.value)
            myEnergi.get_eddi_stats()
            if show_info:
                ui.notify("Successfully read eddi stats.", position='center')
            ok = True
        except Exception as ex:
            GUIServer.Print_Exception()
            ui.notify(f"eddi: {str(ex)}", type='negative')
        return ok

    def _check_zappi_access_ok(self, show_info=True):
        """@brief Check that the stats can be read from the myenergi zappi unit.
           @return True if eddi access ok."""
        ok = False
        try:
            myEnergi = MyEnergi(self._api_key.value)
            myEnergi.set_eddi_serial_number(self._eddi_serial_number.value)
            myEnergi.set_zappi_serial_number(self._zappi_serial_number.value)
            myEnergi.get_zappi_stats()
            if show_info:
                ui.notify("Successfully read zappi stats.", position='center')
            ok = True
        except Exception as ex:
            GUIServer.Print_Exception()
            ui.notify(f"zappi: {str(ex)}", type='negative')
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

        with ui.row().classes('w-full'):
            with ui.row().classes('w-full'):
                ui.label('Target EV charge (%)')
                self._target_ev_charge_input = ui.number(min=5, max=100, value=0).style(GUIServer.TEXT_STYLE_D_SIZE)
            self._target_ev_charge_input.value = self._cfg_mgr.getAttr(GUIServer.TARGET_EV_CHARGE_PERCENTAGE)

        with ui.row().classes('w-full'):
            with ui.row().classes('w-full'):
                ui.label('Current EV charge (%)')
                self._current_ev_charge_input = ui.number(min=0, max=100, value=0).style(GUIServer.TEXT_STYLE_D_SIZE)
            self._current_ev_charge_input.value = self._cfg_mgr.getAttr(GUIServer.CURRENT_EV_CHARGE_PERCENTAGE)

        # Put this off the bottom of the mobile screen as most times it will not be needed
        # and there is not enough room on the mobile screen above the plot pane.
        self._end_charge_time_input = self._get_input_time_field('Ready by')
        self._end_charge_time_input.value = self._cfg_mgr.getAttr(GUIServer.READY_BY)

        self._free_energy_checkbox = ui.checkbox('Free energy period')

        with ui.row():
            # A plot of energy costs is added to this container when the users requests it
            self._plot_container = ui.element('div')

        with ui.row():
            self._calc_button = ColorButton(self._calc_cost_initial_step, 'Calc')
            self._calc_button.tooltip("Calculate the optimal charge time/s.")
            self._set_button = ColorButton(self._set_zappi_charge, 'Set')
            self._set_button.tooltip('Set the displayed charge schedule on your zappi charger.')
            self._get_button = ColorButton(self._get_zappi_charge, 'Get')
            self._get_button.tooltip('Get the current charge schedule on your zappi.')

            self._clear_zappi_button = ColorButton(self._clear_zappi_charge_schedules, 'Clear')
            self._clear_zappi_button.tooltip('Clear all charge schedules from your zappi charger.')

    def _get_zappi_charge(self):
        """@brief Get the current zappi charge schedule."""
        ui.notify("Reading the zappi charge shedules.")
        threading.Thread(target=self._get_zappi_charge_thread).start()

    def _send_zappi_sched_to_gui(self, table_row_list):
        """@brief After having read the zappi schedule list from the myenergi system
                  send it to the GUI.
           @param table_row_list A list of rows to add to the zappi charge table."""
        msg_dict = {}
        msg_dict[GUIServer.ZAPPI_CHARGE_SCHEDULE] = table_row_list
        self._update_gui(msg_dict)

    def _get_zappi_charge_thread(self):
        """@brief Read the zappi charge """
        try:
            table_row_list = self._my_energi.get_zappi_schedule_list()

            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = "Read the zappi charge shedules."
            self._update_gui(msg_dict)
            self._send_zappi_sched_to_gui(table_row_list)

        except Exception as ex:
            GUIServer.Print_Exception()
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _set_zappi_charge_active(self, active):
        """@brief Set the indicator to the user that shows that the zappi charge is active/inactive.
           @param active If True then a zappi charge schedule has been set."""
        self._zappi_charge_schedule_active = active

    def _display_zappi_charge_table(self, zappi_charge_sched_table):
        """@brief Display the table of configured zappi charge schedules.
           @param zappi_charge_sched_table A list of rows in the zappi charge schedule table."""
        # If we have somewhere to display the table.
        if self._plot_container:
            # Clear it's current contents.
            self._plot_container.clear()
            # Add the table to the displayed gui
            with self._plot_container:
                columns = [
                    {'name': 'Time', 'label': 'Time', 'field': 'Time', 'required': True, 'align': 'left'},
                    {'name': 'Duration', 'label': 'Duration', 'field': 'Duration', 'sortable': True},
                    {'name': 'Days', 'label': 'Days', 'field': 'Days', 'sortable': True},
                ]
                rows = []
                for row in zappi_charge_sched_table:
                    rows.append({'Time': row[0], 'Duration': row[1], 'Days': row[2]})
                ui.table(columns=columns, rows=rows, row_key='name')

        ui.timer(once=True, interval=2.0, callback=self._show_get_msg_delay)

    def _show_get_msg_delay(self):
        """@brief Show  messge to indicate to the user it may take a while before the
                  myenergi zappi schedule is updated."""
        ui.notify("The myenergi zappi schedule may take several mins to update after it has been set.")

    def _get_input_time_field(self, label):
        """@brief Add a control to allow the user to enter the time as an hour and min.
           @param label The label for the time field.
           @return The input field containing the hour and minute entered."""
        # Put this off the bottom of the mobile screen as most times it will not be needed
        # and there is not enough room on the mobile screen above the plot pane.
        with ui.row().classes('w-full'):
            ui.label(label)
            time_input = ui.input("(HH:MM)").style("width: 250px; "+GUIServer.TEXT_STYLE_E_SIZE)
            with time_input as time:
                with ui.menu().props('no-parent-event') as menu:
                    with ui.time().bind_value(time):
                        ui.button('Close', color=GUIServer.DEFAULT_BUTTON_COLOR, on_click=menu.close).props('flat')
                with time.add_slot('append'):
                    ui.icon('access_time').on('click', menu.open).classes('cursor-pointer')
        return time_input

    def _get_end_charge_time(self):
        """@brief Get the end charge time.
           @return A tuple
                   0 = Hours
                   1 = mins"""
        return self._get_hours_mins(self._end_charge_time_input.value)

    def _get_hours_mins(self, text):
        """@brief Get the hours and minutes from a string.
           @param text The text in HH:MM format.
           @return A tuple
                   0 = Hours
                   1 = mins

                   o None if not valid."""
        hours = None
        mins = None
        if text and len(text) >= 3:
            elems = text.split(':')
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

    def _calc_optimal_charge_times(self, free_start_time="", free_duration=""):
        """@brief Calculate the optimal charge times."""

        free_start_time_hh_mm = self._get_hours_mins(free_start_time)
        free_duration_hh_mm = self._get_hours_mins(free_duration)

        self._save_config(show_info=False)

        current_ev_charge_percentage = float(self._current_ev_charge_input.value)
        target_ev_charge_percentage = float(self._target_ev_charge_input.value)
        if target_ev_charge_percentage > 100:
            ui.notify("The target EV charge cannot be greater than 100 %.", type='negative')
            return

        # Define the target as a float at the top end of the value.
        target_ev_charge_percentage = float(int(self._target_ev_charge_input.value)) + 0.99

        ev_battery_kwh = self._ev_kwh.value

        if ev_battery_kwh <= 0.0:
            ui.notify("Please set an EV battery capacity greater than 0 in the settings tab.", type='negative')
            return

        target_charge_factor = target_ev_charge_percentage/100.0
        current_charge_factor = current_ev_charge_percentage/100.0

        if current_charge_factor > 1.0:
            ui.notify("The current EV charge cannot be greater than 100 %.", type='negative')
            return

        # If the current charge factor is greater than is already present in the battery
        if current_charge_factor >= target_charge_factor:
            ui.notify(f"The current charge ({current_ev_charge_percentage:.1f} %) is greater than target charge of {target_ev_charge_percentage:.1f} %.", type='negative')
            return

        required_charge_factor = float(target_charge_factor - current_charge_factor)
        charge = required_charge_factor * float(ev_battery_kwh)

        charge_time_mins = 0
        if charge == 0 and charge_time_mins == 0 or \
           charge != 0 and charge_time_mins != 0:
            ui.notify("You must set either the charge or charge time greater than 0.", type='negative')
            return

        if charge > 0:
            charge_time_mins = int((charge/float(self._zappi_max_charge_rate.value))*60)
            # Ensure a multiple of 15 mins as we don't want to be turning the charger on/off
            # any more quickly than this. MyEnergi only allows charge times in chunks of 15 mins.
            remainder = charge_time_mins % 15
            if remainder > 0:
                charge_time_mins = charge_time_mins - remainder

        region_code = self._get_region_code()
        ui.notify("Calculating optimal charge time/s.", position='center', type='ongoing', timeout=1000)
        threading.Thread(target=self.calc_optimal_charge_times_thread, args=(region_code,
                                                                             charge_time_mins,
                                                                             float(self._zappi_max_charge_rate.value),
                                                                             self._get_end_charge_time(),
                                                                             free_start_time_hh_mm,
                                                                             free_duration_hh_mm)).start()

    def _get_region_code(self):
        """@brief Get the electricity region code.
           @return The single letter electricity region code or None if not set."""
        region_code = self._electricity_region_code.value
        if region_code:
            elems = region_code.split()
            region_code = elems[0]
        return region_code

    @staticmethod
    def GET_END_CHARGE_DATETIME(end_charge_time):
        """@brief Get the end charge time as a datetime instance.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed or None if no charge time defined."""
        end_charge_datetime = None
        # If the end charge time is defined then ensure we don't have time after this in the list.
        if end_charge_time:
            now = datetime.now().astimezone()
            end_charge_time_today = now.replace(hour=end_charge_time[0], minute=end_charge_time[1], second=0, microsecond=0)
            # If the user entered a time that is earlier today
            if end_charge_time_today < now:
                # Assume that the time entered is is tomorrow.
                end_charge_time_tomorrow = end_charge_time_today + timedelta(days=1)
                end_charge_datetime = end_charge_time_tomorrow
            else:
                now = datetime.now().astimezone()
                # Add the HH:MM to the time
                then = now + timedelta(hours=end_charge_time[0], minutes=end_charge_time[1])
                then = then.replace(second=0, microsecond=0)
                end_charge_datetime = then
        return end_charge_datetime

    def _get_tariff_data(self, end_charge_time):
        """@brief Get the tariff data needed to calculate the best charge times when not
                  one octopus agile tariff.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed."""
        start_datetime = RegionalElectricity.GET_NEXT_30_MIN_TIME()
        # Get a value for every 1/2 hour through the day and into the next
        time_intervals = [start_datetime + timedelta(minutes=30 * i) for i in range((48*2))]

        # If the end charge time is defined then ensure we don't have time after this in the list.
        if end_charge_time:
            then = GUIServer.GET_END_CHARGE_DATETIME(end_charge_time)

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

    def _update_free_periods(self,
                             free_start_time_hh_mm,
                             free_duration_hh_mm,
                             plot_time_stamp_list,
                             plot_cost_list):
        """@brief UPdate the tariff periods with any free energy periods.
           @param free_start_time_hh_mm A tuple containing HH, MM of the start time of a free energy period or None if no free energy period is available.
           @param free_duration_hh_mm A tuple containing HH, MM of the duration of a free energy period or None if no free energy period is available.
           @param plot_time_stamp_list A list of the tariff times.
           @param plot_cost_list A list of the tariff costs."""

        # If the user has entered a period of time when they will get free energy
        if free_start_time_hh_mm and free_duration_hh_mm:
            # Update the tariff values with the zero cost energy times.
            free_start_time = None
            free_stop_time = None
            for index in range(0, len(plot_time_stamp_list)):
                ts = plot_time_stamp_list[index]
                if ts.hour == free_start_time_hh_mm[0]:
                    # We assume that the HH:MM entered by the user is the next HH:MM that come round.
                    free_start_time = plot_time_stamp_list[index].replace(hour=free_start_time_hh_mm[0], minute=free_start_time_hh_mm[1], second=0, microsecond=0)
                    free_stop_time = free_start_time + timedelta(hours=free_duration_hh_mm[0], minutes=free_duration_hh_mm[1])
                    break

            # If we have a free energy period
            if free_start_time and free_stop_time:
                # Set the cost of energy in this period to 0
                for index in range(0, len(plot_time_stamp_list)):
                    ts = plot_time_stamp_list[index]
                    if ts >= free_start_time and ts <= free_stop_time:
                        plot_cost_list[index] = 0.0

    def _get_charge_details(self,
                            charge_mins,
                            end_charge_time,
                            charge_rate_kw,
                            region_code,
                            free_start_time_hh_mm,
                            free_duration_hh_mm):
        """@brief Get the requested charge details.
           @param charge_mins The required charge time in mins.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed.
           @param charge_rate_kw The rate at which the charger will charge the EV in kW.
           @param region_code The regional electricity code.
           @param free_start_time_hh_mm A tuple containing HH, MM of the start time of a free energy period or None if no free energy period is available.
           @param free_duration_hh_mm A tuple containing HH, MM of the duration of a free energy period or None if no free energy period is available.
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

        # Update the slots with any free energy periods
        self._update_free_periods(free_start_time_hh_mm, free_duration_hh_mm, plot_time_stamp_list, plot_cost_list)

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
                                         charge_mins,
                                         charge_rate_kw,
                                         end_charge_time,
                                         free_start_time_hh_mm,
                                         free_duration_hh_mm):
        """@brief Calculate optimal charge times.
           @param region_code The regional electricity code.
           @param plot_container The container that will hold the plot.
           @param charge_mins The required charge time in mins.
           @param charge_rate_kw The EV charge rate in kW.
           @param end_charge_time The time (a tuple hours,mins) at which the charging must have completed.
           @param free_start_time_hh_mm A tuple containing HH, MM of the start time of a free energy period or None if no free energy period is available.
           @param free_duration_hh_mm A tuple containing HH, MM of the duration of a free energy period or None if no free energy period is available.
           @return A dict containing the slots that the car should charge in."""
        try:
            charge_slot_dict_list, end_charge_datetime, plot_time_stamp_list, plot_cost_list, total_charge_mins, cost = self._get_charge_details(charge_mins,
                                                                                                                                                 end_charge_time,
                                                                                                                                                 charge_rate_kw,
                                                                                                                                                 region_code,
                                                                                                                                                 free_start_time_hh_mm,
                                                                                                                                                 free_duration_hh_mm)

            msg_dict = {}
            msg_dict[GUIServer.PLOT_OPTIMAL_CHARGE_TIMES] = (charge_slot_dict_list, end_charge_datetime, plot_time_stamp_list, plot_cost_list, total_charge_mins, cost)
            self._update_gui(msg_dict)

        except Exception as ex:
            GUIServer.Print_Exception()
            # As we've had an error clear any displayed plot before letting the user know
            msg_dict = {}
            msg_dict[GUIServer.CLEAR_PLOT] = ""
            self._update_gui(msg_dict)
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _plot_optimal_charge_times(self, arg_list):
        """@brief Plot the optimal charge times."""
        # Assign the variables from the arg list
        charge_slot_dict_list, end_charge_datetime, plot_time_stamp_list, plot_cost_list, total_charge_mins, cost = arg_list
        try:
            # Clear the old plot
            self._plot_container.clear()

            fig = go.Figure()
            max_cost = max(plot_cost_list)
            min_cost = min(plot_cost_list)
            if min_cost > 0:
                min_cost = 0
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0),
                              width=350,
                              height=200,
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
                                  range=[min_cost*1.5, max_cost*1.5]
                              ),)

            fig.add_trace(go.Bar(x=plot_time_stamp_list, y=plot_cost_list, opacity=0.5, marker=dict(color='green')))

            self._plot_charge_times(fig, charge_slot_dict_list)

            # Add the new plot to the container
            with self._plot_container:
                ui.plotly(fig)

            with self._plot_container:
                hours_charge_factor = total_charge_mins/60.0
                charge_adjustment_factor = self._cmd_line_config_manager.getAttr(GUIServer.ZAPPI_CHARGE_ADJUSTMENT_FACTOR_FLOAT)
                kwh = charge_adjustment_factor * (hours_charge_factor*float(self._zappi_max_charge_rate.value))
                battery_charged_percentage = self._target_ev_charge_input.value
                # we may be charging slightly longer than is required (due to 15 min charge increments)
                # so limit the max to 100%
                if battery_charged_percentage > 100.0:
                    battery_charged_percentage = 100.0
                ui.label(f"Charge for {int(total_charge_mins)} minutes to reach {battery_charged_percentage:.0f}%")
                ui.label(f"using {kwh:.1f} kWh of energy (cost = £{cost:.2f}).")

            self._charge_slot_dict_list = charge_slot_dict_list

        except Exception as ex:
            GUIServer.Print_Exception()
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _plot_charge_times(self, fig, charge_slot_dict_list):
        """@brief Plot the charge times in red on the charge plot.
           @param fig plotly figure as returned from go.Figure()
           @param charge_slot_dict_list"""
        for charge_slot_dict in charge_slot_dict_list:
            startT = charge_slot_dict[RegionalElectricity.SLOT_START_DATETIME]
            stopT = charge_slot_dict[RegionalElectricity.SLOT_STOP_DATETIME]
            x = [startT, stopT]
            y = [charge_slot_dict[RegionalElectricity.SLOT_COST], charge_slot_dict[RegionalElectricity.SLOT_COST]]
            fig.add_trace(go.Scatter(x=x, y=y, line=dict(width=5), marker=dict(size=10, color='red')))

    def _set_zappi_charge(self):
        """@brief Set a zappi charge schedule."""
        if self._charge_slot_dict_list is None:
            ui.notify("No charge schedule found.", type='negative')
        else:
            ui.notify("Setting zappi charge schedule", position='center')
            threading.Thread(target=self._set_zappi_charge_thread).start()
            self._reset_polling_rate()

    def _set_zappi_charge_thread(self):
        # Sort the dicts in the list on the slot start time. The slot closest in time will be first in the list.
        # The zappi hargr must be set to eco+ mode to run the charge schedule.
        # Check for this and set if required.
        zapp_charge_mode = self._my_energi.get_zappi_charge_mode()
        if zapp_charge_mode != MyEnergi.ZAPPI_CHARGE_MODE_ECO_PLUS:
            self._my_energi.set_zappi_mode_eco_plus()
            # Display a messge to let the user know that the mode had to be set to eco+
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = "Set the zappi to eco+ charge mode."
            self._update_gui(msg_dict)

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
            if len(merged_charge_slot_dict_list) == 0:
                raise Exception("The calculated charge schedule has no duration.")

            self._my_energi.set_zappi_charge_schedule(merged_charge_slot_dict_list)
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = GUIServer.SET_ZAPPI_CHARGE_SCHEDULE_MESSAGE
            self._update_gui(msg_dict)

            # Get the end of the last charge slot
            charge_end_time = merged_charge_slot_dict_list[-1][RegionalElectricity.SLOT_STOP_DATETIME]
            # Set the delete schedule time to be 10 minutes after the charge finishes. 10 minutes was chosen
            # as I've seen the myenergi system take up to 5 minutes to delete a schedule after sending a
            # successfull command. We want to have it clear before then next 15 minute charge slot.
            clear_schedule_time = charge_end_time + timedelta(minutes=10)
            self._cfg_mgr.addAttr(GUIServer.CLEAR_ZAPPI_SCHEDULE_TIME, clear_schedule_time.strftime("%Y-%m-%dT%H:%M:%SZ"))

        except Exception as ex:
            GUIServer.Print_Exception()
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def _clear_zappi_charge_schedules(self):
        """@brief Reset/disable all zappi charge schedules. Called from the GUI thread. This starts the thread that actually does the work."""
        ui.notify("Clearing all zappi charge schedules", position='center', type='ongoing', timeout=4500)
        self._plot_container.clear()
        self._charge_slot_dict_list = None
        # Reset this so that the Set button returns to it's original color.
        self._zappi_charge_schedule_active = False
        self._clear_zappi_button.disable()
        threading.Thread(target=self._clear_zappi_charge_schedules_thread).start()

    def _clear_zappi_charge_schedules_thread(self):
        """@brief Reset/disable all zappi charge schedules. This must be called outside the GUI thread."""
        try:
            self._my_energi.set_all_zappi_schedules_off()
            msg_dict = {}
            msg_dict[GUIServer.INFO_MESSAGE] = GUIServer.CLEARED_ALL_CHARGING_SCHEDULES
            self._update_gui(msg_dict)
        except Exception as ex:
            GUIServer.Print_Exception()
            msg_dict = {}
            msg_dict[GUIServer.ERROR_MESSAGE] = str(ex)
            self._update_gui(msg_dict)

    def command_line_config(self):
        """@brief Allow the user to configure the command line parameters."""
        self._cmd_line_config_manager.edit(GUIServer.CMD_LINE_CONFIG_ATTR_DICT)


def main():
    """@brief Program entry point"""
    uio = UIO()
    options = None

    try:
        parser = argparse.ArgumentParser(description="A program that provides a display interface for myenergi products.",
                                         formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("-p", "--port",    type=int, help=f"The TCP server port to which the GUI server is bound to (default={GUIServer.DEFAULT_SERVER_PORT}).", default=GUIServer.DEFAULT_SERVER_PORT)
        parser.add_argument("-c", "--config",  action='store_true', help="Command line configuration.")
        parser.add_argument("--reload",        action='store_true', help="Reload/Restart GUI when python file is updated. Useful for in dev env.")
        parser.add_argument("--show",          action='store_true', help="Show the GUI (open browser window) on startup.")
        parser.add_argument("-d", "--debug",   action='store_true', help="Enable debugging of the myenergi_display program.")
        parser.add_argument("--nicegui_debug", action='store_true', help="Enable debugging of the nicegui python module.")
        parser.add_argument("-s", "--syslog",  action='store_true', help="Enable syslog.")
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
            if options.config:
                gui.command_line_config()

            else:

                gui.create_gui(options.nicegui_debug,
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
