# coding=utf-8
from __future__ import absolute_import

from os import path as ospath
import math
import logging
from webdav3.client import Client
from webdav3.exceptions import WebDavException
from datetime import datetime
from http import HTTPStatus
import octoprint.plugin
from octoprint.events import Events, eventManager
from octoprint.server import user_permission
from octoprint.server import admin_permission
from octoprint.settings import settings
import flask

SETTINGS_DEFAULTS = dict(
    server=None,
    username=None,
    password=None,
    timeout=30,
    verify_certificate=True,
    upload_path="/"
)

class WebDavBackupPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SimpleApiPlugin,
):

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    ##~~ SettingsPlugin mixin
    def get_settings_defaults(self):
        return SETTINGS_DEFAULTS

    def on_settings_load(self):
        data = octoprint.plugin.SettingsPlugin.on_settings_load(self)
        return data

    def on_settings_save(self, data):
        if "server" in data and not data["server"]:
            data["server"] = None

        if "username" in data and not data["username"]:
            data["username"] = None

        if "password" in data and not data["password"]:
            data["password"] = None

        if "upload_path" in data and not data["upload_path"]:
            data["upload_path"] = None

        if "upload_name" in data and not data["upload_name"]:
            data["upload_name"] = None

        if "timeout" in data:
            try:
                data["timeout"] = int(data["timeout"])
            except:
                self._logger.exception("Got an invalid value to save for timeout, ignoring it")
                del data["timeout"]

        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

    ##~~ EventHandlerPlugin mixin
    def on_event(self, event, payload):
        if event == "plugin_backup_backup_created":
            # Helper function for human readable sizes
            def _convert_size(size_bytes):
                if size_bytes == 0:
                    return "0B"
                size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
                i = int(math.floor(math.log(size_bytes, 1024)))
                p = math.pow(1024, i)
                s = round(size_bytes / p, 2)
                return "%s %s" % (s, size_name[i])

            now = datetime.now()

            davoptions = {
                'webdav_hostname': self._settings.get(["server"]),
                'webdav_login':    self._settings.get(["username"]),
                'webdav_password': self._settings.get(["password"]),
                'webdav_timeout': self._settings.get(["timeout"]),
            }

            backup_path = payload["path"]
            backup_name = payload["name"]
            self._logger.info("Backup " + backup_path + " created, will now attempt to upload to " + davoptions["webdav_hostname"])

            davclient = Client(davoptions)
            davclient.verify = self._settings.get(["verify_certificate"])
            upload_path = now.strftime(self._settings.get(["upload_path"]))
            upload_path = ospath.join("/", upload_path)
            if self._settings.get(["upload_name"]):
                upload_name = now.strftime(self._settings.get(["upload_name"])) + ospath.splitext(backup_path)[1]
                self._logger.debug("Filename for upload: " + upload_name)
            else:
                upload_name = backup_name
            upload_file = ospath.join("/", upload_path, upload_name)
            upload_temp = ospath.join("/", upload_path, upload_name + ".tmp")

            # Check actual connection to the WebDAV server as the check command will not do this.
            try:
                dav_free = davclient.free()
            except WebDavException as exception:
                # Write error and exit function
                status = HTTPStatus(exception.code)
                switcher = {
                    400: "Bad request",
                    401: "Unauthorized",
                    403: "Forbidden",
                    404: "Not found",
                    405: "Method not allowed",
                    408: "Request timeout",
                    500: "Internal error",
                    501: "Not implemented",
                    502: "Bad gateway",
                    503: "Service unavailable",
                    504: "Gateway timeout",
                    508: "Loop detected",
                }
                http_error = str(status.value) + " " + switcher.get(exception.code, status.phrase)
                self._logger.error("HTTP error encountered: " + http_error)
                return

            self._logger.info("Free space on server: " + _convert_size(dav_free))

            backup_size = ospath.getsize(backup_path)
            self._logger.info("Backup file size: " + _convert_size(backup_size))

            if backup_size > dav_free:
                self._logger.error("Unable to upload, size is" + _convert_size(backup_size) + ", free space is " + _convert_size(dav_free))
            else:
                # Helper function to recursively create paths
                def _recursive_create_path(path):
                    # Append leading / for preventing abspath issues
                    path = ospath.join("/", path)
                    if davclient.check(path):
                        self._logger.debug("Directory " + path + " was found.")
                    else:
                        self._logger.debug("Directory " + path + " was not found, checking parent.")
                        _recursive_create_path(ospath.abspath(ospath.join(path, "..")))
                        davclient.mkdir(path)
                        self._logger.debug("Directory " + path + " has been created.")

                _recursive_create_path(upload_path)

                davclient.upload_sync(remote_path=upload_temp, local_path=backup_path)
                davclient.move(remote_path_from=upload_temp, remote_path_to=upload_file)
                self._logger.info("Backup has been uploaded successfully to " + davoptions["webdav_hostname"] + " as " + upload_file)

    ##~~ TemplatePlugin mixin
    def get_template_configs(self):
        return [
            dict(
                type="settings", custom_bindings=False
            )
        ]

    #~~ AssetPlugin API

    def get_assets(self):
        return dict(js=["js/webdavbackup.js"])

    #~~ SimpleApiPlugin

    def get_api_commands(self):
        return dict(test=["test_connection","create_test_file"])

    def on_api_command(self, command, data):
        self._logger.info("API command received: " + command)
        if not admin_permission.can():
            return flask.make_response("Insufficient permissions", 403)

        # Only reply on available commands
        available_commands = self.get_api_commands()
        if not command in available_commands:
            return

        davoptions = {
            'webdav_hostname': data.get("server"),
            'webdav_login': data.get("username"),
            'webdav_password': data.get("password"),
            'webdav_timeout': data.get("timeout"),
        }

        davclient = Client(davoptions)
        davclient.verify = data.get("verify_certificate")

        # Check actual connection to the WebDAV server by retrieving free space.
        try:
            dav_free = davclient.free()
        except WebDavException as exception:
            # Write error and exit function
            status = HTTPStatus(exception.code)
            dav_error_switcher = {
                400: "Bad request",
                401: "Unauthorized",
                403: "Forbidden",
                404: "Not found",
                405: "Method not allowed",
                408: "Request timeout",
                500: "Internal error",
                501: "Not implemented",
                502: "Bad gateway",
                503: "Service unavailable",
                504: "Gateway timeout",
                508: "Loop detected",
            }
            http_error = str(status.value) + " " + dav_error_switcher.get(exception.code, status.phrase)
            self._logger.error("HTTP error encountered: " + http_error)
            return flask.make_response(flask.jsonify(result=False, error="credentials"))
        self._logger.info("Connection test successful")
        if command == "test_connection":
            return flask.make_response(flask.jsonify(result=dav_free))
        else:
            return flask.make_response(flask.jsonify(result="Not implemented"))

    ##~~ Softwareupdate hook
    def get_update_information(self):
        return dict(
            webdavbackup=dict(
                displayName=self._plugin_name,
                displayVersion=self._plugin_version,

                type="github_release",
                user="edekeijzer",
                repo="OctoPrint-WebDavBackup",
                current=self._plugin_version,

                pip="https://github.com/edekeijzer/OctoPrint-WebDavBackup/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "WebDAV Backup"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = WebDavBackupPlugin()

    # global __plugin_hooks__
    # __plugin_hooks__ = {
    #     "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    # }