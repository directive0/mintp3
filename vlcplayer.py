import vlc
import time
import os
import random
import urllib.parse
from mutagen import File as MutagenFile

class VLCPlayer:
	def __init__(self):
		self.instance = vlc.Instance('--no-xlib')
		self.player = self.instance.media_player_new()
		self.stream_player = None
		self.is_streaming = False
		self.media = None
		self.length_ms = 0
		self.metadata = {}
		self.media_list = None
		self.media_list_player = None
		self.is_playlist_mode = False
		self._shuffle_enabled = False
		self.all_media_paths = []
		self.current_filter = {"category": None, "value": None}
		
	def load(self, file_path):
		self.stop_stream()
		if not os.path.exists(file_path):
			return False
		self.is_playlist_mode = False
		self.media = self.instance.media_new(file_path)
		self.player = self.instance.media_player_new()
		self.player.set_media(self.media)
		self.media.parse()
		self.length_ms = self.media.get_duration()
		self._load_metadata(file_path)
		return True

	def play_stream(self, url):
		"""Pauses local playback and starts an audio stream or M3U file."""
		if self.is_playing():
			self.pause()
		
		self.stop_stream()
		
		# Handle local M3U files
		if url.lower().endswith('.m3u') and os.path.exists(url):
			try:
				with open(url, 'r') as f:
					for line in f:
						line = line.strip()
						if line and not line.startswith('#'):
							url = line
							break
			except: pass

		self.stream_player = self.instance.media_player_new()
		stream_media = self.instance.media_new(url)
		self.stream_player.set_media(stream_media)
		self.stream_player.play()
		self.is_streaming = True
		time.sleep(0.5)
		self.update_current_song_info()
		return True

	def stop_stream(self):
		"""Stops and releases the stream player."""
		if self.stream_player:
			self.stream_player.stop()
			self.stream_player.release()
			self.stream_player = None
		self.is_streaming = False

	def get_id3_tags(self):
		if not self.is_media_loaded() and not self.is_streaming:
			return {}
		self.update_current_song_info()
		return self.metadata.copy()

	def set_shuffle(self, enable=True):
		if not self.is_playlist_mode or not self.media_list_player:
			return False
		try:
			if enable:
				current_index = self.get_current_track_index()
				shuffled_media_list = self.instance.media_list_new()
				media_items = []
				for i in range(self.media_list.count()):
					media_items.append(self.media_list.item_at_index(i))
				if current_index >= 0 and current_index < len(media_items):
					current_media = media_items.pop(current_index)
					random.shuffle(media_items)
					media_items.insert(0, current_media)
				else:
					random.shuffle(media_items)
				for media in media_items:
					shuffled_media_list.add_media(media)
				self.media_list = shuffled_media_list
				self.media_list_player.set_media_list(shuffled_media_list)
				if self.is_playing():
					self.media_list_player.play()
			return True
		except:
			return False

	def sort_playlist_alphabetically(self):
		if not self.is_playlist_mode or not self.media_list_player:
			return False
		try:
			current_index = self.get_current_track_index()
			current_media = None
			if current_index >= 0:
				current_media = self.media_list.item_at_index(current_index)
			media_items = []
			for i in range(self.media_list.count()):
				media = self.media_list.item_at_index(i)
				media.parse()
				title = media.get_meta(vlc.Meta.Title)
				if not title:
					mrl = media.get_mrl()
					try:
						if mrl.startswith('file://'):
							path = urllib.parse.unquote(mrl[7:])
							title = os.path.basename(path)
						else:
							title = os.path.basename(urllib.parse.unquote(mrl))
					except:
						title = mrl
				media_items.append((title.lower(), media))
			media_items.sort(key=lambda x: x[0])
			sorted_media_list = self.instance.media_list_new()
			current_media_pos = -1
			if current_media:
				current_mrl = current_media.get_mrl()
				for i, (_, media) in enumerate(media_items):
					if media.get_mrl() == current_mrl:
						current_media_pos = i
						break
			if current_media_pos >= 0:
				media_items = media_items[current_media_pos:] + media_items[:current_media_pos]
			for _, media in media_items:
				sorted_media_list.add_media(media)
			was_playing = self.is_playing()
			position = self.get_time()
			self.media_list = sorted_media_list
			self.media_list_player.set_media_list(sorted_media_list)
			if was_playing:
				self.media_list_player.play()
				if current_media_pos == 0:
					self.seek(position)
			self._shuffle_enabled = False
			return True
		except:
			return False

	def set_music_dir(self, path):
		"""Resolves and stores the music directory path."""
		import os
		self.music_dir = os.path.abspath(os.path.expanduser(path))

	def rescan_library(self, path=None):
		"""Rescans the library using the stored path if none is provided."""
		target_path = path if path else self.music_dir
		self.stop()
		return self.play_directory(target_path)

	def is_media_loaded(self):
		if self.is_streaming:
			return self.stream_player is not None
		if self.is_playlist_mode:
			return self.media_list is not None and self.media_list.count() > 0
		return self.media is not None

	def has_just_finished(self):
		"""Returns True if the current track has reached the end (Stopped)."""
		active_player = self.stream_player if self.is_streaming else self.player
		return active_player.get_state() == vlc.State.Ended or active_player.get_state() == vlc.State.Stopped

	def play_directory(self, directory_path):
		self.stop_stream()
		if not os.path.isdir(directory_path):
			return False
		self.media_list = self.instance.media_list_new()
		self.is_playlist_mode = True
		self.all_media_paths = []
		files_added = 0
		audio_extensions = ['.mp3', '.wav', '.flac', '.ogg', '.aac', '.m4a', '.wma', '.aiff', '.alac']
		def add_files_from_directory(dir_path):
			nonlocal files_added
			try:
				for item in sorted(os.listdir(dir_path)):
					if item.startswith('.'): continue
					item_path = os.path.join(dir_path, item)
					if os.path.isfile(item_path):
						if os.path.splitext(item_path)[1].lower() in audio_extensions:
							self.all_media_paths.append(item_path)
							media = self.instance.media_new(item_path)
							self.media_list.add_media(media)
							files_added += 1
					elif os.path.isdir(item_path):
						add_files_from_directory(item_path)
			except: pass
			
		add_files_from_directory(directory_path)
		if files_added == 0: return False
		self.media_list_player = self.instance.media_list_player_new()
		self.media_list_player.set_media_list(self.media_list)
		self.player = self.media_list_player.get_media_player()
		self.media_list_player.play()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
		
	def update_current_song_info(self):
		song_info = self.get_current_song_info()
		if song_info:
			self.metadata = {
				'title': song_info.get('title', 'Unknown'),
				'artist': song_info.get('artist', 'Unknown'),
				'album': song_info.get('album', 'Unknown'),
				'year': song_info.get('year', ''),
				'genre': song_info.get('genre', ''),
				'length': self.get_length_formatted()
			}
			self.length_ms = int(song_info.get('duration', 0) * 1000)
			return song_info
		return None

	def get_current_song_info(self):
		if self.is_streaming and self.stream_player:
			media_player = self.stream_player
		elif self.is_playlist_mode and self.media_list_player:
			media_player = self.media_list_player.get_media_player()
		else:
			media_player = self.player
			
		if not media_player: return None
		media = media_player.get_media()
		if not media: return None
		
		# Ensure we parse to get latest stream metadata
		if self.is_streaming:
			media.parse_with_options(vlc.MediaParseFlag.network, 0)
		else:
			media.parse()
		
		# Streaming metadata often uses Meta.NowPlaying
		title = media.get_meta(vlc.Meta.NowPlaying) or media.get_meta(vlc.Meta.Title)
		artist = media.get_meta(vlc.Meta.Artist)
		
		if self.is_streaming and title and not artist and " - " in title:
			parts = title.split(" - ", 1)
			artist = parts[0]
			title = parts[1]

		song_info = {
			"title": title or "Stream",
			"artist": artist or "Internet Radio",
			"album": media.get_meta(vlc.Meta.Album) or "Live Stream",
			"year": media.get_meta(vlc.Meta.Date),
			"genre": media.get_meta(vlc.Meta.Genre),
			"track_number": media.get_meta(vlc.Meta.TrackNumber),
			"duration": media_player.get_length() / 1000,
			"current_time": media_player.get_time() / 1000,
			"file_path": media.get_mrl(),
			"is_playing": media_player.is_playing(),
			"position": self.get_progress(),
			"status": str(media_player.get_state()),
			"shuffle": self._shuffle_enabled,
			"volume": self.get_volume()
		}
		return song_info
		
		# Streaming metadata often uses Meta.NowPlaying
		title = media.get_meta(vlc.Meta.NowPlaying) or media.get_meta(vlc.Meta.Title)
		artist = media.get_meta(vlc.Meta.Artist)
		
		# If it's a stream and NowPlaying contains "Artist - Title", try to separate them
		if self.is_streaming and title and not artist and " - " in title:
			parts = title.split(" - ", 1)
			artist = parts[0]
			title = parts[1]

		song_info = {
			"title": title,
			"artist": artist,
			"album": media.get_meta(vlc.Meta.Album),
			"year": media.get_meta(vlc.Meta.Date),
			"genre": media.get_meta(vlc.Meta.Genre),
			"track_number": media.get_meta(vlc.Meta.TrackNumber),
			"duration": media_player.get_length() / 1000,
			"current_time": media_player.get_time() / 1000,
			"file_path": media.get_mrl(),
			"is_playing": media_player.is_playing(),
			"position": self.get_progress(),
			"status": str(media_player.get_state()),
			"shuffle": self._shuffle_enabled,
			"volume": self.get_volume()
		}
		return song_info

	def _load_metadata(self, file_path):
		self.metadata = {'title': os.path.basename(file_path), 'artist': 'Unknown', 'album': 'Unknown', 'year': '', 'genre': '', 'length': self.get_length_formatted()}
		try:
			self.metadata['title'] = self.media.get_meta(vlc.Meta.Title) or self.metadata['title']
			self.metadata['artist'] = self.media.get_meta(vlc.Meta.Artist) or self.metadata['artist']
			self.metadata['album'] = self.media.get_meta(vlc.Meta.Album) or self.metadata['album']
			self.metadata['genre'] = self.media.get_meta(vlc.Meta.Genre) or self.metadata['genre']
			self.metadata['year'] = self.media.get_meta(vlc.Meta.Date) or self.metadata['year']
			if any(v == 'Unknown' for k,v in self.metadata.items() if k != 'length'):
				try:
					audio_file = MutagenFile(file_path, easy=True)
					if audio_file:
						if 'title' in audio_file: self.metadata['title'] = audio_file['title'][0]
						if 'artist' in audio_file: self.metadata['artist'] = audio_file['artist'][0]
						if 'album' in audio_file: self.metadata['album'] = audio_file['album'][0]
						if 'date' in audio_file: self.metadata['year'] = audio_file['date'][0]
						if 'genre' in audio_file: self.metadata['genre'] = audio_file['genre'][0]
				except: pass
		except: pass

	def get_unique_metadata(self, category, artist_filter=None, album_filter=None):
		"""Returns unique metadata items, optionally filtered by artist or album."""
		items = set()
		for path in self.all_media_paths:
			try:
				m = self.instance.media_new(path)
				m.parse()
				if artist_filter:
					if (m.get_meta(vlc.Meta.Artist) or "Unknown") != artist_filter: continue
				if album_filter:
					if (m.get_meta(vlc.Meta.Album) or "Unknown") != album_filter: continue
				if category == "artist":
					val = m.get_meta(vlc.Meta.Artist)
				elif category == "album":
					val = m.get_meta(vlc.Meta.Album)
				elif category == "song":
					val = m.get_meta(vlc.Meta.Title)
					if not val: val = os.path.basename(path)
				items.add(val if val else "Unknown")
			except: continue
		return sorted(list(items))

	def filter_playlist(self, category, value, artist_context=None):
		self.stop_stream()
		self.current_filter = {"category": category, "value": value}
		self.media_list_player.stop()
		new_list = self.instance.media_list_new()
		for path in self.all_media_paths:
			m = self.instance.media_new(path)
			m.parse()
			match = False
			if category is None:
				match = True
			elif category == "artist":
				match = (m.get_meta(vlc.Meta.Artist) or "Unknown") == value
			elif category == "album":
				album_match = (m.get_meta(vlc.Meta.Album) or "Unknown") == value
				artist_match = True
				if artist_context:
					artist_match = (m.get_meta(vlc.Meta.Artist) or "Unknown") == artist_context
				match = album_match and artist_match
			elif category == "song":
				meta_val = m.get_meta(vlc.Meta.Title) or os.path.basename(path)
				match = meta_val == value
			if match:
				new_list.add_media(m)
		self.media_list = new_list
		self.media_list_player.set_media_list(self.media_list)
		self.media_list_player.play()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
	
	def play(self):
		if self.is_streaming and self.stream_player:
			self.stream_player.play()
			return True
		if not self.is_media_loaded(): return False
		if self.is_playlist_mode: self.media_list_player.play()
		else: self.player.play()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
	
	def pause(self):
		if self.is_streaming and self.stream_player:
			self.stream_player.pause()
		elif self.is_playlist_mode: 
			self.media_list_player.pause()
		else: 
			self.player.pause()
		return True
	
	def stop(self):
		self.stop_stream()
		if self.is_playlist_mode: self.media_list_player.stop()
		else: self.player.stop()
		return True
	
	def toggle_pause(self):
		self.pause()
		time.sleep(0.1)
		return self.is_playing()
	
	def toggle_play(self):
		if self.is_playing():
			self.pause()
			return False
		else:
			return self.play()

	def toggle_shuffle(self):
		if not self.is_playlist_mode or not self.media_list_player: return None
		self._shuffle_enabled = not self._shuffle_enabled
		self.set_shuffle(self._shuffle_enabled)
		return self._shuffle_enabled

	def is_paused(self):
		active_player = self.stream_player if self.is_streaming else self.player
		return active_player.get_state() == vlc.State.Paused

	def is_playing(self):
		if self.is_streaming and self.stream_player:
			return bool(self.stream_player.is_playing())
		return bool(self.player.is_playing())

	def get_state(self):
		active_player = self.stream_player if (self.is_streaming and self.stream_player) else self.player
		s = active_player.get_state()
		if s == vlc.State.Playing: return "Playing"
		elif s == vlc.State.Paused: return "Paused"
		elif s == vlc.State.Stopped: return "Stopped"
		elif s == vlc.State.Ended: return "Ended"
		return "Unknown"
	
	def next_track(self):
		if self.is_streaming or not self.is_playlist_mode: return False
		self.media_list_player.next()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
			
	def previous_track(self):
		if self.is_streaming or not self.is_playlist_mode: return False
		self.media_list_player.previous()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
	
	def get_time(self):
		active_player = self.stream_player if self.is_streaming else self.player
		return active_player.get_time()

	def get_current_time(self): 
		return self.get_time() / 1000

	def get_duration(self):
		active_player = self.stream_player if self.is_streaming else self.player
		length = active_player.get_length()
		return length / 1000 if length > 0 else 0

	def get_length(self):
		active_player = self.stream_player if self.is_streaming else self.player
		return active_player.get_length()

	def get_length_formatted(self):
		ms = self.get_length()
		if ms <= 0: return "Live" if self.is_streaming else "00:00"
		sec = ms // 1000
		return f"{sec // 60:02d}:{sec % 60:02d}"

	def get_progress(self):
		length = self.get_length()
		if length <= 0: return 0
		return (self.get_time() / length) * 100

	def seek(self, pos):
		if not self.is_streaming:
			self.player.set_time(pos)

	def set_volume(self, vol):
		active_player = self.stream_player if self.is_streaming else self.player
		active_player.audio_set_volume(vol)

	def get_volume(self):
		active_player = self.stream_player if self.is_streaming else self.player
		return active_player.audio_get_volume()

	def get_current_track_index(self):
		if self.is_streaming or not self.is_playlist_mode or not self.media_list_player: return -1
		m = self.player.get_media()
		if not m: return -1
		mrl = m.get_mrl()
		for i in range(self.media_list.count()):
			if self.media_list.item_at_index(i).get_mrl() == mrl: return i
		return -1

	def get_playlist_data(self):
		if not self.is_playlist_mode or not self.media_list:
			return []
		playlist = []
		for i in range(self.media_list.count()):
			m = self.media_list.item_at_index(i)
			m.parse_with_options(vlc.MediaParseFlag.local, 0)
			mrl = m.get_mrl()
			try:
				if mrl.startswith('file://'):
					filename = os.path.basename(urllib.parse.unquote(mrl[7:]))
				else:
					filename = os.path.basename(urllib.parse.unquote(mrl))
			except:
				filename = "Unknown File"
			playlist.append({
				"index": i,
				"title": m.get_meta(vlc.Meta.Title) or filename,
				"artist": m.get_meta(vlc.Meta.Artist) or "Unknown Artist",
				"album": m.get_meta(vlc.Meta.Album) or "Unknown Album",
				"mrl": mrl
			})
		return playlist

	def play_index(self, index):
		self.stop_stream()
		if not self.is_playlist_mode or not self.media_list_player:
			return False
		self.media_list_player.play_item_at_index(index)
		time.sleep(0.5)
		self.update_current_song_info()
		return True

	def play_playlist_file(self, playlist_path):
		"""Loads an M3U playlist file for full track navigation."""
		self.stop()
		if not os.path.exists(playlist_path):
			return False
		
		self.media_list = self.instance.media_list_new()
		self.is_playlist_mode = True
		self.all_media_paths = []
		files_added = 0
		
		try:
			with open(playlist_path, 'r') as f:
				for line in f:
					line = line.strip()
					if line and not line.startswith('#'):
						# CLEAN THE PATH: Remove file:// and decode URL characters
						if line.startswith('file://'):
							line = urllib.parse.unquote(line[7:])
						
						# Handle relative paths vs absolute paths
						path = line if os.path.isabs(line) else os.path.join(self.music_dir, line)
						
						if os.path.exists(path):
							self.all_media_paths.append(path)
							media = self.instance.media_new(path)
							self.media_list.add_media(media)
							files_added += 1
		except Exception as e:
			print(f"Error parsing playlist: {e}")
			return False
			
		if files_added == 0:
			return False
			
		self.media_list_player = self.instance.media_list_player_new()
		self.media_list_player.set_media_list(self.media_list)
		self.player = self.media_list_player.get_media_player()
		self.media_list_player.play()
		time.sleep(0.5)
		self.update_current_song_info()
		return True
	
	def release(self):
		self.stop_stream()
		if self.is_playlist_mode and self.media_list_player:
			self.media_list_player.release()
		if self.player:
			self.player.release()
		if self.instance:
			self.instance.release()