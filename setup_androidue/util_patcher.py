#!/usr/bin/python3

# Author: Bedran Karakoc <bedran.karakoc@softwareradiosystems.com>
# Author: Nils Fürste <nils.fuerste@softwareradiosystems.com>

import subprocess
import sys
import os
import netifaces
import time

from netifaces import AF_INET
from sys import platform
from shutil import which


class SetupUtils:
    def __init__(self):
        self.adb_bin_p = which('adb')
        if self.adb_bin_p is None:
            print('ADB not found !')
            sys.exit(1)

        # On some devices with active tethering it is only possible to connect
        # via ADB if it is started as root
        subprocess.Popen(['sudo', self.adb_bin_p, 'kill-server'])
        time.sleep(2)
        subprocess.Popen(['sudo', self.adb_bin_p, 'start-server'])
        time.sleep(4)

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

    def set_up_bridge(self, interfaces_l, bridge_name):
        # add bridge
        subprocess.Popen(['sudo', 'ip', 'link', 'add', 'name', str(bridge_name), 'type', 'bridge'])

        # add all interfaces to the bridge
        for intf in interfaces_l:
            subprocess.Popen(['sudo', 'ip', 'link', 'set', str(intf), 'master', str(bridge_name)])

        # set ip address of bridge
        subprocess.Popen(['sudo', 'ip', 'a', 'a', '192.168.42.1/24', 'dev', str(bridge_name)])

        # bring up bridge
        subprocess.Popen(['sudo', 'ip', 'link', 'set', str(bridge_name), 'up'])

    def get_device_serials(self):
        dev_serials_l = []
        adb_ret = setupUtils.run_adb_cmd('devices').split("\n")
        adb_ret.pop(0)  # remove first line
        for line in adb_ret:
            if line != '':
                dev_serials_l.append(line.replace("\tdevice", ""))
        return dev_serials_l

    def check_dropbearmulti(self, serial):
        return not ('not found' in self.run_adb_shell_cmd('dropbearmulti dropbear -V', True, serial))

    def push_dropbear_bin(self, serial):
        directory = sys.path[0]
        android_abi = self.run_adb_shell_cmd('getprop ro.product.cpu.abilist', False, serial)
        print("\nDetected Application Binary Interface (ABI): " + android_abi)
        print("\nCopying binary...")
        self.run_adb_shell_cmd('mount -o rw,remount /system', True, serial)
        time.sleep(2)
        self.run_adb_shell_cmd('mount -o rw,remount /', True, serial)
        time.sleep(2)

        os.popen('adb push ' + directory + '/dropbear/dropbearmulti ' + '/data/local/tmp')
        self.run_adb_shell_cmd('mv /data/local/tmp/dropbearmulti /system/bin', True, serial)
        self.run_adb_shell_cmd('chmod +x /system/bin/dropbearmulti', True, serial)

        if 'not found' in self.run_adb_shell_cmd('dropbearmulti dropbear -V', True, serial):
            print("Setting up DropbearMulti failed, please try again!")
        

    def set_usb_tethering(self, state, serial):
        # If a new version of vsc is running, we can toggle usb tethering through
        # this interface. Older versions do not have the rndis parameter.
        svc_return = self.run_adb_shell_cmd('svc usb', True, serial)
        if 'rndis' in svc_return:
            if state:
                # Activate USB tethering
                self.run_adb_shell_cmd('svc usb setFunctions rndis', True, serial)
            else:
                # We can use this to deactivate USB tethering. Removes the USB properties except for "charging" status
                self.run_adb_shell_cmd('svc usb setFunctions', True, serial)

            time.sleep(3)
            return

        # Use this workaround if we have no compatible vsc version on the device.
        # This dictionary maps the correct parcel payload to the corresponding android version
        # As reference see setUsbTethering method in
        # https://android.googlesource.com/platform/frameworks/base/+/master/core/java/android/net/IConnectivityManager.aidl
        connectivity_parcel_payload = {
            5: "service call connectivity 30 i32 " + str(state),
            6: "service call connectivity 30 i32 " + str(state),
            7: "service call connectivity 33 i32 " + str(state),
            8: "service call connectivity 33 i32 " + str(state),
            9: "service call connectivity 33 i32 " + str(state) + "s16 ogt",
            10: "service call connectivity 33 i32 " + str(state) + "s16 ogt",
        }
        android_ver = (self.get_android_ver(serial)).split(".", 1)[0]

        self.run_adb_shell_cmd(connectivity_parcel_payload.get(int(android_ver)), True, serial)
        time.sleep(3)

    def set_usb_tethering_ip(self, ip, serial):
        if not('rndis0' in self.run_adb_shell_cmd('ip link show', True, serial)):
            print('rndis0 interface not found, check if usb tethering is working.')
            return
        self.run_adb_shell_cmd('ip address add ' + ip + '/24 dev rndis0', True, serial)

    def run_dropbear_server_instance(self, port, pub_key=None, serial=None):
        # Kill all active dropbearmulti instances before starting a new one
        self.run_adb_shell_cmd('pkill -f dropbearmulti', True, serial)
        # Make filesystem writeable
        self.run_adb_shell_cmd('mount -o rw,remount /', True, serial)
        time.sleep(2)
        self.run_adb_shell_cmd('mount -o rw,remount /system', True, serial)
        time.sleep(2)
        if pub_key is not None:
            # Keep /data/local/tmp as location convention for keys. This directory is
            # accessible by everyone and avoids permission problems
            os.popen('adb push ' + pub_key + ' ' + '/data/local/tmp/')

        # Start the dropbearmulti SSH server. Do not modify the parameters!
        start_srv_cmd = 'dropbearmulti dropbear -R -p ' + str(port) \
                        + ' -T /data/local/tmp/authorized_keys -U 0 -G 0 -N root -A && sleep 3'
        self.run_adb_shell_cmd(start_srv_cmd, True, serial)

    def start_dropbear_ssh_server(self, serial, ssh_port):

        # start tethering
        self.set_usb_tethering(0, serial)
        time.sleep(2)
        self.set_usb_tethering(1, serial)
        time.sleep(1)

        # assign IP to Android UE
        ue_ip_addr = '192.168.42.' + str(ssh_port)
        self.set_usb_tethering_ip(ue_ip_addr, serial)

        # start ssh server
        pubkey = '/home/jenkins/.ssh/authorized_keys'
        self.run_dropbear_server_instance(ssh_port, pubkey, serial)
    
    def copy_authorized_keys(self, serial, custom_path=None):
        os.popen('adb push')


    def get_android_ver(self, serial):
        android_ver = self.run_adb_shell_cmd('getprop ro.build.version.release', False, serial)

        return android_ver

    def check_iperf3(self, serial):
        return not ("not found" in self.run_adb_shell_cmd('iperf3 -v', True, serial))

    def push_iperf3_bin(self, serial):
        directory = sys.path[0]
        android_abi = self.run_adb_shell_cmd('getprop ro.product.cpu.abilist', False, serial)
        print("\nDetected Application Binary Interface (ABI): " + android_abi)
        print("\nCopying binary...")
        self.make_iperf3_dirs(serial)

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

    def remount_partitions_writable(self, serial):
        self.run_adb_shell_cmd('mount -o rw,remount /system', True, serial)
        time.sleep(2)
        self.run_adb_shell_cmd('mount -o rw,remount /', True, serial)
        time.sleep(2)

    def make_iperf3_dirs(self, serial):
        self.run_adb_shell_cmd('mkdir /tmp', True, serial)
        self.run_adb_shell_cmd('chmod 777 /tmp', True, serial)

    def setup_ip_forwarding(self, ports_l, ssh_intf_n):
        # get list of tethering interfaces
        android_tethering_ip_prefix = '192.168.42.'
        interfaces_l = []

        # check if network interface is available
        if not (ssh_intf_n in netifaces.interfaces()):
            print("Interface %s not found!" % ssh_intf_n)
            sys.exit(1)

        # get IP of network interface
        try:
            ssh_server_ip = netifaces.ifaddresses(ssh_intf_n)[AF_INET][0]['addr']
        except KeyError:
            print("Interface %s has no IP address assigned!" % ssh_intf_n)
            sys.exit(1)

        # remove all adapters that don't have the Android tethering IP prefix
        for intf_name in netifaces.interfaces():
            addresses = netifaces.ifaddresses(intf_name)
            if netifaces.AF_INET in addresses:
                ipv4_addrs = addresses[netifaces.AF_INET]
                for ipv4_addr in ipv4_addrs:
                    if android_tethering_ip_prefix in ipv4_addr['addr']:
                        interfaces_l.append(intf_name)

        # set up bridge
        bridge_name = 'ogt'
        self.set_up_bridge(interfaces_l, bridge_name)

        # MASQUERADING
        masq_cmd = ['sudo', 'iptables', '-t', 'nat', '-A', 'POSTROUTING', '-o', str(bridge_name), '-j', 'MASQUERADE']
        subprocess.Popen(masq_cmd)

        # SNAT
        snat_cmd = ['sudo', 'iptables', '-t', 'nat', '-A', 'POSTROUTING', '!', '-d', '192.168.42.0/24',
                    '-o', str(ssh_intf_n), '-j', 'SNAT', '--to-source', str(ssh_server_ip)]
        subprocess.Popen(snat_cmd)

        # IP-Forwarding
        ip_fwd_cmd = ['echo', '1', '|', 'sudo', 'tee', '/proc/sys/net/ipv4/ip_forward']
        subprocess.Popen(ip_fwd_cmd)

        # add rules for port forwarding
        for port in ports_l:
            prer_fwd_cmd = ['sudo', 'iptables', '-A', 'PREROUTING', '-t', 'nat', '-i', str(ssh_intf_n), '-p', 'tcp',
                            '--dport', str(port), '-j', 'DNAT', '--to', '192.168.42.' + str(port) + ':' + str(port)]
            subprocess.Popen(prer_fwd_cmd)

            fwd_fwd_cmd = ['sudo', 'iptables', '-A', 'FORWARD', '-p', 'tcp', '-d', '192.168.42.' + str(port),
                           '--dport', str(port), '-j', 'ACCEPT']
            subprocess.Popen(fwd_fwd_cmd)

    def has_qualcomm_modem(self, serial):
        modem = self.run_adb_shell_cmd('getprop ro.board.platform', True, serial)
        if modem.startswith('msm') or modem.startswith('mdm') or modem.startswith('sdm'):
            return True
        else:
            return False

    def setup_diag_mdlog(self, serial):
        directory = sys.path[0]
        self.run_adb_shell_cmd('chmod 777 /dev/diag', True, serial)
        self.run_adb_shell_cmd('mkdir /data/local/tmp/diag_logs', True, serial)
        self.run_adb_shell_cmd('chmod 777 /data/local/tmp/diag_logs', True, serial)
        # Push config file containing logging masks for the diag interface
        os.popen('adb push ' + directory + '/ogt_diag.cfg ' + '/data/local/tmp/diag_logs/')




