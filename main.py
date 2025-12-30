#!/usr/bin/env python

# mintp3 - software for a portable handheld digital audio player contained in an altoids tin powered by a raspberry pi.
# designed and edited by directive0 - written by Gemini ----------------------------------------------------- 2025/2026
# this script uses python-vlc to load a directory of audio files, and organize for playback.
# output is provided via a uc1701x monochrome LCD display and a USB digital to analog converter.
# playback is controlled via 4 momentary switch buttons connected to the GPIOs


import time
import os
import socket
import subprocess
import RPi.GPIO as GPIO
from luma.core.interface.serial import spi
from luma.lcd.device import uc1701x
from luma.core.render import canvas
from vlcplayer import VLCPlayer
from input import button_thread
from connectivity import ConnectivityManager
from threading import Thread
from globals import globals as glob 
from webui import Mp3PlayerWebUI
from PIL import ImageFont
import evdev
from evdev import ecodes

# Attempt to import psutil for richer metrics; fallback to shell if missing
try:
    import psutil
except ImportError:
    psutil = None

# Load fonts
try:
	titlefont = ImageFont.truetype("assets/chicago.ttf", 12)
	font = ImageFont.truetype("assets/font2.ttf", 10)
except:
	titlefont = ImageFont.load_default()
	font = ImageFont.load_default()

screen_w = 128
screen_h = 64

# --- BT HEADSET HANDLER ---
def bt_headset_thread(player, conn):
    last_device_path = None
    while True:
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            headset = None
            target_name = conn.paired_name
            if target_name and target_name != "None":
                for d in devices:
                    if target_name in d.name:
                        headset = d
                        break
            if not headset:
                for d in devices:
                    if "AVRCP" in d.name or "Control" in d.name:
                        headset = d
                        break
            if headset:
                if headset.path != last_device_path:
                    last_device_path = headset.path
                for event in headset.read_loop():
                    if event.type == ecodes.EV_KEY and event.value == 1:
                        if event.code in [ecodes.KEY_PLAYPAUSE, ecodes.KEY_PLAY, ecodes.KEY_PAUSE, ecodes.KEY_PLAYCD, ecodes.KEY_PAUSECD]:
                            player.toggle_play()
                        elif event.code == ecodes.KEY_NEXTSONG:
                            player.next_track()
                        elif event.code == ecodes.KEY_PREVIOUSSONG:
                            player.previous_track()
                        elif event.code == ecodes.KEY_VOLUMEUP:
                            player.set_volume(min(100, player.get_volume() + 5))
                        elif event.code == ecodes.KEY_VOLUMEDOWN:
                            player.set_volume(max(0, player.get_volume() - 5))
            else:
                last_device_path = None
                time.sleep(5)
        except (OSError, Exception):
            last_device_path = None
            time.sleep(5)

# Start input monitor
input_thread = Thread(target=button_thread, args=())
input_thread.daemon = True
input_thread.start()

class LabelObj(object):
	def __init__(self, string, font, draw):
		self.font = font
		self.draw = draw
		self.string = string
	def set_string(self, string): self.string = string
	def push(self, locx, locy): self.draw.text((locx, locy), self.string, font=self.font, fill="white", anchor="lt")
	def getsize(self): 
		left, top, right, bottom = self.font.getbbox(self.string)
		return [right - left, bottom - top]
	def center(self, y, x, w):
		size = self.getsize()
		xmid = x + w/2
		textposx = xmid - (size[0]/2)
		self.push(textposx, y)
	def smart_title(self, y, x, w):
		if len(self.string) > 16: self.push(10, y) 
		else: self.center(y, x, w)

