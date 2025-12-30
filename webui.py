#Vibe coded webui stuff

from flask import Flask, render_template, jsonify, request, url_for
import os
import threading
import time

class Mp3PlayerWebUI:
    def __init__(self, host='0.0.0.0', port=5000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.player = None  
        self.status_data = {
            "status": "stopped",
            "title": "No song loaded",
            "artist": "Unknown Artist",
            "album": "Unknown Album",
            "position": 0,
            "duration": 0,
            "shuffle": False,
            "volume": 100,
            "file_path": ""
        }
        self._setup_routes()
        self._create_template_files()
        
    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.app.route('/api/status', methods=['GET'])
        def get_status():
            return jsonify(self.status_data)
        
        @self.app.route('/api/playlist', methods=['GET'])
        def get_playlist():
            if self.player:
                return jsonify(self.player.get_playlist_data())
            return jsonify([])

        @self.app.route('/api/play_index', methods=['POST'])
        def play_index():
            if self.player:
                data = request.get_json()
                idx = data.get('index')
                if idx is not None:
                    self.player.play_index(int(idx))
                    return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 400

        @self.app.route('/api/play_filtered', methods=['POST'])
        def play_filtered():
            if self.player:
                data = request.get_json()
                category = data.get('category') 
                value = data.get('value')
                self.player.filter_playlist(category, value)
                return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 400

        @self.app.route('/api/play', methods=['POST'])
        def play():
            if self.player: self.player.play(); return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 500
            
        @self.app.route('/api/pause', methods=['POST'])
        def pause():
            if self.player: self.player.pause(); return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 500
            
        @self.app.route('/api/next', methods=['POST'])
        def next_track():
            if self.player: self.player.next_track(); return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 500
            
        @self.app.route('/api/prev', methods=['POST'])
        def prev_track():
            if self.player: self.player.previous_track(); return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 500
        
        @self.app.route('/api/shuffle', methods=['POST'])
        def toggle_shuffle():
            if self.player:
                new_state = self.player.toggle_shuffle()
                return jsonify({"status": "success", "shuffle": new_state})
            return jsonify({"status": "error"}), 500
            
        @self.app.route('/api/volume', methods=['POST'])
        def set_volume():
            if self.player:
                data = request.get_json()
                vol = int(data.get('volume', 100))
                self.player.set_volume(vol)
                return jsonify({"status": "success"})
            return jsonify({"status": "error"}), 400

    def set_player(self, player_instance):
        self.player = player_instance
        
    def start(self):
        thread = threading.Thread(target=self._run_server)
        thread.daemon = True
        thread.start()
        
    def _run_server(self):
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)
        
    def update_status(self, status_data):
        if status_data is None: return
        for key, value in status_data.items():
            if key in self.status_data:
                if key == "is_playing":
                    self.status_data["status"] = "playing" if value else "paused"
                else:
                    self.status_data[key] = value

    def _create_template_files(self):
        if not os.path.exists('templates'): os.makedirs('templates')
        with open('templates/index.html', 'w') as f:
            f.write('''
<!DOCTYPE html>
<html>
<head>
    <title>MintP3 Web Control</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: white; display: flex; flex-direction: column; align-items: center; padding: 20px; }
        .player-card { background: #1e1e1e; padding: 30px; border-radius: 16px; width: 450px; text-align: center; margin-bottom: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.5); box-sizing: border-box; }
        .status-badge { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; background: #333; padding: 4px 8px; border-radius: 4px; margin-bottom: 15px; display: inline-block; }
        .song-title { font-size: 1.4rem; font-weight: bold; margin-bottom: 5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .artist-name { font-size: 1rem; color: #b3b3b3; margin-bottom: 20px; }
        .progress-container { width: 100%; height: 6px; background: #404040; border-radius: 3px; margin-bottom: 10px; cursor: pointer; }
        .progress-bar { height: 100%; background: #1db954; width: 0%; border-radius: 3px; }
        .controls { display: flex; justify-content: center; align-items: center; gap: 20px; margin-bottom: 25px; }
        .btn { background: none; border: none; color: white; cursor: pointer; padding: 10px; }
        .btn:hover { color: #1db954; }
        .btn-play { background: white; color: black; width: 50px; height: 50px; border-radius: 25px; display: flex; align-items: center; justify-content: center; }
        .btn.active { color: #1db954; }
        
        .browser-container { background: #1e1e1e; border-radius: 16px; width: 450px; height: 400px; display: flex; flex-direction: column; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.5); box-sizing: border-box; }
        .browser-header { padding: 15px; background: #282828; display: grid; grid-template-columns: 80px 1fr 80px; align-items: center; border-bottom: 1px solid #333; }
        .back-btn { background: #444; border: none; color: white; padding: 5px 12px; border-radius: 4px; cursor: pointer; font-size: 0.8rem; justify-self: start; }
        .breadcrumb { font-size: 0.9rem; color: #1db954; font-weight: bold; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        .browser-list { flex: 1; overflow-y: auto; }
        .list-item { display: flex; align-items: center; padding: 12px 15px; border-bottom: 1px solid #282828; cursor: pointer; transition: background 0.2s; }
        .list-item:hover { background: #333; }
        .list-item.active { color: #1db954; font-weight: bold; }
        .item-text { flex: 1; font-size: 0.9rem; margin-left: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        
        .quick-play { background: rgba(29, 185, 84, 0.15); color: #1db954; border: none; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; flex-shrink: 0; }
        .quick-play:hover { background: #1db954; color: white; }
        .play-all-item { background: #252525; color: #1db954; font-weight: bold; }

        input[type=range] { width: 100%; -webkit-appearance: none; background: transparent; }
        input[type=range]::-webkit-slider-runnable-track { height: 4px; background: #404040; border-radius: 2px; }
        input[type=range]::-webkit-slider-thumb { height: 12px; width: 12px; border-radius: 50%; background: #ffffff; -webkit-appearance: none; margin-top: -4px; }
    </style>
</head>
<body>
    <div class="player-card">
        <div id="status-badge" class="status-badge">Stopped</div>
        <div class="song-title" id="title">No song loaded</div>
        <div class="artist-name" id="artist">...</div>
        <div class="progress-container"><div class="progress-bar" id="progress"></div></div>
        <div class="controls">
            <button id="shuffle-btn" class="btn" onclick="api('shuffle')">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 3 21 3 21 8"></polyline><line x1="4" y1="20" x2="21" y2="3"></line><polyline points="21 16 21 21 16 21"></polyline><line x1="15" y1="15" x2="21" y2="21"></line><line x1="4" y1="4" x2="9" y2="9"></line></svg>
            </button>
            <button class="btn" onclick="api('prev')">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><polygon points="19 20 9 12 19 4 19 20"></polygon><line x1="5" y1="19" x2="5" y2="5" stroke="currentColor" stroke-width="2"></line></svg>
            </button>
            <button class="btn btn-play" onclick="togglePlay()">
                <svg id="play-icon" width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            </button>
            <button class="btn" onclick="api('next')">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 4 15 12 5 20 5 4"></polygon><line x1="19" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="2"></line></svg>
            </button>
        </div>
        <input type="range" id="vol-slider" min="0" max="100" oninput="setVol(this.value)">
    </div>

    <div class="browser-container">
        <div class="browser-header">
            <button class="back-btn" id="back-btn" onclick="goBack()">Back</button>
            <span class="breadcrumb" id="breadcrumb">Artists</span>
            <div></div> 
        </div>
        <div class="browser-list" id="browser-list"></div>
    </div>

    <script>
        let fullPlaylist = [];
        let viewStack = [{ type: 'artists', filter: null, label: 'Artists' }];
        let currentMrl = "";
        let isPlayingGlobal = false;

        async function api(path, body=null) {
            const res = await fetch('/api/'+path, { 
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body || {})
            });
            update();
            return await res.json();
        }

        async function togglePlay() {
            const res = await fetch('/api/status');
            const data = await res.json();
            const currentlyPlaying = data.status.toLowerCase().includes('playing');
            await api(currentlyPlaying ? 'pause' : 'play');
        }

        async function update() {
            const res = await fetch('/api/status');
            const data = await res.json();
            document.getElementById('title').innerText = data.title;
            document.getElementById('artist').innerText = data.artist;
            document.getElementById('status-badge').innerText = data.status;
            document.getElementById('progress').style.width = data.position + '%';
            document.getElementById('vol-slider').value = data.volume;
            isPlayingGlobal = data.status.toLowerCase().includes('playing');
            currentMrl = data.file_path;
            document.getElementById('shuffle-btn').classList.toggle('active', data.shuffle);
            document.getElementById('play-icon').innerHTML = isPlayingGlobal ? 
                '<rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect>' : 
                '<polygon points="5 3 19 12 5 21 5 3"></polygon>';
            renderBrowser();
        }

        async function loadData() {
            const res = await fetch('/api/playlist');
            fullPlaylist = await res.json();
            renderBrowser();
        }

        function goBack() {
            if (viewStack.length > 1) {
                viewStack.pop();
                renderBrowser();
            }
        }

        function renderBrowser() {
            const currentView = viewStack[viewStack.length - 1];
            const list = document.getElementById('browser-list');
            const breadcrumb = document.getElementById('breadcrumb');
            const backBtn = document.getElementById('back-btn');
            
            list.innerHTML = '';
            breadcrumb.innerText = currentView.label;
            backBtn.style.visibility = viewStack.length > 1 ? 'visible' : 'hidden';

            if (currentView.type === 'artists') {
                const playAll = document.createElement('div');
                playAll.className = 'list-item play-all-item';
                playAll.innerHTML = `
                    <div class="quick-play" style="background:#1db954; color:white;">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                    </div>
                    <div class="item-text">Play All Songs</div>
                `;
                playAll.onclick = () => quickPlay(null, null);
                list.appendChild(playAll);

                const artists = [...new Set(fullPlaylist.map(s => s.artist))].sort();
                artists.forEach(a => createItem(a, () => {
                    viewStack.push({ type: 'albums', filter: a, label: a });
                    renderBrowser();
                }, 'artist', a));
            } 
            else if (currentView.type === 'albums') {
                const albums = [...new Set(fullPlaylist.filter(s => s.artist === currentView.filter).map(s => s.album))].sort();
                albums.forEach(al => createItem(al, () => {
                    viewStack.push({ type: 'songs', filter: al, label: al });
                    renderBrowser();
                }, 'album', al));
            } 
            else if (currentView.type === 'songs') {
                const songs = fullPlaylist.filter(s => s.album === currentView.filter);
                songs.forEach(s => {
                    const div = document.createElement('div');
                    div.className = 'list-item' + (s.mrl === currentMrl ? ' active' : '');
                    div.innerHTML = `
                        <button class="quick-play" onclick="event.stopPropagation(); api('play_index', {index: ${s.index}})">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                        </button>
                        <div class="item-text">${s.title}</div>
                    `;
                    div.onclick = () => api('play_index', {index: s.index});
                    list.appendChild(div);
                });
            }
        }

        function createItem(text, onClick, category, value) {
            const list = document.getElementById('browser-list');
            const div = document.createElement('div');
            div.className = 'list-item';
            div.innerHTML = `
                <button class="quick-play" onclick="event.stopPropagation(); quickPlay('${category}', '${value.replace(/'/g, "\\\\'")}')">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                </button>
                <div class="item-text">${text}</div>
                <div style="color:#666; font-size:1.2rem; margin-left:10px;">›</div>
            `;
            div.onclick = onClick;
            list.appendChild(div);
        }

        function quickPlay(cat, val) {
            api('play_filtered', {category: cat, value: val});
        }

        function setVol(v) { api('volume', {volume: v}); }

        loadData();
        setInterval(update, 1000);
        setInterval(loadData, 10000); // Periodic data refresh
    </script>
</body>
</html>
            ''')