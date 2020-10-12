# coding=utf-8
from __future__ import absolute_import

import os
import logging
from webdav3.client import Client
import octoprint.plugin
from octoprint.events import Events, eventManager
from octoprint.server import user_permission
from octoprint.settings import settings

SETTINGS_DEFAULTS = dict(
    server=None,
    username=None,
    password=None,
    timeout=30,
    verify_certificate=True,
    upload_path="/"
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
            upload_path = self._settings.get(["upload_path"])
            upload_file = os.path.join(upload_path, backup_name)
            upload_temp = os.path.join(upload_path, backup_name + ".tmp")

            if davclient.check(upload_path):
                self._logger.info("Upload path " + upload_path + " was found.")
            else:
                self._logger.info("Upload path " + upload_path + " was not found, attempting to create.")
                davclient.mkdir(upload_path)

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

    ##~~ Softwareupdate hook
    def get_update_information(self):
        return dict(
            webdavbackup=dict(
                displayName="WebDAV Backup",
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="edekeijzer",
                repo="OctoPrint-WebDavBackup",
                current=self._plugin_version,
                stable_branch=dict(
                    name="Stable",
                    branch="master",
                    comittish=["master"]
                ),
                prerelease_branches=[
                    dict(
                        name="Release Candidate",
                        branch="rc",
                        comittish=["rc", "master"]
                    )
                ],
                # update method: pip
                pip="https://github.com/edekeijzer/OctoPrint-WebDavBackup/archive/{target_version}.zip"
            )
        )

__plugin_name__ = "WebDAV Backup"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = WebDavBackupPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }

