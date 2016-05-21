# Tactical Battlefield Installer/Updater/Launcher
# Copyright (C) 2015 TacBF Installer Team.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

from __future__ import unicode_literals

import os
import textwrap
import zipfile

from kivy.logger import Logger
from third_party import SoftwareNotInstalled
from utils import browser
from utils import system_processes
from utils.admin import run_admin
from utils.devmode import devmode
from utils.registry import Registry


class TeamspeakNotInstalled(SoftwareNotInstalled):
    pass


def _parse_windows_cmdline(cmdline):
    """Parse command line from windows with its bizarre quoting mechanism."""

    import ctypes
    reload(ctypes)  # This fixes problems with ipython

    size = ctypes.c_int()
    ptr = ctypes.windll.shell32.CommandLineToArgvW(cmdline, ctypes.byref(size))
    ref = ctypes.c_wchar_p * size.value
    raw = ref.from_address(ptr)
    args = [arg for arg in raw]
    ctypes.windll.kernel32.LocalFree(ptr)

    return args


def get_executable_path():
    """Return the path of the teamspeak executable."""

    if devmode.get_ts_executable():
        return devmode.get_ts_executable()

    try:
        key = 'SOFTWARE\\classes\\ts3file\\shell\\open\\command'
        reg_val = Registry.ReadValueUserAndMachine(key, '', False)
        args = _parse_windows_cmdline(reg_val)

        return args[0]

    except Registry.Error:
        raise TeamspeakNotInstalled()

    except IndexError:
        raise


def get_addon_installer_path():
    """Return the path of the addon installer for teamspeak."""

    if devmode.get_ts_addon_installer():
        return devmode.get_ts_addon_installer()

    try:
        key = 'SOFTWARE\\Classes\\ts3addon\\shell\\open\\command'
        reg_val = Registry.ReadValueUserAndMachine(key, '', False)
        args = _parse_windows_cmdline(reg_val)

        return args[0]

    except Registry.Error:
        raise TeamspeakNotInstalled()

    except IndexError:
        raise


def get_install_location():
    """Return the path to where teamspeak executables are installed."""

    if devmode.get_ts_install_location():
        return devmode.get_ts_install_location()

    try:
        key = 'SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\TeamSpeak 3 Client'
        reg_val = Registry.ReadValueUserAndMachine(key, 'InstallLocation', True)
        return reg_val

    except Registry.Error:
        raise TeamspeakNotInstalled()


def get_config_location():
    """Return the value meaning where the user configuration is stored.
      0 - C:/Users/<username>/AppData/Roaming/TS3Client
      1 - Installation folder (get_install_location()/config).
    The actual directory may not exist until the user actually launches Teamspeak!
    """

    if devmode.get_ts_config_location():
        return devmode.get_ts_config_location()

    try:
        key = 'SOFTWARE\\TeamSpeak 3 Client'
        reg_val = Registry.ReadValueUserAndMachine(key, 'ConfigLocation', True)
        return reg_val

    except Registry.Error:
        raise TeamspeakNotInstalled()


def check_installed():
    """Run all the registry checks. If any of them fails, raises TeamspeakNotInstalled()."""

    executable_path = get_executable_path()
    addon_installer_path = get_addon_installer_path()
    install_location = get_install_location()
    config_location = get_config_location()

    Logger.debug('TS: executable path: {}'.format(executable_path))
    Logger.debug('TS: addon installer path: {}'.format(addon_installer_path))
    Logger.debug('TS: install location: {}'.format(install_location))
    Logger.debug('TS: config location: {}'.format(config_location))


def is_teamspeak_running():
    """Check if a TeamSpeak process is running."""

    ts3_path = get_executable_path()
    # May result in a false negative if you don't have the permission to access
    # the process
    if system_processes.file_running(ts3_path):
        return True

    if system_processes.program_running('ts3client_win32.exe'):
        return True

    if system_processes.program_running('ts3client_win64.exe'):
        return True

    return False


def run_and_connect(url):
    """Run the teamspeak client and connect to the given server."""

    full_url = 'ts3server://{}'.format(url)

    if is_teamspeak_running():
        Logger.info('TS: Teamspeak process found running. Assuming it is already connected to the correct server.')
        return

    Logger.info('TS: Connecting to teamspeak server: {}'.format(url))
    browser.open_hyperlink(full_url)


def create_package_ini_file_contents(path, name, author, version, platforms, description):
    """Create a package.ini file at <path> for a future ts3_plugin file."""
    package_ini = textwrap.dedent("""Name = {}
                                     Type = Plugin
                                     Author = {}
                                     Version = {}
                                     Platforms = {}
                                     Description = "{}"
    """).format(name, author, version, ', '.join(platforms), description)

    return package_ini


def create_teamspeak_package(path, name, author, version, platforms, description):
    """Create a teamspeak ts3_plugin file from files in <path>/plugins.
    The created file will be called tfr.ts3_plugin, will be a zip file and will
    contain the <path>/plugins directory and an autogenerated package.ini file.
    """

    ts3_plugin_path = os.path.join(path, 'tfr.ts3_plugin')

    package_ini_contents = create_package_ini_file_contents(
        path=path, name=name, author=author, version=version,
        platforms=platforms, description=description)

    zipf = zipfile.ZipFile(ts3_plugin_path, 'w')
    zipf.writestr('package.ini', package_ini_contents.encode('utf-8'))

    for root, _, files in os.walk(os.path.join(path, 'plugins')):
        for file_entry in files:
            file_path = os.path.join(root, file_entry)

            base_offset = len(path)
            if not path.endswith(os.path.sep):
                base_offset += 1

            # Strip the base path from the file path in the archive
            archive_path = file_path[base_offset:]

            # Note There is no official file name encoding for ZIP files.
            # If you have unicode file names, you must convert them to byte
            # strings in your desired encoding before passing them to write().
            # WinZip interprets all file names as encoded in CP437, also known
            # as DOS Latin.
            zipf.write(file_path, archive_path.encode('cp437'))

    zipf.close()

    return ts3_plugin_path


def install_unpackaged_plugin(path):
    """Package a plugin located at <path> to a ts3_plugin file and then install it.
    The created ts3_plugin file will be left in place because we cannot know when
    the installer terminates, yet.
    """

    version = 'Unknown'

    tfr_package = create_teamspeak_package(
        path,
        name='Task Force Arma 3 Radio',
        author='[TF]Nkey',
        version=version,
        platforms=['win32', 'win64'],
        description='Task Force Arrowhead Radio.\nPlugin packaged automatically by TacBF launcher team.'
    )

    args = [get_addon_installer_path(), '-silent', tfr_package]
    return run_admin(args[0], args[1:])
    # return subprocess.Popen(unicode_helpers.u_to_fs_list(args))


def copy_userconfig(path):
    """Copy and overwrite the files at <path> to the userconfig directory inside Arma 3 directory."""
    # TODO: Move this somewhere else
    import distutils.dir_util

    from third_party.arma import Arma

    Arma.get_installation_path()
    userconfig_path = os.path.join(Arma.get_installation_path(), 'userconfig')

    distutils.dir_util.copy_tree(path, userconfig_path)
