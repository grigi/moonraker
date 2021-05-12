# Octoprint API compatibility
#
# Copyright (C) 2021 Nickolas Grigoriadis <nagrigoriadis@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

import utils

OCTO_VERSION = '1.5.0'


class OctoprintCompat:
    """
    Minimal implementation of the REST API as described here:
    https://docs.octoprint.org/en/master/api/index.html

    So that Cura Octoprint plugin will function for:
    * Handshake
    * Upload gcode/ufp
    * Webcam config
    * Manual GCode submission
    * Heater temperatures
    """

    def __init__(self, config):
        self.server = config.get_server()
        self.software_version = config['system_args'].get('software_version')

        # Webcam settings
        self.webcam_enabled = config.getboolean('webcam_enabled', True)
        self.webcam_stream_url = config.get(
            'webcam_stream_url', '/webcam/?action=stream')
        self.webcam_flip_h = config.getboolean('webcam_flip_h', True)
        self.webcam_flip_v = config.getboolean('webcam_flip_v', True)
        self.webcam_rotate90 = config.getboolean('webcam_rotate90', True)

        # Local variables
        self.klippy_apis = self.server.lookup_component('klippy_apis')
        self.heaters = {}
        self.last_print_stats = {}
        self.selected_filename = ''

        # Register status update event
        self.server.register_event_handler(
            'server:klippy_ready', self._init)
        self.server.register_event_handler(
            'server:status_update', self._handle_status_update)

        # Version & Server information
        self.server.register_endpoint(
            '/api/version', ['GET'], self._get_version, wrap_result=False)
        self.server.register_endpoint(
            '/api/server', ['GET'], self._get_server, wrap_result=False)

        # Login, User & Settings
        self.server.register_endpoint(
            '/api/login', ['POST'], self._post_login_user, wrap_result=False)
        self.server.register_endpoint(
            '/api/currentuser', ['GET'], self._post_login_user,
            wrap_result=False)
        self.server.register_endpoint(
            '/api/settings', ['GET'], self._get_settings, wrap_result=False)

        # File operations
        # Note that file upload is handled in file_manager.py
        # TODO: List/info/select/delete files

        # Job operations
        self.server.register_endpoint(
            '/api/job', ['GET'], self._get_job, wrap_result=False)
        self.server.register_endpoint(
            '/api/job', ['POST'], self._post_job, wrap_result=False)

        # Printer operations
        self.server.register_endpoint(
            '/api/printer', ['GET'], self._get_printer, wrap_result=False)
        self.server.register_endpoint(
            '/api/printer/command', ['POST'], self._post_command,
            wrap_result=False)
        # TODO: head/tool/bed/chamber specific read/issue

        # Printer profiles
        self.server.register_endpoint(
            '/api/printerprofiles', ['GET'], self._get_printerprofiles,
            wrap_result=False)

        # System
        # TODO: shutdown/reboot/restart operations

    async def _init(self):
        self.heaters = {}
        # Fetch heaters
        try:
            result = await self.klippy_apis.query_objects({'heaters': None})
            sensors = result.get('heaters', {}).get('available_sensors', [])
        except self.server.error as e:
            logging.info(f'Error Configuring heaters: {e}')
            sensors = []
        # subscribe objects
        sub = {s: None for s in sensors}
        sub['print_stats'] = None
        result = await self.klippy_apis.subscribe_objects(sub)
        self.last_print_stats = result.get('print_stats', {})
        if sensors:
            self.heaters = {name: result.get(name, {}) for name in sensors}

    def _handle_status_update(self, status):
        if 'print_stats' in status:
            self.last_print_stats.update(status['print_stats'])
        for heater_name, data in self.heaters.items():
            if heater_name in status:
                data.update(status[heater_name])

    def printer_state(self):
        klippy_state = self.server.get_klippy_state()
        if klippy_state in ["disconnected", "startup"]:
            return 'Offline'
        elif klippy_state != 'ready':
            return 'Error'
        return {
            'standby': 'Operational',
            'printing': 'Printing',
            'paused': 'Paused',
            'complete': 'Operational'
        }.get(self.last_print_stats.get('state', 'standby'), 'Error')

    def printer_temps(self):
        temps = {}
        for heater, data in self.heaters.items():
            name = 'bed'
            if heater.startswith('extruder'):
                try:
                    tool_no = int(heater[8:])
                except ValueError:
                    tool_no = 0
                name = f'tool{tool_no}'
            elif heater != "heater_bed":
                continue
            temps[name] = {
                'actual': round(data.get('temperature', 0.), 2),
                'offset': 0,
                'target': data.get('target', 0.),
            }
        return temps

    async def _get_version(self, web_request):
        """
        Version information
        """
        return {
            'server': OCTO_VERSION,
            'api': '0.1',
            'text': f'OctoPrint (Moonraker {self.software_version})',
        }

    async def _get_server(self, web_request):
        """
        Server status
        """
        klippy_state = self.server.get_klippy_state()
        return {
            'server': OCTO_VERSION,
            'safemode': (
                None if klippy_state == 'ready' else 'settings')
        }

    async def _post_login_user(self, web_request):
        """
        Confirm session login.

        Since we only support apikey auth, do nothing.
        Report hardcoded user called _api
        """
        return {
            '_is_external_client': False,
            '_login_mechanism': 'apikey',
            'name': '_api',
            'active': True,
            'user': True,
            'admin': True,
            'apikey': None,
            'permissions': [],
            'groups': ['admins', 'users'],
        }

    async def _get_settings(self, web_request):
        """
        Used to parse Octoprint capabilities

        Hardcode capabilities to be basically there and use configurable
        fluid/mainsail webcam path.
        """
        return {
            'plugins': {
                'UltimakerFormatPackage': {
                    'align_inline_thumbnail': False,
                    'inline_thumbnail': False,
                    'inline_thumbnail_align_value': 'left',
                    'inline_thumbnail_scale_value': '50',
                    'installed': True,
                    'installed_version': '0.2.2',
                    'scale_inline_thumbnail': False,
                    'state_panel_thumbnail': True,
                },
            },
            'feature': {
                'sdSupport': False,
                'temperatureGraph': False
            },
            'webcam': {
                'flipH': self.webcam_flip_h,
                'flipV': self.webcam_flip_v,
                'rotate90': self.webcam_rotate90,
                'streamUrl': self.webcam_stream_url,
                'webcamEnabled': self.webcam_enabled,
            },
        }

    async def _get_job(self, web_request):
        """
        Get current job status
        """
        return {
            'job': {
                'file': {'name': None},
                'estimatedPrintTime': None,
                'filament': {'length': None},
                'user': None,
            },
            'progress': {
                'completion': None,
                'filepos': None,
                'printTime': None,
                'printTimeLeft': None,
                'printTimeOrigin': None,
            },
            'state': self.printer_state()
        }

    async def _post_job(self, web_request):
        """
        Get current job status
        """
        command = web_request.get('command', '')
        fail = False

        try:
            if command == 'start':
                # NOTE: Won't work until select file is implemented
                if self.selected_filename:
                    await self.start_print(self.selected_filename)
                else:
                    fail = True
            elif command == 'cancel':
                await self.klippy_apis.self.run_gcode("CANCEL_PRINT")
            elif command == 'pause':
                action = web_request.get('action', '')
                if action == 'pause':
                    await self.klippy_apis.run_gcode("PAUSE")
                elif action == 'resume':
                    await self.klippy_apis.run_gcode("RESUME")
                elif action == 'toggle':
                    state = self.printer_state()
                    if state == 'Paused':
                        await self.klippy_apis.run_gcode("RESUME")
                    elif state == 'Printing':
                        await self.klippy_apis.run_gcode("PAUSE")
                    else:
                        fail = True
                else:
                    fail = True
            else:
                fail = True
        except self.server.error:
            fail = True

        # Any fail must be 409 Conflict
        if fail:
            raise self.server.error("Conflict", 409)

        # Any success must be 204 No Content
        raise self.server.error("No Content", 204)

    async def _get_printer(self, web_request):
        """
        Get Printer status
        """
        state = self.printer_state()
        return {
            'temperature': self.printer_temps(),
            'state': {
                'text': state,
                'flags': {
                    'operational': state not in ['Error', 'Offline'],
                    'paused': state == 'Paused',
                    'printing': state == 'Printing',
                    'cancelling': state == 'Cancelling',
                    'pausing': False,
                    'error': state == 'Error',
                    'ready': state == 'Operational',
                    'closedOrError': state in ['Error', 'Offline'],
                },
            },
        }

    async def _post_command(self, web_request):
        """
        Request to run some gcode command
        """
        commands = web_request.get('commands', [])
        for command in commands:
            logging.info(f'Executing GCode: {command}')
            try:
                await self.klippy_apis.run_gcode(command)
            except self.server.error:
                msg = f"Error executing GCode {command}"
                logging.exception(msg)

        return {}

    async def _get_printerprofiles(self, web_request):
        """
        Get Printer profiles
        """
        return {
            'profiles': {
                '_default': {
                    'id': '_default',
                    'name': 'Default',
                    'color': 'default',
                    'model': 'Default',
                    'default': True,
                    'current': True,
                    'heatedBed': 'heater_bed' in self.heaters,
                    'heatedChamber': 'chamber' in self.heaters,
                }
            }
        }


def load_component(config):
    return OctoprintCompat(config)
