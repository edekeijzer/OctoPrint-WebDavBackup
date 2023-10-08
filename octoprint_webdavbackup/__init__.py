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
from random import randint
import octoprint.plugin
from octoprint.events import Events, eventManager
from octoprint.server import user_permission
from octoprint.settings import settings
from random import choice
from string import ascii_letters, digits

class WebDavBackupPlugin(
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SimpleApiPlugin,
):

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self.davclient = None

    def update_dav_client(self):
        davoptions = {
            'webdav_hostname': self._settings.get(["server"]),
            'webdav_login': self._settings.get(["username"]),
            'webdav_password': self._settings.get(["password"]),
            'webdav_timeout': self._settings.get(["timeout"]),
            'disable_check': self._settings.get(["disable_path_check"]),
            # 'webdav_override_methods': {
            #     'check': 'GET',
            # },
        }
        self.davclient = Client(davoptions)
        self.davclient.verify = self._settings.get(["verify_certificate"])
        self.check_space = self._settings.get(["check_space"])
        self.skip_path_check = self._settings.get(["disable_path_check"])

    # Helper function to recursively create paths
    def create_dav_path(self, path):
        # Append leading / for preventing abspath issues
        path = ospath.join("/", path)
        if self.davclient.check(path):
            self._logger.debug(f"Directory {path} was found.")
            return True
        else:
            if path != "/":
                self._logger.debug(f"Directory {path} was not found, checking parent.")
                if self.create_dav_path(ospath.abspath(ospath.join(path, ".."))):
                    self.davclient.mkdir(path)
                    self._logger.debug(f"Directory {path} has been created.")
                    return True
            else:
                self._logger.error("Could not find WebDAV root, something is probably wrong with your settings.")
                return False

    # Helper function to test connectivity
    def test_dav_connection(self):
        now = datetime.now()
        great_success = True

        dummy_string = ''.join(choice(ascii_letters + digits) for i in range(12))
        dummy_path = ospath.join('/', 'tmp', dummy_string)
        upload_path = now.strftime(self._settings.get(["upload_path"]))
        upload_file = ospath.join('/', upload_path, dummy_string)
        self._logger.info(f"Dummy file {dummy_path} to {upload_file}")

        if not self.skip_path_check:
            try:
                if self.davclient.check("/"):
                    self._logger.debug("Server returned WebDAV root, will now upload dummy file.")
                    self.create_dav_path(upload_path)
                else:
                    error_message = "Server did not return WebDAV root, something is probably wrong with your settings."
                    self._logger.error(error_message)
                    great_success = False
            except RemoteResourceNotFound as exception:
                error_message = "Resource was not found, something is probably wrong with your settings."
                self._logger.error(error_message)
                great_success = False
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
                    error_message = "HTTP error 401 encountered, your credentials are most likely wrong."
                else:
                    error_message = f"HTTP error encountered: {str(status.value)} {error_switcher.get(exception.code, status.phrase)}"
                self._logger.error(error_message)
                great_success = False
            except WebDavException as exception:
                self._logger.error(f"An unexpected WebDAV error was encountered: {exception.args}")
                raise
        else:
            self._logger.warning("All checks for successful connection are disabled, will just try to upload a dummy file.")

        if great_success:
            try:
                with open(dummy_path, "w") as dummy_file:
                    dummy_file.write(dummy_string)
                self.davclient.upload_sync(remote_path=upload_file, local_path=dummy_path)
                self.davclient.clean(upload_file)
                osremove(dummy_path)
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
                    error_message = "HTTP error 401 encountered, your credentials are most likely wrong."
                else:
                    error_message = f"HTTP error encountered: {str(status.value)} {error_switcher.get(exception.code, status.phrase)}"
                self._logger.error(error_message)
                great_success = False
            except WebDavException as exception:
                error_message = f"An unexpected WebDAV error was encountered: {exception.args}"
                self._logger.error(error_message)
                great_success = False
        response = dict(success=great_success)
        if not great_success:
            response['error'] = error_message
        return response

    def get_dav_space(self):
        self._logger.debug("Attempting to check free space.")
        try:
            # If the resource was not found
            dav_free = self.davclient.free()
            if dav_free < 0:
                self._logger.warning(f"Free space on server: {str(dav_free)}, it appears your server does not support reporting size correctly but it's still a proper way to check connectivity.")
            else:
                self._logger.info(f"Free space on server: {self.convert_size(dav_free)}")
            return dav_free
        except RemoteResourceNotFound as exception:
            self._logger.error("Resource was not found, something is probably wrong with your settings.")
            return False
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
                http_error = f"HTTP error encountered: {str(status.value)} {error_switcher.get(exception.code, status.phrase)}"
            self._logger.error(http_error)
            return False
        except WebDavException as exception:
            self._logger.error(f"An unexpected WebDAV error was encountered: {exception.args}")
            raise

    # Helper function for human readable sizes
    def convert_size(self, size_bytes):
        if size_bytes == 0:
            return "0B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return "%s %s" % (s, size_name[i])

    ##~~ StartupPlugin mixin
    # def on_startup(self):
    #     pass

    def on_after_startup(self):
        self._logger.info("Initializing WebDAV client")
        self.update_dav_client()

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

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self.update_dav_client()

    def on_settings_migrate(self, target, current):
        pass

    ##~~ EventHandlerPlugin mixin
    def on_event(self, event, payload):
        upload_timelapse_video = self._settings.get(["upload_timelapse_video"])
        upload_timelapse_snapshots = self._settings.get(["upload_timelapse_snapshots"])
        upload_other = self._settings.get(["upload_other"])
        remove_after_upload = self._settings.get(["remove_after_upload"])

        if event == "plugin_backup_backup_created" or (event == "MovieDone" and upload_timelapse_video) or (event == "CaptureDone" and upload_timelapse_snapshots) or (event == "FileAdded" and upload_other):
            if not self.test_dav_connection():
                return False
            now = datetime.now()
            check_space = self.check_space
            # Set a safe default here
            upload_overwrite = False

            if event == "plugin_backup_backup_created":
                local_file_path = payload["path"]
                local_file_name = payload["name"]
                self._logger.info(f"Backup {local_file_path} created, will now attempt to upload")
                if self._settings.get(["upload_name"]):
                    upload_name = now.strftime(self._settings.get(["upload_name"])) + ospath.splitext(local_file_path)[-1]
                else:
                    upload_name = local_file_name
                upload_path = now.strftime(self._settings.get(["upload_path"]))

            elif event == "MovieDone":
                local_file_path = payload["movie"]
                local_file_name = payload["movie_basename"]
                self._logger.info(f"Timelapse movie {local_file_path} created, will now attempt to upload")
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
                self._logger.info(f"Timelapse snapshot {local_file_path} created, will now attempt to upload as {local_file_name}")
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
                        self._logger.info(f"Local file {local_file_path} matches {pattern}, will upload")
                        _file_match = True
                        break
                    else:
                        self._logger.debug(f"Local file {local_file_path} doesn't match {pattern}")

                if not _file_match:
                    self._logger.info(f"Local file {local_file_path} does not match any pattern, will NOT upload")
                    return

                if self._settings.get(["upload_other_path"]):
                    upload_path = now.strftime(self._settings.get(["upload_other_path"]))
                else:
                    # If no specific path is set for timelapses, upload them to the same directory as the backups
                    upload_path = now.strftime(self._settings.get(["upload_path"]))

                if self._settings.get(["upload_other_full_path"]):
                    upload_path = ospath.join(upload_path, ospath.dirname(local_file_path))
                upload_name = local_file_name
                self._logger.debug(f"File {local_file_path} was created on storage {local_file_storage}, will upload to {ospath.join(upload_path, upload_name)}")
                local_file_path = ospath.join(_local_storage, local_file_path)
                self._logger.debug(local_file_type)

            upload_path = ospath.join("/", upload_path)

            self._logger.debug(f"Filename for upload: {upload_name}")

            upload_file = ospath.join("/", upload_path, upload_name)
            upload_temp = ospath.join("/", f"{upload_file}.tmp")

            self._logger.debug(f"Upload location: {upload_file}")

            if check_space:
                dav_free = self.get_dav_space()
                check_space = type(dav_free) is int and dav_free > 0

            try:
                local_file_size = ospath.getsize(local_file_path)
                self._logger.info(f"File size: {self.convert_size(local_file_size)}")
            except FileNotFoundError:
                self._logger.warning(f"File {local_file_path} not found, this is a known issue when moving a file.")
                return False

            if check_space and (local_file_size > dav_free):
                self._logger.error(f"Unable to upload, size is {self.convert_size(local_file_size)}, free space is {self.convert_size(dav_free)}")
                return False
            else:
                if self.create_dav_path(upload_path):
                    try:
                        self._logger.debug(f"Uploading {local_file_path} to {upload_temp}")
                        self.davclient.upload_sync(remote_path=upload_temp, local_path=local_file_path)
                        self._logger.debug(f"Moving {upload_temp} to {upload_file}")
                        self.davclient.move(remote_path_from=upload_temp, remote_path_to=upload_file, overwrite=upload_overwrite)
                        self._logger.info(f"File has been uploaded successfully to {dav_server} as {upload_file}")

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
                type="settings", custom_bindings=True
            )
        ]

    ##~~ SimpleApiPlugin mixin
    def get_api_commands(self):
        return dict(
            test_connection=[]
        )

    def on_api_command(self, command, data):
        self._logger.info(f"Received API command: {command}")
        if command == "test_connection":
            test_result = self.test_dav_connection()
            self._logger.debug(test_result)
            response = dict(success=test_result['success'])
            if test_result['success']:
                dav_free = self.get_dav_space()
                response['free_space'] = dav_free
                if type(dav_free) is int and dav_free > 0:
                    response['message'] = self.convert_size(dav_free)
                else:
                    response['message'] = "Unable to determine free space"
            elif test_result['error']:
                response['message'] = test_result['error']
            else:
                response['message'] = "Unknown error"
            return response

    ##~~ AssetPlugin mixin
    def get_assets(self):
        return dict(js=["js/WebDavBackup.js"])

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