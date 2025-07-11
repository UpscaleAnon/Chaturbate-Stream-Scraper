import tkinter as tk
from tkinter import ttk, messagebox
import threading
import requests
import re
import json
import time
import os
import pyperclip
import subprocess
from datetime import datetime
from urllib.parse import urljoin, urlparse

from io import BytesIO

# === CONFIGURATION ===
CHECK_INTERVAL = 1
RETRY_TIMEOUT = 30  # seconds
MAX_RETRIES = 5
LIST_FILE = "list.txt"
HEADERS = {"User-Agent": "Mozilla/5.0"}
TEMP_SEGMENT_DIR = "F:/TempSegments"  # Editable temp path for segment checking
ENABLE_CORRUPTION_CHECK = 1  # 1 = enable checking, 0 = disable (Uses drive to check for corrupt segments, ideally set up a RAM disk and set path to that above)

# === ERROR PATTERNS ===
ERROR_PATTERNS = [
    r"non-existing PPS",
    r"no frame!",
    r"Invalid data found when processing input",
    r"Decode error rate",
    r"Could not open encoder",
    r"Decoding error",
    r"Task finished with error code",
    r"Terminating thread with return code",
    r"Cannot determine format of input",
]

IGNORED_PATTERNS = [
    r"non monotonically increasing dts",
    r"Nothing was written into output file",
]

def is_relevant_error(line):
    return any(re.search(p, line) for p in ERROR_PATTERNS)

def is_ignored_warning(line):
    return any(re.search(p, line) for p in IGNORED_PATTERNS)

