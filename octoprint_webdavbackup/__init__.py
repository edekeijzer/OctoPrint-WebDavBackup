# coding=utf-8
from __future__ import absolute_import
from os import path as ospath
from os import remove as osremove
import math
import logging
from webdav3.client import Client
from webdav3.exceptions import WebDavException, ResponseErrorCode, RemoteResourceNotFound, RemoteParentNotFound
from fnmatch import fnmatch as fn
from datetime import datetime
from http import HTTPStatus
import octoprint.plugin
from octoprint.events import Events, eventManager
from octoprint.server import user_permission
from octoprint.settings import settings

class WebDavBackupPlugin(octoprint.plugin.SettingsPlugin,
                              octoprint.plugin.AssetPlugin,
                              octoprint.plugin.TemplatePlugin,
                              octoprint.plugin.EventHandlerPlugin,
):

    def __init__(self):
        self._logger = logging.getLogger(__name__)

    ##~~ SettingsPlugin mixin
    def get_settings_defaults(self):
        settings_defaults = dict(
            server=None,
            username=None,
            password=None,
            timeout=30,
            verify_certificate=True,
            upload_path="/",
            upload_name=None,
            check_space=False,
            skip_path_check=False,
            upload_timelapse_path=None,
            upload_timelapse_name=None,
            upload_timelapse_video=True,
            upload_timelapse_snapshots=False, # This will not be visible in settings
            upload_other=False,
            upload_other_path=None,
            upload_other_filter="*.gcode,*.stl",
            upload_other_overwrite=True,
            remove_after_upload=False,
        )
        return settings_defaults

    def get_settings_version(self):
        return 3

