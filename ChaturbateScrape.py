import tkinter as tk
from tkinter import ttk, messagebox
import threading
import requests
import re
import json
import time
import os
import pyperclip
from datetime import datetime
from urllib.parse import urljoin, urlparse

# === CONFIGURATION ===
CHECK_INTERVAL = 1
RETRY_TIMEOUT = 30  # seconds
MAX_RETRIES = 5
HEADERS = {"User-Agent": "Mozilla/5.0"}

class StreamDownloader(threading.Thread):
    def __init__(self, url, gui):
        super().__init__(daemon=True)
        self.url = url
        self.username = extract_username_from_url(url)
        self.gui = gui
        self.running = True
        self.retries = 0
        self.last_index = -1
        self.current_index = -1
        self.folder = None

    def run(self):
        while self.running and self.retries < MAX_RETRIES:
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

        if self.retries >= MAX_RETRIES:
            self.gui.update_status(self.username, "Stream ended")

    def download_loop(self, base_url, start_index):
        self.gui.update_status(self.username, "Downloading")
        start_time = time.time()
        current_index = start_index
        downloaded = set()

        while self.running:
            self.current_index = current_index
            ts_url = f"{base_url}{current_index}.ts"
            ts_path = os.path.join(self.folder, f"{current_index:06d}.ts")
            try:
                resp = requests.get(ts_url, headers=HEADERS, timeout=10, stream=True)
                if resp.status_code == 200:
                    with open(ts_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    downloaded.add(current_index)
                    self.gui.update_segment(self.username, current_index)
                    current_index += 1
                    start_time = time.time()
                else:
                    time.sleep(CHECK_INTERVAL)
            except:
                time.sleep(CHECK_INTERVAL)

            if time.time() - start_time > RETRY_TIMEOUT:
                raise Exception("Retry timeout")

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
    print("[*] Fetching .m3u8 playlist...")
    res = requests.get(m3u8_url, headers=HEADERS)
    res.raise_for_status()
    lines = res.text.strip().splitlines()

    chunklists = [line for line in lines if line.startswith("chunklist_") and line.endswith(".m3u8")]
    if chunklists:
        selected_chunklist = chunklists[-1]
        print(f"[+] Found sub-playlist: {selected_chunklist}")
        chunklist_url = urljoin(m3u8_url.rsplit("/", 1)[0] + "/", selected_chunklist)

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
    date_str = datetime.now().strftime("%Y-%m-%d %H-%M")
    folder = os.path.join("Downloads", username, date_str)
    os.makedirs(folder, exist_ok=True)
    return folder

class DownloaderGUI:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Stream Downloader")
        self.downloaders = {}

        frame = tk.Frame(self.window)
        frame.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(frame, columns=("username", "status", "segment"), show="headings")
        self.tree.heading("username", text="Username")
        self.tree.heading("status", text="Status")
        self.tree.heading("segment", text="Current Segment")
        self.tree.column("username", width=150)
        self.tree.column("status", width=120)
        self.tree.column("segment", width=120)
        self.tree.pack(fill=tk.BOTH, expand=True)

        input_frame = tk.Frame(self.window)
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.entry = tk.Entry(input_frame)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.add_button = tk.Button(input_frame, text="Add Stream", command=self.add_stream)
        self.add_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(self.window, text="Clear Finished Tasks", command=self.clear_finished)
        self.clear_button.pack(pady=(0, 10))

    def add_stream(self):
        url = self.entry.get().strip()
        if not url:
            url = pyperclip.paste().strip()
        if not url.startswith("http"):
            messagebox.showerror("Invalid URL", "Please enter a valid stream URL.")
            return

        username = extract_username_from_url(url)
        if username in self.downloaders:
            messagebox.showinfo("Already Added", f"Stream for '{username}' is already being downloaded.")
            return

        self.tree.insert("", "end", iid=username, values=(username, "Initializing", "-"))
        downloader = StreamDownloader(url, self)
        self.downloaders[username] = downloader
        downloader.start()

    def update_status(self, username, status):
        if username in self.tree.get_children():
            self.tree.set(username, "status", status)

    def update_segment(self, username, segment):
        if username in self.tree.get_children():
            self.tree.set(username, "segment", str(segment))

    def clear_finished(self):
        for item in self.tree.get_children():
            status = self.tree.set(item, "status")
            if status == "Stream ended":
                self.tree.delete(item)
                del self.downloaders[item]

    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    app = DownloaderGUI()
    app.run()
