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
from PIL import ImageFont, Image, ImageDraw
import evdev
from evdev import ecodes
import random
import json
from PIL import Image, ImageOps
from luma.core.render import canvas
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
	def set_string(self, string): 
		self.string = string
	def push(self, locx, locy): 
		self.draw.text((locx, locy), self.string, font=self.font, fill="white", anchor="lt")
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


class MintPet:
	def __init__(self):
		self.DATA_FILE = "assets/pet_data.json"
		self.SPRITE_PATH = "assets/mintpet_spritesheet.png"
		self.box_size = 18 
		
		# Persisted Stats
		self.hunger = 100
		self.happiness = 100
		self.stage = 0 
		self.xp = 0
		self.facing_right = False
		
		# Session State
		self.listen_threshold_met = False
		self.last_update = time.time()
		self.last_playing_time = time.time()
		self.x, self.y = 64, 45 
		self.dx, self.dy = 0, 0
		self.is_dancing = False
		self.is_sleeping = False

		self.load_stats() # Load saved data on init

		try:
			img = Image.open(self.SPRITE_PATH).convert("1")
			self.atlas = ImageOps.invert(img) 
		except:
			self.atlas = None

	def load_stats(self):
		if os.path.exists(self.DATA_FILE):
			try:
				with open(self.DATA_FILE, 'r') as f:
					data = json.load(f)
					# Use .get() with defaults to avoid KeyErrors if the file is old/corrupt
					self.hunger = data.get("hunger", 100)
					self.happiness = data.get("happiness", 100)
					self.stage = data.get("stage", 0)
					self.xp = data.get("xp", 0)
					self.facing_right = data.get("facing_right", False)
			except Exception as e:
				print(f"Error loading stats: {e}")

	def save_stats(self):
		try:
			# Ensure the assets directory exists before writing
			os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
			
			stats_to_save = {
				"hunger": self.hunger,
				"happiness": self.happiness,
				"stage": self.stage,
				"xp": self.xp,
				"facing_right": self.facing_right
			}
			
			with open(self.DATA_FILE, 'w') as f:
				json.dump(stats_to_save, f)
		except Exception as e:
			print(f"Error saving stats: {e}")

	def update_evolution(self):
		new_stage = min(5, self.xp // 10)
		if new_stage != self.stage:
			self.stage = new_stage
			self.save_stats() # Save the new stage immediately

	def finish_track(self):
		if self.listen_threshold_met:
			self.xp += 1
			self.happiness = min(100, self.happiness + 10)
			self.update_evolution() # This must call save_stats internally
			self.save_stats() # Force save here as well
		self.listen_threshold_met = False

	def on_track_change(self):
		self.is_sleeping = False
		self.listen_threshold_met = False
		self.last_playing_time = time.time()

	def get_current_sprite(self):
		if not self.atlas: return None
		col = self.stage
		if self.is_sleeping:
			row = 2
		elif self.is_dancing:
			row = int(time.time() * 2) % 2 
		else:
			row = 0
		left, top = col * self.box_size, row * self.box_size
		sprite = self.atlas.crop((left, top, left + self.box_size, top + self.box_size))
		if self.facing_right:
			sprite = ImageOps.mirror(sprite)
		return sprite

	def update(self, is_playing, volume):
		now = time.time()
		self.is_dancing = is_playing
		
		if is_playing:
			self.last_playing_time = now
			self.is_sleeping = False
		elif now - self.last_playing_time > 60:
			self.is_sleeping = True

		if now - self.last_update >= 1.0:
			if not self.is_sleeping:
				if is_playing:
					self.dx = random.choice([-3, -2, 2, 3])
					self.dy = random.choice([-2, -1, 1, 2])
				else:
					self.dx, self.dy = (random.choice([-1, 1]), 0) if random.random() < 0.2 else (0, 0)
			else:
				self.dx, self.dy = 0, 0
			self.last_update = now

		if self.dx > 0: self.facing_right = True
		elif self.dx < 0: self.facing_right = False

		self.x = max(2, min(128 - self.box_size - 2, self.x + self.dx))
		self.y = max(30, min(48, self.y + self.dy))

	def draw_staff(self, draw, start_y=20, spacing=4, line_width=1):
		"""
		Draws a five-line musical staff.
		:param draw: The luma.core.render.canvas draw object.
		:param start_y: The top-most line's Y position.
		:param spacing: Vertical pixels between each line.
		:param line_width: The thickness of the horizontal lines.
		"""
		# Draw the 5 horizontal lines
		for i in range(5):
			y = start_y + (i * spacing)
			draw.line((0, y, 128, y), fill="white", width=line_width)

		# Staff boundaries
		bottom_y = start_y + (4 * spacing)
		
		# Thick bar line on the left (Start of staff)
		draw.line((0, start_y, 0, bottom_y), fill="white", width=3)
		
		# Thin bar line on the right (End of screen)
		draw.line((127, start_y, 127, bottom_y), fill="white", width=1)
		
	def draw(self, device, font, cursor, show_menu=False):
		with canvas(device) as draw:
			draw.text((42, 1), "MintPet", font=font, fill="white")
			draw.line((0, 11, 128, 11), fill="white")
			sprite = self.get_current_sprite()
			if sprite:
				draw.bitmap((self.x, self.y - self.box_size), sprite, fill="white")
			draw.text((5, 54), f"HNG:{self.hunger}%", font=font, fill="white")
			draw.text((60, 54), f"HAP:{self.happiness}%", font=font, fill="white")
			draw.text((110, 54), f"X:{self.xp}", font=font, fill="white") # Show XP


			self.draw_staff(draw, start_y=25, spacing=5, line_width=1)

			if show_menu:
				draw.rectangle([8, 14, 55, 43], fill="black", outline="white")
				items = ["Feed", "Play", "Back"]
				for i, text in enumerate(items):
					prefix = ">" if i == cursor else " "
					draw.text((12, 16 + (i * 9)), f"{prefix}{text}", font=font, fill="white")

	def feed(self):
		"""Restored: Increases hunger stat and saves."""
		self.is_sleeping = False
		self.hunger = min(100, self.hunger + 20)
		self.save_stats()

	def play(self):
		"""Restored: Increases happiness stat and saves."""
		self.is_sleeping = False
		self.happiness = min(100, self.happiness + 15)
		self.save_stats()

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

		self.pet = MintPet()
		self.pet_cursor = 0
		
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
		self.header_scroll_pos = 0
		self.header_title = "Main Menu"

		# Navigation tracking
		self.library_level = 0 
		self.selected_artist = None
		self.selected_album = None

	def draw_status_bar(self, draw, heading = "default"):

		self.draw_scrolling_text(heading, self.HEADER_Y, self.titlefont, draw, max_w=90, scroll_var="header")

		state = self.mp3_player.get_state()
		x, y, w, h = 4, 1, 7, 7
		if state == "Playing": 
			draw.polygon([(x, y), (x + w, y + h // 2), (x, y + h)], fill="white")
		elif state == "Paused":
			draw.rectangle([x, y, x + 2, y + h], fill="white")
			draw.rectangle([x + 5, y, x + 7, y + h], fill="white")
		if self.mp3_player._shuffle_enabled: 
			draw.text((screen_w - 12, -1), "S", font=self.font, fill="white")
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
		try:
			s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
			s.connect(("8.8.8.8", 80))
			ip = s.getsockname()[0]; s.close()
		except: ip = "Not Connected"
		try:
			temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode().replace("temp=","").strip()
		except: temp = "??'C"
		if psutil:
			ram = psutil.virtual_memory()
			ram_str = f"{ram.used//1048576}MB / {ram.total//1048576}MB"
		else: ram_str = "psutil missing"
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

	def draw_scrolling_text(self, text, y, font, draw, max_w=None, scroll_var="main"):
			screen_w = draw.im.size[0]
			envelope_w = max_w if max_w is not None else screen_w
			start_x = (screen_w - envelope_w) // 2

			left, top, right, bottom = font.getbbox(text)
			w = right - left
			h = bottom + 2 # Padding for descenders (g, j, p, q, y)

			if w <= envelope_w:
				# STATIC CENTERED
				inner_x = (envelope_w - w) // 2
				text_canvas = Image.new("1", (envelope_w, h))
				text_draw = ImageDraw.Draw(text_canvas)
				text_draw.text((inner_x, 0), text, font=font, fill="white", anchor="lt")
				draw.bitmap((start_x, y), text_canvas, fill="white")
			else:
				# SCROLLING LOGIC
				text_canvas = Image.new("1", (envelope_w, h))
				text_draw = ImageDraw.Draw(text_canvas)
				
				# 1. Use the correct tracker
				pos = self.scroll_pos if scroll_var == "main" else self.header_scroll_pos
				
				# 2. Smooth Loop Math
				# We add a fixed spacing (e.g., 60px) so the gap is consistent
				gap = 60 
				total_loop_len = w + gap
				offset = pos % total_loop_len
				
				# 3. Draw with sub-pixel math (truncated to int for the actual pixel coord)
				# We draw the string twice with the gap in between
				full_string = text + " " * 10 + text
				text_draw.text((-int(offset), 0), full_string, font=font, fill="white", anchor="lt")
				
				draw.bitmap((start_x, y), text_canvas, fill="white")
				
				# 4. Increment the tracker
				if scroll_var == "main": 
					self.scroll_pos += self.SCROLL_SPEED
				else: 
					self.header_scroll_pos += self.SCROLL_SPEED

	def draw_playing(self):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw,"Now Playing") 
			self.mainlabel.draw = self.secondlabel.draw = self.albumlabel.draw = self.time_label.draw = draw
			
			if self.mp3_player.is_media_loaded() and self.mp3_player.get_state() != "Stopped":
				
				# Standard "Now Playing" header				
				tags = self.mp3_player.get_id3_tags()
				
				if tags:
					# Ensure values are strings to prevent NoneType subscripting error
					title = tags.get('title') or 'Unknown'
					artist = tags.get('artist') or 'Unknown Artist'
					album = tags.get('album') or 'Unknown Album'

					self.draw_scrolling_text(str(title), self.LAYOUT_Y_START - 2, self.titlefont, draw)
					self.secondlabel.set_string(str(artist)[:22])
					self.secondlabel.center(self.LAYOUT_Y_START + 16, 0, screen_w)
					self.albumlabel.set_string(str(album)[:22])
					self.albumlabel.center(self.LAYOUT_Y_START + 25, 0, screen_w)

				bar_x, bar_w = self.draw_progress_bar(draw, self.mp3_player.get_progress())
				curr = self.mp3_player.get_time() / 1000
				self.time_label.set_string(f"{int(curr//60)}:{int(curr%60):02d}")
				self.time_label.push(bar_x - 26, self.PROGRESS_Y)
				dur = self.mp3_player.player.get_media().get_duration() / 1000
				rem = dur - curr
				if rem > 0: 
					self.time_label.set_string(f"-{int(rem//60)}:{int(rem%60):02d}")
					self.time_label.push(bar_x + bar_w + 4, self.PROGRESS_Y)
			else: 
				self.draw_scrolling_text("Stopped", self.HEADER_Y, self.titlefont, draw, max_w=90, scroll_var="header")

	def draw_list_menu(self, title, items, current_idx):

		with canvas(self.device) as draw:

			self.draw_status_bar(draw, title); 
			self.heading.draw = self.list_item.draw = draw
			# Apply scrolling to the header

			start = (current_idx // 4) * 4
			for i, text in enumerate(items[start:start+4]):
				prefix = "> " if (start + i) == current_idx else "  "
				self.list_item.set_string(prefix + str(text)[:18])
				self.list_item.push(self.LAYOUT_X_OFFSET, self.LAYOUT_Y_START + (i * self.LINE_SPACING))

	def draw_settings(self, shuffle, light, vol):

		with canvas(self.device) as draw:

			self.draw_status_bar(draw,"Settings"); 
			self.list_item.draw = draw
			items = [f"Shuffle: {'ON' if shuffle else 'OFF'}", f"Light: {'ON' if light else 'OFF'}", f"Vol: {vol}%", "Bluetooth", "Wi-Fi", "Rescan Lib", "Shutdown"]
			cursor = "X" if self.is_editing else ">"
			start = (self.cursor_idx // 4) * 4
			for i, text in enumerate(items[start:start+4]):
				prefix = f"{cursor} " if (start + i) == self.cursor_idx else "  "
				self.list_item.set_string(prefix + text)
				self.list_item.push(self.LAYOUT_X_OFFSET, self.LAYOUT_Y_START + (i * self.LINE_SPACING))

	def draw_message(self, message, header="Alert"):
		with canvas(self.device) as draw:
			self.draw_status_bar(draw,header) 
			self.heading.draw = draw
			self.heading.set_string(message)
			self.heading.center(30, 0, screen_w)

	def draw_about(self):
		info = self.get_sys_info()
		with canvas(self.device) as draw:
			self.draw_status_bar(draw,"System Info")
			self.heading.draw = self.list_item.draw = draw
			metrics = [f"IP: {info['ip']}", f"CPU: {info['temp']} | Up: {info['up']}", f"RAM: {info['ram']}", f"Library: {info['count']} tracks"]
			for i, text in enumerate(metrics):
				self.list_item.set_string(text)
				self.list_item.push(5, self.LAYOUT_Y_START + (i * self.LINE_SPACING))


# --- Logic ---
player = VLCPlayer()
conn = ConnectivityManager() 

config_data = conn.load_config()
player.set_music_dir(config_data["music_dir"])

display = MintP3(player, conn)

if not os.path.isdir(player.music_dir):
	display.draw_message("Path Not Found", header="Error")
else:
	player.play_directory(player.music_dir)
	# ... rest of startup ...
	player.play()
	player.toggle_play()

webui = Mp3PlayerWebUI()
webui.set_player(player)
webui.start()
bt_thread = Thread(target=bt_headset_thread, args=(player, conn))
bt_thread.daemon = True; bt_thread.start()


current_view = "main_menu"
view_stack = [] 
backstat = True
display.device.backlight(not backstat)

pet_menu_active = False

def push_state():
	state = {
		'view': current_view,
		'header': display.header_title,
		'items': list(display.filtered_items) if display.filtered_items else [],
		'cursor': display.item_cursor,
		'level': display.library_level,
		'artist': display.selected_artist,
		'album': display.selected_album,
		'cat_cursor': display.cat_cursor,
		'main_cursor': display.main_menu_cursor,
		'set_cursor': display.cursor_idx,
		'bt_cursor': display.bt_cursor,
		'wifi_cursor': display.wifi_cursor
	}
	view_stack.append(state)

try:
	while True:

		
		state = player.get_state()
		is_playing = state == "Playing"
		current_time = player.get_current_time() # Matches VLCPlayer.py
		total_time = player.get_duration()

		if state == "Playing" and total_time > 0:
			# Once you pass 90%, the pet "notices" you are listening
			if (current_time / total_time) > 0.9:
				display.pet.listen_threshold_met = True

		# VLC transitions to 'Stopped' or 'Ended' briefly between songs
		# We check for these to award XP
		if state in ["Stopped", "Unknown"] or player.has_just_finished():
			if display.pet.listen_threshold_met:
				display.pet.finish_track() # Awards XP and resets flag

		vol = player.get_volume()
		display.pet.update(is_playing, vol)
		status = player.get_current_song_info()

		if status: webui.update_status(status)
		if not hasattr(glob, 'eventlist') or len(glob.eventlist) < 2:
			# Redraw loop for animations/scrolling even without input
			if current_view == "playing": display.draw_playing()
			elif current_view == "main_menu": 
				display.draw_list_menu("Main Menu", ["Now Playing", "Library", "Settings", "About"], display.main_menu_cursor)
			elif current_view == "category_select": 
				display.draw_list_menu("Browse", ["Song", "Artist", "Album"], display.cat_cursor)
			elif current_view == "library_select": 
				display.draw_list_menu(display.header_title, display.filtered_items, display.item_cursor)
			elif current_view == "settings": 
				display.draw_settings(player._shuffle_enabled, backstat, player.get_volume())
			elif current_view == "about": 
				display.draw_about()
			time.sleep(0.05); continue
		
		btn = glob.eventlist[0]; hold = glob.eventlist[1]

		# Home / Back Logic (Button A)
		if btn[0]:
			btn[0] = False
			display.scroll_pos = 0; display.header_scroll_pos = 0
			if view_stack:
				state = view_stack.pop()
				current_view = state['view']
				display.header_title = state['header']
				display.filtered_items = state['items']
				display.item_cursor = state['cursor']
				display.library_level = state['level']
				display.selected_artist = state['artist']
				display.selected_album = state['album']
				display.cat_cursor = state['cat_cursor']
				display.main_menu_cursor = state['main_cursor']
				display.cursor_idx = state['set_cursor']
				display.bt_cursor = state['bt_cursor']
				display.wifi_cursor = state['wifi_cursor']
				if current_view == "main_menu": view_stack = []
			else:
				current_view = "main_menu"
				display.header_title = "Main Menu"
			continue
		
		if hold[0]: 
			hold[0] = False
			backstat = not backstat
			display.device.backlight(not backstat)

		if hold[2]: 
			hold[2] = False
			player.toggle_shuffle()

		if current_view == "main_menu":
			menu = ["Now Playing", "Library", "Settings", "MintPet", "About"]
			if btn[1]:
				btn[1] = False
				display.main_menu_cursor = (display.main_menu_cursor - 1) % len(menu)
			if btn[3]: 
				btn[3] = False
				display.main_menu_cursor = (display.main_menu_cursor + 1) % len(menu)
			if btn[2]:
				btn[2] = False
				push_state()
				mapping = {0:"playing", 1:"category_select", 2:"settings", 3:"pet", 4:"about"}
				current_view = mapping[display.main_menu_cursor]
				display.header_title = menu[display.main_menu_cursor]
				display.scroll_pos = 0; display.header_scroll_pos = 0
			display.draw_list_menu("Main Menu", menu, display.main_menu_cursor)

		elif current_view == "playing":
			if btn[2]: 
				btn[2] = False
				player.toggle_play()
			if btn[1]:
				btn[1] = False
				player.previous_track()
				display.scroll_pos = 0 
			if btn[3]: 
				btn[3] = False
				player.next_track()
				display.pet.on_track_change() # Pet gets "fed" by new music
				display.scroll_pos = 0
			display.draw_playing()
		
		elif current_view == "category_select":
			opts = ["Song", "Artist", "Album"]
			if btn[1]: 
				btn[1] = False
				display.cat_cursor = (display.cat_cursor - 1) % len(opts)
			if btn[3]: 
				btn[3] = False; display.cat_cursor = (display.cat_cursor + 1) % len(opts)
			if btn[2]:
				btn[2] = False
				push_state()
				c_type = ["song", "artist", "album"][display.cat_cursor]
				display.draw_message("Loading...", header=opts[display.cat_cursor])
				display.filtered_items = ["Play All"] + player.get_unique_metadata(c_type)
				display.item_cursor = 0
				display.library_level = 0
				display.header_title = opts[display.cat_cursor]
				current_view = "library_select"
				display.header_scroll_pos = 0
			display.draw_list_menu("Browse", opts, display.cat_cursor)

		elif current_view == "library_select":
			if btn[1]: 
				btn[1] = False
				display.item_cursor = (display.item_cursor - 1) % len(display.filtered_items)
			if btn[3]: 
				btn[3] = False; display.item_cursor = (display.item_cursor + 1) % len(display.filtered_items)
			
			# if play pressed
			if btn[2]:
				btn[2] = False
				sel = display.filtered_items[display.item_cursor]
				c_type = ["song", "artist", "album"][display.cat_cursor]
				
				if sel == "Play All":
					display.draw_message("Loading...", header=sel)
					push_state()
					if display.library_level == 1: 
						player.filter_playlist("artist", display.selected_artist)
					elif display.library_level == 2:
						player.filter_playlist("album", display.selected_album, artist_context=display.selected_artist)
					else: 
						player.filter_playlist(None, None)
					current_view = "playing"
					display.scroll_pos = 0
				elif c_type == "artist" and display.library_level == 0:
					push_state()
					display.draw_message("Loading...", header=sel)
					display.selected_artist = sel
					display.library_level = 1
					display.header_title = sel
					display.filtered_items = ["Play All"] + player.get_unique_metadata("album", artist_filter=sel)
					display.item_cursor = 0
					display.header_scroll_pos = 0
				elif (c_type == "album" or display.library_level == 1) and display.library_level < 2:
					push_state()
					display.draw_message("Loading...", header=sel)
					display.selected_album = sel
					display.library_level = 2
					display.header_title = sel
					display.filtered_items = ["Play All"] + player.get_unique_metadata("song", artist_filter=display.selected_artist, album_filter=sel)
					display.item_cursor = 0
					display.header_scroll_pos = 0
				else: 
					display.draw_message("Loading...", header=sel)
					player.filter_playlist("song", sel)
					push_state()
					current_view = "playing"
					display.scroll_pos = 0

			display.draw_list_menu(display.header_title, display.filtered_items, display.item_cursor)

		elif current_view == "settings":

			num_items = 7
			
			if btn[2]:
				btn[2] = False
				if display.cursor_idx == 3: 
					push_state()
					current_view = "bt_menu"
				elif display.cursor_idx == 4: 
					push_state()
					current_view = "wifi_menu"
				elif display.cursor_idx == 5: 
					display.draw_message("Rescanning...", header="Settings")
					# No need to load config or resolve paths here anymore
					player.rescan_library() 
					display.draw_message("Done", header="Settings")
					time.sleep(1)
				elif display.cursor_idx == 6: 
					push_state()
					current_view = "confirm_shutdown"
				else: display.is_editing = not display.is_editing

			if not display.is_editing:
				if btn[1]: 
					btn[1] = False
					display.cursor_idx = (display.cursor_idx - 1) % num_items
				if btn[3]: 
					btn[3] = False; display.cursor_idx = (display.cursor_idx + 1) % num_items
			else:
				ch = -1 if btn[1] else 1 if btn[3] else 0
				if ch != 0:
					btn[1] = btn[3] = False
					if display.cursor_idx == 0: player.toggle_shuffle()
					elif display.cursor_idx == 1: backstat = not backstat; display.device.backlight(not backstat)
					elif display.cursor_idx == 2: player.set_volume(max(0, min(100, player.get_volume() + (ch * 5))))
			display.draw_settings(player._shuffle_enabled, backstat, player.get_volume())

		elif current_view == "wifi_menu":
					wf_on = conn.is_wifi_on()
					ap_on = conn.is_ap_on()
					wf_items = [
						f"WiFi: {'ON' if wf_on else 'OFF'}", 
						f"Hotspot: {'ON' if ap_on else 'OFF'}", 
						"Back"
					]
					
					if btn[1]: 
						btn[1] = False
						display.wifi_cursor = (display.wifi_cursor - 1) % len(wf_items)
					if btn[3]: 
						btn[3] = False
						display.wifi_cursor = (display.wifi_cursor + 1) % len(wf_items)
						
					if btn[2]:
						btn[2] = False
						if display.wifi_cursor == 0:
							conn.toggle_wifi(not wf_on)
						elif display.wifi_cursor == 1:
							display.draw_message("Starting AP...", header="Wi-Fi")
							conn.toggle_ap(not ap_on)
						else:
							if view_stack:
								state = view_stack.pop()
								current_view = state['view']
							else:
								current_view = "settings"
					display.draw_list_menu("Wi-Fi", wf_items, display.wifi_cursor)

		elif current_view == "bt_menu":
			bt_on = conn.is_bt_on(); bt_items = ["Pair New Device", f"Re-Pair {conn.paired_name[:10]}", f"BT: {'ON' if bt_on else 'OFF'}", "Back"]
			if btn[1]: 
				btn[1] = False
				display.bt_cursor = (display.bt_cursor - 1) % 4
			if btn[3]: 
				btn[3] = False; display.bt_cursor = (display.bt_cursor + 1) % 4
			if btn[2]:
				btn[2] = False
				if display.bt_cursor == 0: 
					display.draw_message("Scanning...", header="Bluetooth")
					# Perform the scan
					found_devices = conn.discover_devices()
					
					if found_devices:
						push_state()
						display.discovered_bt = found_devices
						display.pairing_cursor = 0
						current_view = "bt_pairing_select"
					else:
						display.draw_message("No Devices Found", header="Bluetooth")
						time.sleep(1.5)
			display.draw_list_menu("Bluetooth", bt_items, display.bt_cursor)

		elif current_view == "bt_pairing_select":
			# Create a list of names for the menu
			device_names = [d['name'] for d in display.discovered_bt]
			
			if btn[1]: 
				btn[1] = False
				display.pairing_cursor = (display.pairing_cursor - 1) % len(device_names)
			if btn[3]: 
				btn[3] = False
				display.pairing_cursor = (display.pairing_cursor + 1) % len(device_names)
			
			if btn[2]:
				btn[2] = False
				target = display.discovered_bt[display.pairing_cursor]
				display.draw_message("Pairing...", header=target['name'][:10])
				
				if conn.pair_device(target['mac'], target['name']):
					display.draw_message("Success!", header="Bluetooth")
				else:
					display.draw_message("Failed", header="Bluetooth")
				
				time.sleep(1.5)
				current_view = "bt_menu" # Go back after attempt

			display.draw_list_menu("Select Device", device_names, display.pairing_cursor)

		elif current_view == "confirm_shutdown":
					if btn[1] or btn[3]: 
						btn[1] = btn[3] = False
						display.shutdown_cursor = 1 - display.shutdown_cursor
					if btn[2]:
						btn[2] = False
						if display.shutdown_cursor == 1: os.system("sudo shutdown -h now")
						else:
							if view_stack: current_view = view_stack.pop()['view']
							else: current_view = "settings"
					with canvas(display.device) as draw:
						display.draw_status_bar(draw,"Shutdown?")
						display.heading.draw = display.list_item.draw = draw
						
						# Define positions to ensure alignment
						options = ["Cancel", "Power Off"]
						for i, text in enumerate(options):
							prefix = "> " if display.shutdown_cursor == i else "  "
							display.list_item.set_string(prefix + text)
							# Using LAYOUT constants to match the rest of the menus
							display.list_item.push(display.LAYOUT_X_OFFSET, display.LAYOUT_Y_START + (i * display.LINE_SPACING))

		elif current_view == "pet":
			# Toggle menu or select option with Center Button (btn[2])
			if btn[2]:
				btn[2] = False
				if not pet_menu_active:
					pet_menu_active = True
				else:
					# Menu is active, handle selection
					if display.pet_cursor == 0: 
						display.pet.feed()
					elif display.pet_cursor == 1: 
						display.pet.play()
					elif display.pet_cursor == 2:
						# Back option: clean up state and return
						pet_menu_active = False
						if view_stack:
							state = view_stack.pop()
							current_view = state['view']
						else:
							current_view = "main_menu"
					
					# Close menu after any selection
					pet_menu_active = False

			# Navigation within the pet menu
			if pet_menu_active:
				if btn[1]: # Up
					btn[1] = False
					display.pet_cursor = (display.pet_cursor - 1) % 3
				if btn[3]: # Down
					btn[3] = False
					display.pet_cursor = (display.pet_cursor + 1) % 3

			# The Pet class now handles its own rendering entirely
			display.pet.draw(display.device, font, display.pet_cursor, pet_menu_active)

		elif current_view == "about":
			if btn[1] or btn[2] or btn[3]:
				btn[1] = btn[2] = btn[3] = False
				current_view = "main_menu"
			display.draw_about()

		time.sleep(0.05)
except KeyboardInterrupt:
	GPIO.cleanup()