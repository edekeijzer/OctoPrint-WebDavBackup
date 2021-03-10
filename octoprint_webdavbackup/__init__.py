# coding=utf-8
from __future__ import absolute_import

from os import path as ospath
import math
import logging
from webdav3.client import Client
from webdav3.exceptions import WebDavException,ResponseErrorCode,RemoteResourceNotFound
from datetime import datetime
from http import HTTPStatus
import octoprint.plugin
from octoprint.events import Events, eventManager
from octoprint.server import user_permission
from octoprint.settings import settings

# Tick boxes set to default of True
SETTINGS_DEFAULTS = dict(
    server=None,
    username=None,
    password=None,
    timeout=30,
    verify_certificate=True,
    upload_path="/",
    check_space=True,
    check_directories=True
)

class WebDavBackupPlugin(octoprint.plugin.SettingsPlugin,
                              octoprint.plugin.AssetPlugin,
                              octoprint.plugin.TemplatePlugin,
                              octoprint.plugin.EventHandlerPlugin,
):

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    ##~~ SettingsPlugin mixin
    def get_settings_defaults(self):
        return SETTINGS_DEFAULTS

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
            
            # Disables checking of remote WebDAV server using WebDAV_root.
            # Checking causes errors with certain remote servers.
            if self._settings.get(["check_directories"]): 
                checks_disabled = False
            else:
                checks_disabled =  True

            davoptions = {
                'webdav_hostname': self._settings.get(["server"]),
                'webdav_login':    self._settings.get(["username"]),
                'webdav_password': self._settings.get(["password"]),
                'webdav_timeout':  self._settings.get(["timeout"]),
                'disable_check':   checks_disabled,
            }

            backup_path = payload["path"]
            backup_name = payload["name"]
            self._logger.info("Backup " + backup_path + " created, will now attempt to upload to " + davoptions["webdav_hostname"])

            davclient = Client(davoptions)
            davclient.verify = self._settings.get(["verify_certificate"])
            check_space = self._settings.get(["check_space"])
            upload_path = now.strftime(self._settings.get(["upload_path"]))
            upload_path = ospath.join("/", upload_path)

            if self._settings.get(["upload_name"]):
                upload_name = now.strftime(self._settings.get(["upload_name"])) + ospath.splitext(backup_path)[1]
            else:
                upload_name = backup_name
            self._logger.debug("Filename for upload: " + upload_name)

            upload_file = ospath.join("/", upload_path, upload_name)
            upload_temp = ospath.join("/", upload_path, upload_name + ".tmp")

            self._logger.debug("Upload location: " + upload_file)

            # Check actual connection to the WebDAV server as the check command will not do this.
            if check_space:
                self._logger.debug("Attempting to check free space.")
                try:
                    # If the resource was not found
                    dav_free = davclient.free()
                    if dav_free < 0:
                        # If we get a negative free size, this server is not returning correct value.
                        check_space = False
                        self._logger.warning("Free space on server: " + _convert_size(dav_free) + ", it appears your server does not support reporting size correctly but it's still a proper way to check connectivity.")
                    else:
                        self._logger.info("Free space on server: " + _convert_size(dav_free))
                except RemoteResourceNotFound as exception:
                    self._logger.error("Resource was not found, something is probably wrong with your settings.")
                    return
                except ResponseErrorCode as exception:
                    # Write error and exit function
                    status = HTTPStatus(exception.code)
                    error_switcher = {
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
                    if (exception.code == 401):
                        http_error = "HTTP error 401 encountered, your credentials are most likely wrong."
                    else:
                        http_error = "HTTP error encountered: " + str(status.value) + " " + error_switcher.get(exception.code, status.phrase)
                    self._logger.error(http_error)
                    return
                except WebDavException as exception:
                    self._logger.error("An unexpected WebDAV error was encountered: " + exception.args)
                    raise
            else:
                self._logger.debug("Not checking free space, just try to check the WebDAV root.")
                # Not as proper of a check as retrieving size, but it's something.
                if davclient.check("/"):
                    self._logger.debug("Server returned WebDAV root.")
                else:
                    self._logger.error("Server did not return WebDAV root, something is probably wrong with your settings.")
                    return

            backup_size = ospath.getsize(backup_path)
            self._logger.info("Backup file size: " + _convert_size(backup_size))

            if check_space and (backup_size > dav_free):
                self._logger.error("Unable to upload, size is" + _convert_size(backup_size) + ", free space is " + _convert_size(dav_free))
                return
            else:
                # Helper function to recursively create paths
                def _recursive_create_path(path):
                    # Append leading / for preventing abspath issues
                    path = ospath.join("/", path)
                    if davclient.check(path):
                        self._logger.debug("Directory " + path + " was found.")
                        return True
                    else:
                        if path != "/":
                            self._logger.debug("Directory " + path + " was not found, checking parent.")
                            if _recursive_create_path(ospath.abspath(ospath.join(path, ".."))):
                                davclient.mkdir(path)
                                self._logger.debug("Directory " + path + " has been created.")
                                return True
                        else:
                            self._logger.error("Could not find WebDAV root, something is probably wrong with your settings.")
                            return False

                if _recursive_create_path(upload_path):
                    self._logger.debug("Uploading " + backup_path + " to " + upload_temp)
                    davclient.upload_sync(remote_path=upload_temp, local_path=backup_path)
                    self._logger.debug("Moving " + upload_temp + " to " + upload_file)
                    davclient.move(remote_path_from=upload_temp, remote_path_to=upload_file)
                    self._logger.info("Backup has been uploaded successfully to " + davoptions["webdav_hostname"] + " as " + upload_file)
                else:
                    self._logger.error("Something went wrong trying to check/create the upload path.")

    ##~~ TemplatePlugin mixin
    def get_template_configs(self):
        return [
            dict(
                type="settings", custom_bindings=False
            )
        ]

    ##~~ Softwareupdate hook
    def get_update_information(self):
        return dict(
            webdavbackup=dict(
                displayName="WebDAV Backup",
                displayVersion=self._plugin_version,

                type="github_release",
                user="edekeijzer",
                repo="OctoPrint-WebDavBackup",
                current=self._plugin_version,
				stable_branch=dict(
					name="Stable",
					branch="main",
					comittish=["main"]
				),
				prerelease_branches=[
					dict(
						name="Release Candidate",
						branch="rc",
						comittish=["rc", "main"]
					)
				],
                pip="https://github.com/edekeijzer/OctoPrint-WebDavBackup/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "WebDAV Backup"
__plugin_pythoncompat__ = ">=3,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = WebDavBackupPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }

