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
	

	def toggle_ap(self, state):
		"""Toggles a Wi-Fi Hotspot using settings from config.json."""
		cfg = self.load_config()
		ssid = cfg["wifi_ssid"]
		pw = cfg["wifi_pass"]

		if state:
			# 1. Clean up any existing 'Recovery' profile to avoid conflicts
			subprocess.run("nmcli con delete Recovery".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			
			# 2. Create the AP profile with 'shared' IPv4 method (Critical for AP mode)
			cmd_create = f"nmcli con add type wifi ifname wlan0 mode ap con-name Recovery ssid {ssid} autoconnect false"
			# Set security to WPA2
			cmd_sec = "nmcli con modify Recovery 802-11-wireless-security.key-mgmt wpa-psk"
			cmd_pw = f"nmcli con modify Recovery 802-11-wireless-security.psk {pw}"
			# Set the IP sharing (This is likely why it was failing)
			cmd_ip = "nmcli con modify Recovery ipv4.method shared"
			
			subprocess.run(cmd_create.split(), check=True)
			subprocess.run(cmd_sec.split(), check=True)
			subprocess.run(cmd_pw.split(), check=True)
			subprocess.run(cmd_ip.split(), check=True)
			
			# 3. Bring the connection up
			time.sleep(1) # Hardware cooldown
			subprocess.run("nmcli con up Recovery".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		else:
			subprocess.run("nmcli con down Recovery".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

	def is_ap_on(self):
		try:
			res = subprocess.check_output(["nmcli", "-t", "-f", "active,device", "con", "show"]).decode()
			return "yes:wlan0" in res or "yes:p2p-dev-wlan0" in res
		except:
			return False
		
	def load_config(self):
		"""Loads recovery and path settings from config file."""
		config_path = "assets/config.json"
		defaults = {
			"wifi_ssid": "MintP3-Recovery",
			"wifi_pass": "recovery123",
			"music_dir": "music/"
		}
		if os.path.exists(config_path):
			try:
				with open(config_path, 'r') as f:
					return {**defaults, **json.load(f)}
			except:
				return defaults
		return defaults

	def toggle_ap(self, state):
		"""Toggles a Wi-Fi Hotspot using settings from config.json."""
		cfg = self.load_config()
		ssid = cfg["wifi_ssid"]
		pw = cfg["wifi_pass"]

		if state:
			# Remove old profile if it exists to ensure settings update
			subprocess.run("nmcli con delete Recovery".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			
			cmd_create = f"nmcli con add type wifi ifname wlan0 mode ap con-name Recovery hotspot ssid {ssid} autoconnect false"
			cmd_set_pw = f"nmcli con modify Recovery 802-11-wireless-security.key-mgmt wpa-psk 802-11-wireless-security.psk {pw}"
			cmd_up = "nmcli con up Recovery"
			
			subprocess.run(cmd_create.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			subprocess.run(cmd_set_pw.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			subprocess.run(cmd_up.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
		else:
			subprocess.run("nmcli con down Recovery".split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)