if __name__ == "__main__":
    # directory = sys.path[0]
    setupUtils = SetupUtils()
    ports_tb_forwarded = []  # Ports needed for IP forwarding on Secondary Unit

    # get device serials
    serials_l = setupUtils.get_device_serials()
    print("Available serials:", serials_l)

    # set up UEs
    while True:
        # ask for device to be configured
        ue_serial = input("Please enter a UE device serial or \'exit\' when you are done: ")
        if ue_serial == 'exit':
            break
        elif not (ue_serial in serials_l):
            print("Serial %s not available! Serials of connected devices:" % ue_serial)
            print(serials_l)
            print("\n\n")
            continue

        ## check dropbearmulti binary
        print("Checking DropbearMulti SSH ...")
        setupUtils.remount_partitions_writable(ue_serial)
        has_dropbearmulti_bin = False
        if not setupUtils.check_dropbearmulti(ue_serial):
            if 'yes' in input('DropbearMulti was not found. Do you want to install it on the UE? (yes/no): '):
                setupUtils.push_dropbear_bin(ue_serial)
                has_dropbearmulti_bin = True
                print("DropbearMulti SSH is ready to use")
        else:
            print("DropbearMulti SSH is ready to use")
            has_dropbearmulti_bin = True

        if has_dropbearmulti_bin:
            if 'yes' in input('Do you want to start tethering and the DropbearMulti SSH server? (yes/no): '):
                ue_ssh_port = int(input("Please specify the server's SSH port: "))
                ports_tb_forwarded.append(ue_ssh_port)  # save ports for IP forwarding setup
                print("Setting up SSH server. This may take a while...")

                setupUtils.start_dropbear_ssh_server(ue_serial, ue_ssh_port)
                print("DropbearMulti SSH server running")

        ## check iperf3 binary
        print("Checking iPerf3.9 ...")
        if not setupUtils.check_iperf3(ue_serial):
            if 'yes' in input('iPerf3.9 was not found. Do you want to install it on the UE? (yes/no): '):
                setupUtils.push_iperf3_bin(ue_serial)
        else:
            # make sure iPerf3 directories are available
            setupUtils.make_iperf3_dirs(ue_serial)
            print("iPerf3.9 is ready to use!")

        ## diag setup
        print("Checking if device has a Qualcomm baseband to support diag features")
        if setupUtils.has_qualcomm_modem(ue_serial):
            setupUtils.setup_diag_mdlog(ue_serial)

    ## setup IPTable rules on OGT Secondary Unit
    if 'yes' in input('Do you want to set up IPTables on OGT Secondary Unit? (yes/no): '):
        # get ssh interface name from user
        ssh_intf_name = input("Please specify the interface for SSH connections by OGT Main Unit: ")
        if 'yes' in input('Do you want to delete a previously created bridge if there is any? (yes/no)'):
            subprocess.Popen(['sudo', 'brctl', 'delbr', 'ogt'])
        # set up forwarding
        setupUtils.setup_ip_forwarding(ports_tb_forwarded, ssh_intf_name)
