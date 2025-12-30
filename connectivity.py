import subprocess
import time
import json
import os

class ConnectivityManager:
    DATA_FILE = "assets/connection_data.json"

    def __init__(self):
        self.paired_name = "None"
        self.paired_mac = None
        self.load_data()

    def load_data(self):
        if os.path.exists(self.DATA_FILE):
            try:
                with open(self.DATA_FILE, 'r') as f:
                    data = json.load(f)
                    self.paired_name = data.get("bt_name", "None")
                    self.paired_mac = data.get("bt_mac", None)
            except: pass

    def save_data(self):
        os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
        with open(self.DATA_FILE, 'w') as f:
            json.dump({"bt_name": self.paired_name, "bt_mac": self.paired_mac}, f)

    def toggle_bluetooth(self, state):
        cmd = "bluetoothctl power on" if state else "bluetoothctl power off"
        subprocess.run(cmd.split(), stdout=subprocess.DEVNULL)

    def toggle_wifi(self, state):
        cmd = "nmcli radio wifi on" if state else "nmcli radio wifi off"
        subprocess.run(cmd.split(), stdout=subprocess.DEVNULL)

    def is_wifi_on(self):
        try:
            res = subprocess.check_output(["nmcli", "radio", "wifi"]).decode().strip()
            return res == "enabled"
        except: return False

    def get_current_wifi(self):
        """Returns the SSID of the currently connected network."""
        try:
            res = subprocess.check_output(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"]).decode()
            for line in res.split('\n'):
                if line.startswith("yes:"):
                    return line.split(':')[1]
            return "Not Connected"
        except: return "Error"

    def is_bt_on(self):
        try:
            res = subprocess.check_output(["bluetoothctl", "show"]).decode()
            return "Powered: yes" in res
        except: return False

    def discover_devices(self):
        devices = []
        try:
            subprocess.run(["bluetoothctl", "power", "on"], stdout=subprocess.DEVNULL)
            scan_proc = subprocess.Popen(["bluetoothctl", "scan", "on"], stdout=subprocess.DEVNULL)
            time.sleep(5) 
            scan_proc.terminate()
            out = subprocess.check_output(["bluetoothctl", "devices"]).decode()
            for line in out.strip().split('\n'):
                if "Device" in line:
                    parts = line.split(' ', 2)
                    if len(parts) >= 3:
                        devices.append({"mac": parts[1], "name": parts[2]})
        except Exception as e:
            print(f"Discovery error: {e}")
        return devices

    def pair_device(self, mac, name):
        try:
            subprocess.run(["bluetoothctl", "pair", mac], timeout=10, stdout=subprocess.DEVNULL)
            subprocess.run(["bluetoothctl", "trust", mac], stdout=subprocess.DEVNULL)
            subprocess.run(["bluetoothctl", "connect", mac], timeout=10, stdout=subprocess.DEVNULL)
            self.paired_mac = mac
            self.paired_name = name
            self.save_data()
            return True
        except:
            return False

    def repair_existing(self):
        if self.paired_mac:
            try:
                subprocess.run(["bluetoothctl", "connect", self.paired_mac], timeout=10, stdout=subprocess.DEVNULL)
                return True
            except: return False
        return False