class FFmpegWriter:
    def __init__(self, output_dir, username):
        self.output_dir = output_dir
        self.username = username
        self.start_time = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        self.output_file = os.path.join(output_dir, f"{username} [{self.start_time}].mkv")
        self.log_file = os.path.join(output_dir, f"{username} [{self.start_time}].txt")

        self.process = subprocess.Popen(
            [
                "ffmpeg", "-y", "-f", "mpegts", "-i", "pipe:0",
                "-c", "copy", self.output_file
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        self.lock = threading.Lock()
        self.segments = []
        self.corrupt_segments = []

    def write_segment(self, segment_index, ts_bytes):
        if ENABLE_CORRUPTION_CHECK:
            if not self.check_ts(segment_index, ts_bytes):
                self.corrupt_segments.append(segment_index)

        with self.lock:
            try:
                self.process.stdin.write(ts_bytes)
                self.segments.append(segment_index)
            except Exception as e:
                print(f"[FFmpegWriter] Failed to write segment {segment_index}: {e}")

    def check_ts(self, segment_index, ts_bytes):
        try:
            os.makedirs(TEMP_SEGMENT_DIR, exist_ok=True)
            temp_path = os.path.join(TEMP_SEGMENT_DIR, f"temp_{segment_index:06d}.ts")
            with open(temp_path, "wb") as temp_file:
                temp_file.write(ts_bytes)
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", temp_path, "-f", "null", "-"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True
            )
            os.remove(temp_path)
            errors = [
                line for line in result.stderr.splitlines()
                if is_relevant_error(line) and not is_ignored_warning(line)
            ]
            return not errors
        except Exception:
            return False

    def close(self):
        try:
            self.process.stdin.close()
            self.process.wait()
        except:
            pass
        self._write_log()

    def _write_log(self):
        with open(self.log_file, "w", encoding="utf-8") as f:
            if self.segments:
                f.write(f"Start segment: {self.segments[0]:06d}.ts\n")
                f.write(f"End segment:   {self.segments[-1]:06d}.ts\n")
            f.write(f"Total segments used: {len(self.segments)}\n")

            all_indices = set(range(self.segments[0], self.segments[-1] + 1))
            missing = sorted(all_indices - set(self.segments))
            if missing:
                f.write("\nMissing segments:\n")
                for m in missing:
                    f.write(f"  {m:06d}.ts\n")
            else:
                f.write("\nNo segments missing.\n")

            if ENABLE_CORRUPTION_CHECK:
                if self.corrupt_segments:
                    f.write("\nCorrupt segments:\n")
                    for s in self.corrupt_segments:
                        f.write(f"  {s:06d}.ts\n")
                else:
                    f.write("\nNo corrupt segments detected.\n")
            else:
                f.write("\nCorrupt segments checking disabled.\n")

class StreamDownloader(threading.Thread):
    def __init__(self, url, gui, infinite=False):
        super().__init__(daemon=True)
        self.url = url
        self.username = extract_username_from_url(url)
        self.gui = gui
        self.running = False
        self.retries = 0
        self.last_index = -1
        self.current_index = -1
        self.folder = None
        self.infinite = infinite

    def run(self):
        self.running = True
        while self.running and (self.infinite or self.retries < MAX_RETRIES):
            try:
                self.gui.update_status(self.username, "Fetching")
                m3u8_url = extract_hls_url(self.url)
                latest_ts_url = get_latest_ts_url(m3u8_url)
                print(f"[DEBUG] Latest TS URL: {latest_ts_url}")
                base_url, index = parse_base_and_index(latest_ts_url)

                if index <= self.last_index:
                    self.folder = get_output_folder(self.username)
                elif self.folder is None:
                    self.folder = get_output_folder(self.username)

                self.current_index = index
                self.last_index = max(self.last_index, index)
                self.download_loop(base_url, index)
                break
            except Exception as e:
                print(f"[!] Error during stream fetch for {self.username}: {e}")
                self.retries += 1
                self.gui.update_status(self.username, f"Retrying ({self.retries})")
                time.sleep(5)

        if not self.running:
            self.gui.update_status(self.username, "Stopped")
        elif not self.infinite and self.retries >= MAX_RETRIES:
            self.gui.update_status(self.username, "Stream ended")

    def download_loop(self, base_url, start_index):
        self.gui.update_status(self.username, "Downloading")
        start_time = time.time()
        current_index = start_index
        writer = FFmpegWriter(self.folder, self.username)

        try:
            while self.running:
                self.current_index = current_index
                ts_url = f"{base_url}{current_index}.ts"
                try:
                    resp = requests.get(ts_url, headers=HEADERS, timeout=10)
                    if resp.status_code == 200:
                        ts_bytes = resp.content
                        writer.write_segment(current_index, ts_bytes)
                        self.gui.update_segment(self.username, current_index)
                        current_index += 1
                        start_time = time.time()
                    else:
                        time.sleep(CHECK_INTERVAL)
                except:
                    time.sleep(CHECK_INTERVAL)

                if time.time() - start_time > RETRY_TIMEOUT:
                    raise Exception("Retry timeout")
        finally:
            writer.close()

    def stop(self):
        self.running = False

    def restart(self):
        self.stop()
        new_thread = StreamDownloader(self.url, self.gui, self.infinite)
        self.gui.replace_downloader(self.username, new_thread)
        new_thread.start()

    def toggle_infinite(self):
        self.infinite = not self.infinite
        self.gui.update_infinite(self.username, self.infinite)

def extract_hls_url(page_url):
    res = requests.get(page_url, headers=HEADERS)
    res.raise_for_status()
    html = res.text
    match = re.search(r'window\.initialRoomDossier\s*=\s*"({.+?})";', html)
    if not match:
        raise Exception("Could not find stream JSON")
    json_str = bytes(match.group(1), "utf-8").decode("unicode_escape")
    data = json.loads(json_str)
    hls_url = data.get("hls_source")
    if not hls_url:
        raise Exception("No hls_source found in JSON")
    return hls_url

def get_latest_ts_url(m3u8_url):
    res = requests.get(m3u8_url, headers=HEADERS)
    res.raise_for_status()
    lines = res.text.strip().splitlines()
    chunklists = [line for line in lines if line.startswith("chunklist_") and line.endswith(".m3u8")]
    if chunklists:
        chunklist_url = urljoin(m3u8_url.rsplit("/", 1)[0] + "/", chunklists[-1])
        res = requests.get(chunklist_url, headers=HEADERS)
        res.raise_for_status()
        lines = res.text.strip().splitlines()
        ts_files = [line for line in lines if line and not line.startswith("#")]
        if not ts_files:
            raise Exception("No .ts files found in sub-playlist")
        return urljoin(chunklist_url.rsplit("/", 1)[0] + "/", ts_files[-1])
    else:
        ts_files = [line for line in lines if line and not line.startswith("#")]
        if not ts_files:
            raise Exception("No .ts files found in playlist")
        return urljoin(m3u8_url.rsplit("/", 1)[0] + "/", ts_files[-1])

def parse_base_and_index(ts_url):
    match = re.search(r"(.+?_)(\d+)\.ts", ts_url)
    if not match:
        raise Exception("Could not parse .ts base and index")
    return match.group(1), int(match.group(2))

def extract_username_from_url(url):
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    return parts[0] if parts else "unknown"

def get_output_folder(username):
    date_str = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    folder = os.path.join("Downloads", username, date_str)
    os.makedirs(folder, exist_ok=True)
    return folder

def save_list(downloaders):
    with open(LIST_FILE, "w") as f:
        for username, downloader in downloaders.items():
            f.write(f"{downloader.url}|{int(downloader.infinite)}\n")

def load_list():
    if not os.path.exists(LIST_FILE):
        return []
    with open(LIST_FILE, "r") as f:
        return [line.strip().split("|") for line in f if line.strip()]

class DownloaderGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Stream Downloader")
        self.downloaders = {}

        frame = tk.Frame(self.window)
        frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(frame)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("username", "status", "segment", "infinite"), show="headings")
        self.tree.heading("username", text="Username")
        self.tree.heading("status", text="Status")
        self.tree.heading("segment", text="Current Segment")
        self.tree.heading("infinite", text="Infinite")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.bind("<Button-3>", self.show_context_menu)

        input_frame = tk.Frame(self.window)
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.add_button = tk.Button(input_frame, text="Add Stream", command=self.add_stream)
        self.add_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(self.window, text="Clear Finished Tasks", command=self.clear_finished)
        self.clear_button.pack()

        control_frame = tk.Frame(self.window)
        control_frame.pack(pady=(5, 10))
        tk.Button(control_frame, text="Start All", command=self.start_all).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="Stop All", command=self.stop_all).pack(side=tk.LEFT, padx=5)

        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="Stop Task", command=self.stop_task)
        self.context_menu.add_command(label="Restart Task", command=self.restart_task)
        self.context_menu.add_command(label="Toggle Infinite", command=self.toggle_infinite)

        self.load_previous_tasks()

    def load_previous_tasks(self):
        for url, infinite in load_list():
            username = extract_username_from_url(url)
            self.tree.insert("", "end", iid=username, values=(username, "Stopped", "-", "On" if infinite == "1" else "Off"))
            self.downloaders[username] = StreamDownloader(url, self, infinite == "1")

    def replace_downloader(self, username, new_downloader):
        self.downloaders[username] = new_downloader
        save_list(self.downloaders)

    def add_stream(self):
        url = self.entry.get().strip()
        if not url:
            url = pyperclip.paste().strip()
        if not url.startswith("http"):
            messagebox.showerror("Invalid URL", "Please enter a valid stream URL.")
            return

        username = extract_username_from_url(url)
        if username in self.downloaders:
            messagebox.showinfo("Already Added", f"Stream for '{username}' is already in the list.")
            return

        self.tree.insert("", "end", iid=username, values=(username, "Initializing", "-", "Off"))
        downloader = StreamDownloader(url, self)
        self.downloaders[username] = downloader
        save_list(self.downloaders)
        downloader.start()

    def update_status(self, username, status):
        if username in self.tree.get_children():
            self.tree.set(username, "status", status)

    def update_segment(self, username, segment):
        if username in self.tree.get_children():
            self.tree.set(username, "segment", str(segment))

    def update_infinite(self, username, state):
        if username in self.tree.get_children():
            self.tree.set(username, "infinite", "On" if state else "Off")
            save_list(self.downloaders)

    def clear_finished(self):
        for item in self.tree.get_children():
            status = self.tree.set(item, "status")
            if status == "Stream ended" or status == "Stopped":
                self.tree.delete(item)
                if item in self.downloaders:
                    del self.downloaders[item]
        save_list(self.downloaders)

    def start_all(self):
        for username in list(self.downloaders):
            downloader = self.downloaders[username]
            if not downloader.running:
                new_thread = StreamDownloader(downloader.url, self, downloader.infinite)
                self.replace_downloader(username, new_thread)
                new_thread.start()

    def stop_all(self):
        for downloader in self.downloaders.values():
            downloader.stop()

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def stop_task(self):
        selected = self.tree.selection()
        for item in selected:
            if item in self.downloaders:
                self.downloaders[item].stop()

    def restart_task(self):
        selected = self.tree.selection()
        for item in selected:
            if item in self.downloaders:
                self.downloaders[item].restart()

    def toggle_infinite(self):
        selected = self.tree.selection()
        for item in selected:
            if item in self.downloaders:
                self.downloaders[item].toggle_infinite()

    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    app = DownloaderGUI()
    app.run()