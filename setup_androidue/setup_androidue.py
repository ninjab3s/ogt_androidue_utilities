#!/usr/bin/python3
# setup_androidue: Setup script to prepare rooted Android devices for testing
#
# Copyright (C) 2020 by Software Radio Systems Limited
#
# Author: Bedran Karakoc <bedran.karakoc@softwareradiosystems.com>
# Author: Nils Fürste <nils.fuerste@softwareradiosystems.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import subprocess
import sys
import os
import time
from shutil import which


class SetupUtils:
    def __init__(self):
        self.adb_bin_p = which('adb')
        if self.adb_bin_p is None:
            print('ADB not found !')
            sys.exit(1)

    def run_adb_cmd(self, command, serial=None):
        try:
            adb_cmd = [self.adb_bin_p, command]
            if serial:
                adb_cmd.insert(-1, serial)
                adb_cmd.insert(-2, '-s')
            process = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as err:
            print("Error executing ADB command: " + err.output)
            return None

        return process.stdout.read().decode('utf-8')

    def run_adb_shell_cmd(self, command, run_root, serial):
        adb_cmd = [self.adb_bin_p, '-s', serial, 'exec-out', command]
        if run_root:
            adb_cmd.insert(-1, '-c')
            adb_cmd.insert(-2, 'su')

        try:
            process = subprocess.Popen(adb_cmd, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as err:
            print(err)
            return None

        return process.stdout.read().decode('utf-8')

    def get_device_serials(self):
        dev_serials_l = []
        adb_ret = setupUtils.run_adb_cmd('devices').split("\n")
        adb_ret.pop(0)  # remove first line
        for line in adb_ret:
            if line != '':
                dev_serials_l.append(line.replace("\tdevice", ""))
        return dev_serials_l

    def install_iperf3_bin(self, serial):
        directory = sys.path[0]
        android_abi = self.run_adb_shell_cmd('getprop ro.product.cpu.abilist', False, serial)

        # make sure tmp dir exists and is writeable
        self.run_adb_shell_cmd('mkdir /tmp', True, serial)
        self.run_adb_shell_cmd('chmod 777 /tmp', True, serial)

        if 'arm64-v8a' in android_abi:
            os.popen('adb push ' + directory + '/iperf3/arm64-v8a/iperf3.9 ' + '/data/local/tmp')
            self.run_adb_shell_cmd('cp /data/local/tmp/iperf3.9 /system/bin', True, serial)
            self.run_adb_shell_cmd('chmod +x /system/bin/iperf3.9', True, serial)
            print(self.run_adb_shell_cmd('iperf3.9 -v', True, serial))
        elif 'armeabi-v7a' in android_abi:
            os.popen('adb push ' + directory + '/iperf3/armeabi-v7a/iperf3.9 ' + '/data/local/tmp')
            self.run_adb_shell_cmd('cp /data/local/tmp/iperf3.9 /system/bin', True, serial)
            self.run_adb_shell_cmd('chmod +x /system/bin/iperf3.9', True, serial)
            print(self.run_adb_shell_cmd('iperf3.9 -v', True, serial))
        else:
            print('Architecture %s not supported by iperf3' % android_abi)

    def install_dropbearmulti(self, serial):
        directory = sys.path[0]

        # ensure system is writeable
        self.run_adb_shell_cmd('mount -o rw,remount /', True, serial)
        time.sleep(2)
        self.run_adb_shell_cmd('mount -o rw,remount /system', True, serial)
        time.sleep(2)

        # push dropbear host key and authorized_keys file
        os.popen('adb push /data/local/tmp/dropbear_ecdsa_host_key /data/local/tmp/')
        os.popen('adb push /data/local/tmp/authorized_keys /data/local/tmp/')

        # push dropbearmulti binary and symlink
        self.run_adb_shell_cmd('pkill -f dropbearmulti', True, serial)
        os.popen('adb push ' + directory + '/dropbear/dropbearmulti ' + '/data/local/tmp')
        self.run_adb_shell_cmd('chmod +x /data/local/tmp/dropbearmulti', True, serial)
        self.run_adb_shell_cmd('ln -s /data/local/tmp/dropbearmulti /system/bin/dropbearmulti', True, serial)

        if not 'dropbear' in self.run_adb_shell_cmd('dropbearmulti', True, serial):
            print("Setting up DropbearMulti failed, please try again!")

    def install_diag_mdlog_cfg(self, serial):
        directory = sys.path[0]
        self.run_adb_shell_cmd('chmod 777 /dev/diag', True, serial)
        self.run_adb_shell_cmd('mkdir /data/local/tmp/diag_logs', True, serial)
        self.run_adb_shell_cmd('chmod 777 /data/local/tmp/diag_logs', True, serial)
        # Push config file containing logging masks for the diag interface
        os.popen('adb push ' + directory + '/ogt_diag.cfg ' + '/data/local/tmp/diag_logs/')

    def start_adb_forwarding(self, serial, port):
        self.run_adb_cmd('forward tcp:%s tcp:%s' % (port, port), serial)

    def start_dropbear_server(self, port, serial):
        # Kill all active dropbearmulti instances before starting a new one
        self.run_adb_shell_cmd('pkill -f dropbearmulti', True, serial)

        self.run_adb_cmd('exec-out su -c "pkill -f dropbearmulti', serial)
        self.run_adb_shell_cmd('dropbearmulti dropbear -R '
                               '-p %s '
                               '-T /data/local/tmp/authorized_keys '
                               '-r /data/local/tmp/dropbear_ecdsa_host_key '
                               '-U 0 -G 0 -N root -A'
                               % port,
                               True,
                               serial
                               )

    def has_qualcomm_modem(self, serial):
        modem = self.run_adb_shell_cmd('getprop ro.board.platform', True, serial)
        return modem.startswith('msm') or modem.startswith('mdm') or modem.startswith('sdm')


if __name__ == "__main__":
    setupUtils = SetupUtils()

    while True:
        # get device serials
        serials_l = setupUtils.get_device_serials()
        print("Available serials:", serials_l)
        print('Syntax: install SERIAL, ssh SERIAL, start_adb')

        try:
            cmd, ue_serial = input('').split(' ')
        except ValueError:
            print('invalid command')
            print('\n\n')
            continue

        # install ue
        if cmd == 'install':
            if ue_serial not in serials_l:
                print('Serial %s not available in %s' % (ue_serial, serials_l))
                print("\n\n")
                continue

            setupUtils.install_dropbearmulti(ue_serial)
            print('DropbearMulti SSH is ready to use')

            setupUtils.install_iperf3_bin(ue_serial)
            print("iPerf3 is ready to use")

            if setupUtils.has_qualcomm_modem(ue_serial):
                setupUtils.install_diag_mdlog_cfg(ue_serial)
                print('diag_mdlog is ready to use!')
            else:
                print('diag_mdlog not available')

        # set up ue
        if cmd == 'ssh':
            if ue_serial not in serials_l:
                print('Serial %s not available in %s' % (ue_serial, serials_l))
                print("\n\n")
                continue

            ssh_port = int(input('Enter the port for the ssh server: '))
            setupUtils.start_adb_forwarding(ue_serial, ssh_port)
            setupUtils.start_dropbear_server(ue_serial, ssh_port)

        if cmd == 'start_adb':
            if 'y' == input('After starting/restarting ADB you need to set up all forwarding rules again. Continiue? (y/n)'):
                setupUtils.run_adb_cmd('kill-server')
                os.popen('sudo adb -a nodaemon server start &')
                # make sure adb server is started
                time.sleep(5)

        if cmd == 'exit':
            sys.exit(0)