class MintP3:
	LAYOUT_X_OFFSET = 10
	LAYOUT_Y_START = 20
	LINE_SPACING = 11
	HEADER_Y = 0
	PROGRESS_Y = 56
	SCROLL_SPEED = 1 

	def __init__(self, mp3_player, conn_manager, width=128, height=64):
		self.mp3_player = mp3_player
		self.conn = conn_manager
		self.font = font
		self.titlefont = titlefont
		serial = spi(port=0, device=0, bus_speed_hz=8000000, gpio_DC=23, gpio_RST=24)
		self.device = uc1701x(serial, width=width, height=height, rotate=2)
		self.heading = LabelObj("", self.titlefont, None)
		self.mainlabel = LabelObj("", self.titlefont, None)
		self.secondlabel = LabelObj("", self.font, None)
		self.albumlabel = LabelObj("", self.font, None) 
		self.time_label = LabelObj("", self.font, None)
		self.list_item = LabelObj("", self.font, None)
		
		self.cursor_idx = 0 
		self.is_editing = False
		self.shutdown_cursor = 0 
		self.cat_cursor = 0
		self.item_cursor = 0
		self.main_menu_cursor = 0
		self.bt_cursor = 0
		self.wifi_cursor = 0
		self.pairing_cursor = 0
		self.discovered_bt = []
		self.filtered_items = []
		self.scroll_pos = 0

		# Navigation tracking
		self.library_level = 0 # 0: List, 1: Albums (Artist context), 2: Songs (Album context)
		self.selected_artist = None
		self.selected_album = None

	def draw_status_bar(self, draw):
		state = self.mp3_player.get_state()
		x, y, w, h = 4, 1, 7, 7
		if state == "Playing": draw.polygon([(x, y), (x + w, y + h // 2), (x, y + h)], fill="white")
		elif state == "Paused":
			draw.rectangle([x, y, x + 2, y + h], fill="white")
			draw.rectangle([x + 5, y, x + 7, y + h], fill="white")
		if self.mp3_player._shuffle_enabled: draw.text((screen_w - 12, -1), "S", font=self.font, fill="white")
		draw.line([0, 12, screen_w, 12], fill="white")

	def draw_progress_bar(self, draw, progress):
		w, h = 70, 5
		x = (screen_w // 2) - (w // 2)
		y = self.PROGRESS_Y
		draw.rectangle([x, y, x + w, y + h], outline="white", fill="black")
		if progress > 0:
			bar_width = int((max(0, min(100, progress)) / 100) * (w - 2))
			draw.rectangle([x + 2, y + 2, x + 2 + bar_width, y + h - 2], outline="white", fill="white")
		return x, w

	def get_sys_info(self):
		# IP Address
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(("8.8.8.8", 80))
			ip = s.getsockname()[0]; s.close()
		except: ip = "Not Connected"
		
		# CPU Temp
		try:
			temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode().replace("temp=","").strip()
		except: temp = "??'C"

		# RAM
		if psutil:
			ram = psutil.virtual_memory()
			ram_str = f"{ram.used//1048576}MB / {ram.total//1048576}MB"
		else: ram_str = "psutil missing"

		# Uptime
		try:
			with open('/proc/uptime', 'r') as f:
				uptime_seconds = float(f.readline().split()[0])
				h = int(uptime_seconds // 3600)
				m = int((uptime_seconds % 3600) // 60)
				up_str = f"{h}h {m}m"
		except: up_str = "N/A"

		return {
			"ip": ip, "temp": temp, "ram": ram_str, "up": up_str,
			"host": socket.gethostname()[:15],
			"count": self.mp3_player.media_list.count() if self.mp3_player.media_list else 0
		}


	def draw_scrolling_text(self, text, y, font, draw, max_w=120):
		left, top, right, bottom = font.getbbox(text); w = right - left
		if w <= max_w: draw.text(((screen_w - w) // 2, y), text, font=font, fill="white")
		else:
			offset = int(self.scroll_pos % (w + 20))
			draw.text((10 - offset, y), text + "   " + text, font=font, fill="white")
			self.scroll_pos += self.SCROLL_SPEED

	def draw_playing(self):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw); self.heading.draw = self.mainlabel.draw = self.secondlabel.draw = self.albumlabel.draw = self.time_label.draw = draw
			if self.mp3_player.is_media_loaded() and self.mp3_player.get_state() != "Stopped":
				self.heading.set_string("Now Playing"); self.heading.center(self.HEADER_Y, 0, screen_w)
				tags = self.mp3_player.get_id3_tags()
				if tags:
					self.draw_scrolling_text(tags.get('title', 'Unknown'), self.LAYOUT_Y_START - 2, self.titlefont, draw)
					self.secondlabel.set_string(tags.get('artist', 'Unknown Artist')[:22]); self.secondlabel.center(self.LAYOUT_Y_START + 16, 0, screen_w)
					self.albumlabel.set_string(tags.get('album', 'Unknown Album')[:22]); self.albumlabel.center(self.LAYOUT_Y_START + 25, 0, screen_w)
				bar_x, bar_w = self.draw_progress_bar(draw, self.mp3_player.get_progress())
				curr = self.mp3_player.get_time() / 1000
				self.time_label.set_string(f"{int(curr//60)}:{int(curr%60):02d}"); self.time_label.push(bar_x - 26, self.PROGRESS_Y)
				dur = self.mp3_player.player.get_media().get_duration() / 1000
				rem = dur - curr
				if rem > 0: self.time_label.set_string(f"-{int(rem//60)}:{int(rem%60):02d}"); self.time_label.push(bar_x + bar_w + 4, self.PROGRESS_Y)
			else: self.heading.set_string("Stopped"); self.heading.center(self.HEADER_Y, 0, screen_w)

	def draw_list_menu(self, title, items, current_idx):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw); self.heading.draw = self.list_item.draw = draw
			self.heading.set_string(title); self.heading.smart_title(self.HEADER_Y, 0, screen_w)
			start = (current_idx // 4) * 4
			for i, text in enumerate(items[start:start+4]):
				prefix = "> " if (start + i) == current_idx else "  "
				self.list_item.set_string(prefix + str(text)[:18]); self.list_item.push(self.LAYOUT_X_OFFSET, self.LAYOUT_Y_START + (i * self.LINE_SPACING))

	def draw_settings(self, shuffle, light, vol):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw); self.heading.draw = self.list_item.draw = draw
			self.heading.set_string("Settings"); self.heading.center(self.HEADER_Y, 0, screen_w)
			items = [f"Shuffle: {'ON' if shuffle else 'OFF'}", f"Light: {'ON' if light else 'OFF'}", f"Vol: {vol}%", "Bluetooth", "Wi-Fi", "Rescan Lib", "Shutdown"]
			cursor = "X" if self.is_editing else ">"
			start = (self.cursor_idx // 4) * 4
			for i, text in enumerate(items[start:start+4]):
				prefix = f"{cursor} " if (start + i) == self.cursor_idx else "  "
				self.list_item.set_string(prefix + text); self.list_item.push(self.LAYOUT_X_OFFSET, self.LAYOUT_Y_START + (i * self.LINE_SPACING))

	def draw_message(self, message):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw); self.heading.draw = draw
			self.heading.set_string(message); self.heading.center(30, 0, screen_w)

	def draw_about(self):
		info = self.get_sys_info()
		with canvas(self.device) as draw:
			self.draw_status_bar(draw)
			self.heading.draw = self.list_item.draw = draw
			self.heading.set_string("System Info")
			self.heading.center(self.HEADER_Y, 0, screen_w)
			
			metrics = [
				f"IP: {info['ip']}",
				f"CPU: {info['temp']} | Up: {info['up']}",
				f"RAM: {info['ram']}",
				f"Library: {info['count']} tracks"
			]
			for i, text in enumerate(metrics):
				self.list_item.set_string(text)
				self.list_item.push(5, self.LAYOUT_Y_START + (i * self.LINE_SPACING))


# --- Logic ---
player = VLCPlayer(); conn = ConnectivityManager(); display = MintP3(player, conn)
webui = Mp3PlayerWebUI(); webui.set_player(player); webui.start()
bt_thread = Thread(target=bt_headset_thread, args=(player, conn)); bt_thread.daemon = True; bt_thread.start()

player.play_directory("music/"); player.play(); player.toggle_play()
current_view = "playing"; previous_view = "playing"; backstat = True; display.device.backlight(not backstat)

try:
	while True:
		status = player.get_current_song_info()
		if status: webui.update_status(status)
		if not hasattr(glob, 'eventlist') or len(glob.eventlist) < 2:
			if current_view == "playing": display.draw_playing()
			time.sleep(0.05); continue
		btn = glob.eventlist[0]; hold = glob.eventlist[1]

		# Home Toggle
		if btn[0]:
			btn[0] = False
			display.scroll_pos = 0 # Reset scroll on view change
			if current_view == "main_menu":
				current_view = previous_view
			else: 
				previous_view = current_view
				current_view = "main_menu"
		
		if hold[0]: hold[0] = False; backstat = not backstat; display.device.backlight(not backstat)
		if hold[2]: hold[2] = False; player.toggle_shuffle()

		if current_view == "main_menu":
			menu = ["Now Playing", "Library", "Settings", "About"]
			if btn[1]: btn[1] = False; display.main_menu_cursor = (display.main_menu_cursor - 1) % len(menu)
			if btn[3]: btn[3] = False; display.main_menu_cursor = (display.main_menu_cursor + 1) % len(menu)
			if btn[2]:
				btn[2] = False; mapping = {0:"playing", 1:"category_select", 2:"settings", 3:"about"}
				current_view = mapping[display.main_menu_cursor]; previous_view = current_view; display.scroll_pos = 0 
			display.draw_list_menu("Main Menu", menu, display.main_menu_cursor)

		elif current_view == "playing":
			if btn[2]: btn[2] = False; player.toggle_play()
			if btn[1]: btn[1] = False; player.previous_track(); display.scroll_pos = 0 
			if btn[3]: btn[3] = False; player.next_track(); display.scroll_pos = 0 
			display.draw_playing()
		
		elif current_view == "category_select":
			opts = ["Song", "Artist", "Album"]
			if btn[1]: btn[1] = False; display.cat_cursor = (display.cat_cursor - 1) % 3
			if btn[3]: btn[3] = False; display.cat_cursor = (display.cat_cursor + 1) % 3
			if btn[2]:
				btn[2] = False; c_type = ["song", "artist", "album"][display.cat_cursor]
				display.filtered_items = ["PLAY ALL"] + player.get_unique_metadata(c_type)
				display.item_cursor = 0; display.library_level = 0; current_view = "library_select"
			display.draw_list_menu("Browse", opts, display.cat_cursor)

		elif current_view == "library_select":
			if btn[1]: btn[1] = False; display.item_cursor = (display.item_cursor - 1) % len(display.filtered_items)
			if btn[3]: btn[3] = False; display.item_cursor = (display.item_cursor + 1) % len(display.filtered_items)
			if btn[2]:
				btn[2] = False; sel = display.filtered_items[display.item_cursor]
				c_type = ["song", "artist", "album"][display.cat_cursor]
				
				# Drill-down Logic
				if sel == "PLAY ALL":
					if display.library_level == 1: player.filter_playlist("artist", display.selected_artist)
					elif display.library_level == 2: player.filter_playlist("album", display.selected_album, artist_context=display.selected_artist)
					else: player.filter_playlist(None, None)
					current_view = "playing"; display.scroll_pos = 0
				elif c_type == "artist" and display.library_level == 0:
					display.selected_artist = sel; display.library_level = 1
					display.filtered_items = ["PLAY ALL"] + player.get_unique_metadata("album", artist_filter=sel)
					display.item_cursor = 0
				elif (c_type == "album" or display.library_level == 1) and display.library_level < 2:
					display.selected_album = sel; display.library_level = 2
					display.filtered_items = ["PLAY ALL"] + player.get_unique_metadata("song", artist_filter=display.selected_artist, album_filter=sel)
					display.item_cursor = 0
				else: # Play specific song
					player.filter_playlist("song", sel); current_view = "playing"; display.scroll_pos = 0
			display.draw_list_menu("Select", display.filtered_items, display.item_cursor)

		elif current_view == "settings":
			num_items = 7
			if btn[2]:
				btn[2] = False
				if display.cursor_idx == 3: current_view = "bt_menu"
				elif display.cursor_idx == 4: current_view = "wifi_menu"
				elif display.cursor_idx == 5: 
					display.draw_message("Rescanning..."); player.rescan_library("music/"); display.draw_message("Done"); time.sleep(1)
				elif display.cursor_idx == 6: current_view = "confirm_shutdown"
				else: display.is_editing = not display.is_editing
			if not display.is_editing:
				if btn[1]: btn[1] = False; display.cursor_idx = (display.cursor_idx - 1) % num_items
				if btn[3]: btn[3] = False; display.cursor_idx = (display.cursor_idx + 1) % num_items
			else:
				ch = -1 if btn[1] else 1 if btn[3] else 0
				if ch != 0:
					btn[1] = btn[3] = False
					if display.cursor_idx == 0: player.toggle_shuffle()
					elif display.cursor_idx == 1: backstat = not backstat; display.device.backlight(not backstat)
					elif display.cursor_idx == 2: player.set_volume(max(0, min(100, player.get_volume() + (ch * 5))))
			display.draw_settings(player._shuffle_enabled, backstat, player.get_volume())

		elif current_view == "wifi_menu":
			wf_on = conn.is_wifi_on(); wf_items = [f"WiFi: {'ON' if wf_on else 'OFF'}", "Back"]
			if btn[1]: btn[1] = False; display.wifi_cursor = (display.wifi_cursor - 1) % 2
			if btn[3]: btn[3] = False; display.wifi_cursor = (display.wifi_cursor + 1) % 2
			if btn[2]:
				btn[2] = False
				if display.wifi_cursor == 0: conn.toggle_wifi(not wf_on)
				else: current_view = "settings"
			display.draw_list_menu("Wi-Fi", wf_items, display.wifi_cursor)

		elif current_view == "bt_menu":
			bt_on = conn.is_bt_on(); bt_items = ["Pair New Device", f"Re-Pair {conn.paired_name[:10]}", f"BT: {'ON' if bt_on else 'OFF'}", "Back"]
			if btn[1]: btn[1] = False; display.bt_cursor = (display.bt_cursor - 1) % 4
			if btn[3]: btn[3] = False; display.bt_cursor = (display.bt_cursor + 1) % 4
			if btn[2]:
				btn[2] = False
				if display.bt_cursor == 0: 
					display.draw_message("Scanning..."); display.discovered_bt = conn.discover_devices(); display.pairing_cursor = 0; current_view = "bt_pairing_select"
				elif display.bt_cursor == 1: display.draw_message("Connecting..."); conn.repair_existing()
				elif display.bt_cursor == 2: conn.toggle_bluetooth(not bt_on)
				else: current_view = "settings"
			display.draw_list_menu("Bluetooth", bt_items, display.bt_cursor)

		elif current_view == "bt_pairing_select":
			names = [d["name"] for d in display.discovered_bt]
			if not names: names = ["No Devices Found", "Back"]
			if btn[1]: btn[1] = False; display.pairing_cursor = (display.pairing_cursor - 1) % len(names)
			if btn[3]: btn[3] = False; display.pairing_cursor = (display.pairing_cursor + 1) % len(names)
			if btn[2]:
				btn[2] = False
				if "Back" in names[display.pairing_cursor] or "No Devices" in names[display.pairing_cursor]: current_view = "bt_menu"
				else:
					target = display.discovered_bt[display.pairing_cursor]; display.draw_message("Pairing..."); conn.pair_device(target["mac"], target["name"]); current_view = "bt_menu"
			display.draw_list_menu("Select Device", names, display.pairing_cursor)

		elif current_view == "about":
			if btn[1] or btn[2] or btn[3]:
				btn[1] = btn[2] = btn[3] = False
				current_view = "main_menu"
			display.draw_about()

		elif current_view == "confirm_shutdown":
			if btn[1] or btn[3]: btn[1] = btn[3] = False; display.shutdown_cursor = 1 - display.shutdown_cursor
			if btn[2]:
				btn[2] = False
				if display.shutdown_cursor == 1: os.system("sudo shutdown -h now")
				else: current_view = "settings"
			with canvas(display.device) as draw:
				display.draw_status_bar(draw); display.heading.draw = display.list_item.draw = draw
				display.heading.set_string("Shutdown?"); display.heading.center(0, 0, screen_w)
				display.list_item.set_string("Cancel"); display.list_item.push(30, 30)
				display.list_item.set_string("Power Off"); display.list_item.push(30, 42)
				draw.text((20, 30 if display.shutdown_cursor == 0 else 42), ">", font=font, fill="white")

		time.sleep(0.05)
except KeyboardInterrupt:
	GPIO.cleanup()