#    def on_settings_migrate(self, target, current):

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

    ##~~ EventHandlerPlugin mixin
    def on_event(self, event, payload):
        upload_timelapse_video = self._settings.get(["upload_timelapse_video"])
        upload_timelapse_snapshots = self._settings.get(["upload_timelapse_snapshots"])
        upload_other = self._settings.get(["upload_other"])
        remove_after_upload = self._settings.get(["remove_after_upload"])

        if event == "plugin_backup_backup_created" or (event == "MovieDone" and upload_timelapse_video) or (event == "CaptureDone" and upload_timelapse_snapshots) or (event == "FileAdded" and upload_other):
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
                'disable_check': self._settings.get(["disable_path_check"]),
            }

            # Set a safe default here
            upload_overwrite = False

            if event == "plugin_backup_backup_created":
                local_file_path = payload["path"]
                local_file_name = payload["name"]
                self._logger.info("Backup " + local_file_path + " created, will now attempt to upload to " + davoptions["webdav_hostname"])
                if self._settings.get(["upload_name"]):
                    upload_name = now.strftime(self._settings.get(["upload_name"])) + ospath.splitext(local_file_path)[-1]
                else:
                    upload_name = local_file_name
                upload_path = now.strftime(self._settings.get(["upload_path"]))

            elif event == "MovieDone":
                local_file_path = payload["movie"]
                local_file_name = payload["movie_basename"]
                self._logger.info("Timelapse movie " + local_file_path + " created, will now attempt to upload to " + davoptions["webdav_hostname"])
                if self._settings.get(["upload_timelapse_name"]):
                    upload_name = now.strftime(self._settings.get(["upload_timelapse_name"])) + local_file_name
                else:
                    upload_name = local_file_name
                if self._settings.get(["upload_timelapse_path"]):
                    upload_path = now.strftime(self._settings.get(["upload_timelapse_path"]))
                else:
                    # If no specific path is set for timelapses, upload them to the same directory as the backups
                    upload_path = now.strftime(self._settings.get(["upload_path"]))

            elif event == "CaptureDone":
                # Removing snapshots makes it hard to create a timelapse
                remove_after_upload = False

                local_file_path = payload["file"]
                local_file_name = ospath.split(local_file_path)[1]
                self._logger.info("Timelapse snapshot " + local_file_path + " created, will now attempt to upload to " + davoptions["webdav_hostname"] + " as " + local_file_name)
                if self._settings.get(["upload_timelapse_name"]):
                    upload_name = now.strftime(self._settings.get(["upload_timelapse_name"])) + local_file_name
                else:
                    upload_name = local_file_name
                if self._settings.get(["upload_timelapse_path"]):
                    upload_path = now.strftime(self._settings.get(["upload_timelapse_path"]))
                else:
                    # If no specific path is set for timelapses, upload them to the same directory as the backups
                    upload_path = now.strftime(self._settings.get(["upload_path"]))

            elif event == "FileAdded":
                # Removing random files is undesired behavior
                remove_after_upload = False

                upload_overwrite = self._settings.get(["upload_other_overwrite"])

                local_file_storage = payload["storage"]
                local_file_path = payload["path"]
                local_file_name = payload["name"]
                local_file_type = payload["type"]
                _local_storage = self._settings.getBaseFolder("uploads")
                self._logger.debug(f"Upload folder: {_local_storage}")

                if self._settings.get(["upload_other_filter"]):
                    other_file_filter = self._settings.get(["upload_other_filter"]).lower().split(',')
                else:
                    # If no specific path is set for timelapses, upload them to the same directory as the backups
                    other_file_filter = ["*.gcode","*.stl"]

                _file_match = False
                for pattern in other_file_filter:
                    if fn(ospath.join('/', local_file_path.lower()), ospath.join('/', pattern.strip())):
                        self._logger.info("Local file " + local_file_path + " matches " + pattern + ", will upload")
                        _file_match = True
                        break
                    else:
                        self._logger.debug("Local file " + local_file_path + " doesn't match " + pattern)

                if not _file_match:
                    self._logger.info("Local file " + local_file_path + " does not match any pattern, will NOT upload")
                    return

                if self._settings.get(["upload_other_path"]):
                    upload_path = now.strftime(self._settings.get(["upload_other_path"]))
                else:
                    # If no specific path is set for timelapses, upload them to the same directory as the backups
                    upload_path = now.strftime(self._settings.get(["upload_path"]))

                if self._settings.get(["upload_other_full_path"]):
                    upload_path = ospath.join(upload_path, ospath.dirname(local_file_path))
                upload_name = local_file_name
                self._logger.debug("File " + local_file_path + " was created on storage " + local_file_storage + ", will upload to " + ospath.join(upload_path, upload_name))
                local_file_path = ospath.join(_local_storage, local_file_path)
                self._logger.debug(local_file_type)

            davclient = Client(davoptions)
            davclient.verify = self._settings.get(["verify_certificate"])
            check_space = self._settings.get(["check_space"])
            skip_path_check = self._settings.get(["disable_path_check"])
            upload_path = ospath.join("/", upload_path)

            self._logger.debug("Filename for upload: " + upload_name)

            upload_file = ospath.join("/", upload_path, upload_name)
            upload_temp = ospath.join("/", upload_file + ".tmp")

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
                        self._logger.warning("Free space on server: " + str(dav_free) + ", it appears your server does not support reporting size correctly but it's still a proper way to check connectivity.")
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
            elif not skip_path_check:
                self._logger.debug("Not checking free space, just try to check the WebDAV root.")
                # Not as proper of a check as retrieving size, but it's something.
                if davclient.check("/"):
                    self._logger.debug("Server returned WebDAV root.")
                else:
                    self._logger.error("Server did not return WebDAV root, something is probably wrong with your settings.")
                    return
            else:
                self._logger.warning("All checks for successful connection are disabled.")

            try:
                local_file_size = ospath.getsize(local_file_path)
                self._logger.info("File size: " + _convert_size(local_file_size))
            except FileNotFoundError:
                self._logger.warning(f"File {local_file_path} not found, this is a known issue when moving a file.")
                return

            if check_space and (local_file_size > dav_free):
                self._logger.error("Unable to upload, size is" + _convert_size(local_file_size) + ", free space is " + _convert_size(dav_free))
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
                    try:
                        self._logger.debug("Uploading " + local_file_path + " to " + upload_temp)
                        davclient.upload_sync(remote_path=upload_temp, local_path=local_file_path)
                        self._logger.debug("Moving " + upload_temp + " to " + upload_file)
                        davclient.move(remote_path_from=upload_temp, remote_path_to=upload_file, overwrite=upload_overwrite)
                        self._logger.info("File has been uploaded successfully to " + davoptions["webdav_hostname"] + " as " + upload_file)

                        if remove_after_upload:
                            self._logger.debug("Removing local file after successful upload has been enabled.")
                            osremove(local_file_path)
                    except RemoteParentNotFound:
                        self._logger.error("The specified parent directory was not found, unable to upload.")
                    except:
                        if skip_path_check:
                            self._logger.error("Something went wrong uploading the file. Since you disabled the path check, this could anything, like incorrect credentials or a non-existing directory.")
                        elif remove_after_upload:
                            self._logger.error("Something went wrong uploading the file. (local file not removed)")
                        else:
                            self._logger.error("Something went wrong uploading the file.")
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
                        name="Development",
                        branch="dev",
                        comittish=["dev", "main"]
                    ),
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

