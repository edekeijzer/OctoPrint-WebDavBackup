# WebDAV Backup

This plugin will automatically upload a backup upon completion to your WebDAV storage, like Nextcloud.

## Prerequisites

### OctoPrint 1.5.0
At least version 1.5.0 of OctoPrint is required because of event support in the backup plugin.

### WebDAV storage
You need a working WebDAV storage solution to upload your back-ups to. I have tested this against Nextcloud 17.

### Python 3
This plugin is **not compatible** with Python 2.7. See [this blog post](https://octoprint.org/blog/2020/09/10/upgrade-to-py3/) on how to upgrade your OctoPi installation.

### libxml2-dev and libxslt1-dev (Raspberry Pi)
For Raspberry Pi (ARM architecture) there is no pre-built package available for _lxml_, a dependency of the WebDAV library used in this plugin. To install this, it has to be built from source.
To be able to do this, you will need the libxml2 and libxslt1 development packages, which can be installed on Debian based operating systems with the following command: _apt-get install libxml2-dev libxslt1-dev_
For AMD64, a pre-built package is available, so these packages do not have to be installed.

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/edekeijzer/OctoPrint-WebDavBackup/archive/main.zip

## To-Do

- [X] ~~Develop this plugin~~
- [X] ~~Customizable filenames~~
- [X] ~~Create folders per year and/or month~~
- [ ] Improve error handling, display messages in UI
- [ ] Implement a connection test button

## Get Help

If you experience issues with this plugin or need assistance please use the issue tracker by clicking issues above.