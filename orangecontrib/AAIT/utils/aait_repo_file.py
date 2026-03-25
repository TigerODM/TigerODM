#---------------------------------------------------------------------------------------------
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import posixpath
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests


try:
    from AnyQt.QtCore import Qt, QThread, QObject, Signal
    from AnyQt.QtWidgets import (
        QApplication,
        QDialog,
        QVBoxLayout,
        QLabel,
        QProgressBar,
        QTextEdit,
        QPushButton,
        QHBoxLayout,
    )
except Exception:
    QApplication = None
    QDialog = object
    Qt = None
    QThread = None
    QObject = object
    Signal = None


import json
import zipfile
from bs4 import BeautifulSoup
try:
    from ..utils import MetManagement
except:
    from Orange.widgets.orangecontrib.AAIT.utils import MetManagement



def generate_listing_json(directory_to_list):
    """
    generate a file file_info.json  with size of file in directory
    for low level devellopper only
    -> use create_index_file
    """
    output_json_file = directory_to_list+'/files_info.json'
    if os.path.isfile(output_json_file):
        os.remove(output_json_file)

    def list_files_recursive(directory):
        files_info = {}

        for root, dirs, files in os.walk(directory):
            for file in files:

                file_path = os.path.join(root, file).replace("\\","/")
                file_size = os.path.getsize(file_path)
                file_path=file_path[len(directory)+1:]
                files_info[file_path]=file_size

        return files_info

    def save_to_json(data, output_file):
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    files_info = list_files_recursive(directory_to_list)
    save_to_json(files_info, output_json_file)
    return files_info

def add_file_to_zip_file(folder,file_in,zip_file):
    """
    folder : a point to start relative path
    file in : a file to add to zip file
    zip file : destination zip file
    for exemple I want to add C:/dir1/dir2/dir3/qwerty.txt to
    C:/dir1//dir2/example.zip and index dir3/qwerty.txt
    folder = C:/dir1/
    file_in=C:/dir1/dir2/dir3/qwerty.txt
    zip_file  C:/dir2/example.zip
    """
    path_in=folder+file_in
    with open(path_in, 'rb') as f:
        contenu = f.read()
    with zipfile.ZipFile(zip_file, 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(file_in, contenu)

def create_index_file(in_repo_file,out_repo_file="a_ignorer"):
    """
    delete files_info.json and regenerate it
    with file contain a dictionnary filename:filesize
    out_repo_file is not used
    """
    if not os.path.isfile(in_repo_file):
        raise Exception("The specified path is not a file "+in_repo_file)
    if 0!=MetManagement.get_size(in_repo_file):
        raise Exception("The file " + in_repo_file+ " need to be empty to use this functions")
    print(MetManagement.get_size(in_repo_file))
    folder_to_process=os.path.dirname(in_repo_file).replace("\\","/")
    file_info=generate_listing_json(folder_to_process)
    print(file_info)
    return

def decode(repo_file,file_to_read):
    """
    be carrefull with big file (ram saturation)
    return containt of a zipped file
    """
    if not os.path.isfile(repo_file):
        return None
    file_to_read=os.path.splitext(os.path.basename(repo_file))[0]+"/"+file_to_read
    with zipfile.ZipFile(repo_file, 'r') as zip_ref:
        with zip_ref.open(file_to_read) as file:
            content = file.read()
            return content.decode('utf-8')
def decode_to_file(zip_path, target_path, output_path):
    """
    extract a file from a zip file and write it on hdd
    example : I want to extract dir1/qwerty.txt from C:/dir1/dir2/zipfile.zip to C:/dir_a/dir_b/dir1/qwerty.txt
    zip_path=C:/dir1/dir2/zipfile.zip
    target_path=dir1/qwerty.txt
    output_path=C:/dir_a/dir_b/
    """
    chunk_size = 1024 * 1024 * 100 # 100 Mo
    target_path=os.path.splitext(os.path.basename(zip_path))[0]+"/"+target_path
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        target_path = target_path.rstrip('/')
        files_to_extract = [f for f in zip_ref.namelist() if f.startswith(target_path)]

        if len(files_to_extract) == 0:
            raise FileNotFoundError(f"{target_path} not found in the archive.")

        if len(files_to_extract) == 1 and not files_to_extract[0].endswith('/'):
            # Cible est un fichier unique
            output_file_path = output_path
            os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
            with zip_ref.open(files_to_extract[0]) as source, open(output_file_path, 'wb') as target:
                #target.write(source.read())
                while True:
                    # read and write a chunk to avoid ram limitation
                    chunk = source.read(chunk_size)
                    if not chunk:
                        break
                    target.write(chunk)
        else:
            # Cible est un dossier ou plusieurs fichiers
            for file in files_to_extract:
                relative_path = os.path.relpath(file, start=target_path)
                destination_path = os.path.join(output_path, relative_path)

                if file.endswith('/'):
                    os.makedirs(destination_path, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
                    with zip_ref.open(file) as source, open(destination_path, 'wb') as target:
                        #target.write(source.read())
                        while True:
                            # read and write a chunk to avoid ram limitation
                            chunk = source.read(chunk_size)
                            if not chunk:
                                break
                            target.write(chunk)

def normalize_path(path):
    """
    Normalize paths for URLs and local usage:
    - Replaces backslashes with forward slashes .
    - Removes './' and '\\.' segments from paths.
    - Handles redundant slashes.
    """
    # Replace backslashes with slashes
    path = path.replace("\\", "/")

    # Remove any occurrences of './' or '\.'
    path = path.replace("./", "").replace("/./", "/")

    # Clean up multiple slashes (e.g., "///" -> "/")
    path = os.path.normpath(path).replace("\\", "/")

    # Remove trailing and leading slashes (if required)
    path = path.strip("/")

    return path





# ============================================================
# Helpers sécurité / chemins
# ============================================================

SKIP_FILENAMES = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
}


def should_skip_name(name: str) -> bool:
    return (name or "").strip().lower() in SKIP_FILENAMES


def normalize_child_name(href: str) -> str:
    href = href.strip()
    href = href.split("?", 1)[0].split("#", 1)[0]
    href = href.rstrip("/")
    name = posixpath.basename(href)
    name = unquote(name)
    return name.strip()


def sanitize_remote_subpath(subpath: str) -> str:
    subpath = (subpath or "").replace("\\", "/").strip()
    subpath = subpath.lstrip("/")

    norm = posixpath.normpath(subpath)
    if norm == ".":
        return ""

    if norm.startswith("../") or norm == "..":
        raise ValueError(f"Chemin distant non autorisé: {subpath!r}")

    return norm


def safe_local_path(base_dir: str | Path, relative_subpath: str) -> Path:
    base_dir = Path(base_dir).resolve()
    rel = sanitize_remote_subpath(relative_subpath)
    target = (base_dir / rel).resolve()

    try:
        target.relative_to(base_dir)
    except ValueError:
        raise ValueError(f"Chemin local hors racine interdit: {target}")

    return target


def build_full_url(base_url: str, target_subfolder: str) -> str:
    target_subfolder = sanitize_remote_subpath(target_subfolder)
    return urljoin(base_url.rstrip("/") + "/", target_subfolder)


def default_port(scheme: str) -> int | None:
    scheme = (scheme or "").lower()
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def is_same_origin(base_url: str, candidate_url: str) -> bool:
    b = urlparse(base_url)
    c = urlparse(candidate_url)
    return (
        b.scheme.lower() == c.scheme.lower()
        and b.hostname == c.hostname
        and (b.port or default_port(b.scheme)) == (c.port or default_port(c.scheme))
    )


def content_type_is_html_header(content_type: str) -> bool:
    content_type = (content_type or "").lower()
    return "text/html" in content_type or "application/xhtml+xml" in content_type


def guess_filename_from_url(url: str) -> str:
    p = urlparse(url)
    name = posixpath.basename(p.path.rstrip("/"))
    name = unquote(name)
    return name or "downloaded_file"


def format_bytes(num_bytes: int | float) -> str:
    value = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def format_seconds(seconds: float) -> str:
    if seconds < 0:
        return "?"
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h:d}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m:d}m {s:02d}s"
    return f"{s:d}s"


# ============================================================
# UI Qt
# ============================================================

class PrettyDownloadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_requested = False
        self._ui_alive = True
        self.setWindowTitle("Synchronization in progress")
        self.resize(760, 540)

        layout = QVBoxLayout(self)

        self.label_title = QLabel("<b>Remote synchronization</b>")
        self.label_title.setTextFormat(Qt.RichText if Qt else 0)
        layout.addWidget(self.label_title)

        self.label_current = QLabel("Waiting…")
        self.label_current.setWordWrap(True)
        layout.addWidget(self.label_current)

        self.label_global = QLabel("0 file processed")
        self.label_global.setWordWrap(True)
        layout.addWidget(self.label_global)

        self.label_connection = QLabel("")
        self.label_connection.setWordWrap(True)
        layout.addWidget(self.label_connection)

        self.label_speed = QLabel("Speed: 0 B/s | ETA: ?")
        self.label_speed.setWordWrap(True)
        layout.addWidget(self.label_speed)

        self.progress_file = QProgressBar()
        self.progress_file.setRange(0, 100)
        self.progress_file.setValue(0)
        layout.addWidget(self.progress_file)

        self.progress_global = QProgressBar()
        self.progress_global.setRange(0, 100)
        self.progress_global.setValue(0)
        layout.addWidget(self.progress_global)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self._on_cancel)
        btns.addWidget(self.btn_cancel)

        layout.addLayout(btns)

        self.setStyleSheet("""
            QDialog {
                background: #1f2430;
            }
            QLabel {
                color: #f0f3f6;
                font-size: 13px;
            }
            QTextEdit {
                background: #11151c;
                color: #d9e1e8;
                border: 1px solid #3a4352;
                border-radius: 8px;
                padding: 6px;
                font-family: Consolas, Menlo, monospace;
                font-size: 12px;
            }
            QProgressBar {
                border: 1px solid #3a4352;
                border-radius: 8px;
                text-align: center;
                height: 22px;
                background: #11151c;
                color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #3d8bfd;
                border-radius: 7px;
            }
            QPushButton {
                background: #2d3748;
                color: white;
                padding: 8px 14px;
                border-radius: 8px;
                border: 1px solid #4a5568;
            }
            QPushButton:hover {
                background: #3b4658;
            }
        """)

    def request_cancel(self):
        if not self._cancel_requested:
            self._cancel_requested = True
            if self._ui_alive:
                try:
                    self.log_edit.append("Cancellation requested by user.")
                except Exception:
                    pass

    def _on_cancel(self):
        self.request_cancel()
        self._ui_alive = False
        self.close()

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_requested

    @property
    def ui_alive(self) -> bool:
        return self._ui_alive

    def append_log(self, text: str):
        if not self._ui_alive:
            return
        try:
            self.log_edit.append(text)
        except Exception:
            return

    def set_current(self, text: str):
        if not self._ui_alive:
            return
        try:
            self.label_current.setText(text)
        except Exception:
            return

    def set_global_text(self, text: str):
        if not self._ui_alive:
            return
        try:
            self.label_global.setText(text)
        except Exception:
            return

    def set_connection_text(self, text: str):
        if not self._ui_alive:
            return
        try:
            self.label_connection.setText(text)
        except Exception:
            return

    def set_speed_text(self, text: str):
        if not self._ui_alive:
            return
        try:
            self.label_speed.setText(text)
        except Exception:
            return

    def set_file_progress(self, percent: int):
        if not self._ui_alive:
            return
        try:
            self.progress_file.setValue(max(0, min(100, int(percent))))
        except Exception:
            return

    def set_global_progress(self, percent: int):
        if not self._ui_alive:
            return
        try:
            self.progress_global.setValue(max(0, min(100, int(percent))))
        except Exception:
            return

    def closeEvent(self, event):
        self.request_cancel()
        self._ui_alive = False
        event.accept()

    def pump(self):
        if QApplication is not None:
            QApplication.processEvents()


# ============================================================
# Signals Qt
# ============================================================

class DownloadSignals(QObject):
    if Signal is not None:
        log = Signal(str)
        current = Signal(str)
        global_text = Signal(str)
        connection = Signal(str)
        speed = Signal(str)
        file_progress = Signal(int)
        global_progress = Signal(int)


# ============================================================
# Exceptions
# ============================================================

class DownloadCancelled(Exception):
    pass


class DownloadIntegrityError(Exception):
    pass


# ============================================================
# Thread de téléchargement
# ============================================================

class DownloadThread(QThread):
    def __init__(self, downloader, target_subfolder: str):
        super().__init__()
        self.downloader = downloader
        self.target_subfolder = target_subfolder
        self.exc = None

    def run(self):
        try:
            self.downloader.download(self.target_subfolder)
        except Exception as e:
            self.exc = e


# ============================================================
# Downloader principal
# ============================================================

class FolderServerDownloader:
    def __init__(
        self,
        base_url: str,
        local_dir: str = ".",
        session: requests.Session | None = None,
        dialog: PrettyDownloadDialog | None = None,   # uniquement pour cancel_requested
        signals: DownloadSignals | None = None,       # toutes les updates UI passent ici
        timeout: tuple[int, int] = (10, 60),
        chunk_size: int = 1024 * 512,
        verify_ssl: bool = True,
        max_redirects: int = 8,
    ):
        self.base_url = base_url.rstrip("/")
        self.local_dir = Path(local_dir).resolve()
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.verify_ssl = verify_ssl
        self.max_redirects = max_redirects

        self.max_retries = 8
        self.retry_base_delay = 2.0
        self.retry_max_delay = 30.0

        self.visited: set[str] = set()
        self.stats = {
            "files_done": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "dirs_seen": 0,
            "bytes_done": 0,
            "files_total_estimated": 0,
        }

        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "TigerODM-SafeSync/1.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.session.max_redirects = self.max_redirects

        self.dialog = dialog
        self.signals = signals
        self._last_ui_refresh = 0.0

    # -----------------------------
    # UI helpers via signals
    # -----------------------------
    def _log(self, text: str):
        print(text)
        if self.signals is not None:
            try:
                self.signals.log.emit(text)
            except Exception:
                pass

    def _set_current(self, text: str):
        if self.signals is not None:
            try:
                self.signals.current.emit(text)
            except Exception:
                pass

    def _set_connection_status(self, text: str):
        if self.signals is not None:
            try:
                self.signals.connection.emit(text)
            except Exception:
                pass

    def _update_global_ui(self):
        total = max(1, self.stats["files_total_estimated"])
        done = self.stats["files_done"] + self.stats["files_skipped"] + self.stats["files_failed"]
        pct = int((done / total) * 100)

        if self.signals is not None:
            try:
                self.signals.global_text.emit(
                    f"Done: {self.stats['files_done']} | "
                    f"Skipped: {self.stats['files_skipped']} | "
                    f"Failed: {self.stats['files_failed']} | "
                    f"Folders seen: {self.stats['dirs_seen']} | "
                    f"Transferred: {self.stats['bytes_done'] / (1024 * 1024):.2f} MB"
                )
                self.signals.global_progress.emit(pct)
            except Exception:
                pass

    def _update_file_ui(self, written: int, total_size: int, speed_bps: float):
        now = time.perf_counter()
        if now - self._last_ui_refresh < 0.08:
            return
        self._last_ui_refresh = now

        if self.signals is None:
            return

        try:
            if total_size > 0:
                pct = int((written / total_size) * 100)
                remaining = max(0, total_size - written)
                eta = remaining / speed_bps if speed_bps > 0 else -1
                self.signals.file_progress.emit(pct)
                self.signals.speed.emit(
                    f"Speed: {format_bytes(speed_bps)}/s | "
                    f"{format_bytes(written)} / {format_bytes(total_size)} | "
                    f"ETA: {format_seconds(eta)}"
                )
            else:
                pseudo = min(99, (written // max(1, self.chunk_size)) % 100)
                self.signals.file_progress.emit(pseudo)
                self.signals.speed.emit(
                    f"Speed: {format_bytes(speed_bps)}/s | "
                    f"{format_bytes(written)} transferred | "
                    f"ETA: ?"
                )
        except Exception:
            pass

    def _check_cancel(self):
        if self.dialog and self.dialog.cancel_requested:
            raise DownloadCancelled("Operation cancelled by user.")

    # -----------------------------
    # Résilience réseau
    # -----------------------------
    def _is_transient_network_error(self, exc: Exception) -> bool:
        transient_types = (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )
        if isinstance(exc, transient_types):
            return True

        if isinstance(exc, requests.HTTPError):
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (408, 425, 429, 500, 502, 503, 504):
                return True

        return False

    def _retry_sleep(self, attempt_index: int):
        delay = min(self.retry_base_delay * (2 ** max(0, attempt_index - 1)), self.retry_max_delay)
        self._set_connection_status("Connection lost, retrying...")
        self._log(f"[warning] Network issue detected. Retrying in {delay:.1f}s (attempt {attempt_index}/{self.max_retries})")
        end = time.perf_counter() + delay
        while time.perf_counter() < end:
            self._check_cancel()
            time.sleep(0.1)

    def _inspect_remote_resource_with_retry(self, url: str) -> tuple[bool, str, str]:
        last_exc = None
        had_retry = False
        for attempt in range(1, self.max_retries + 1):
            self._check_cancel()
            try:
                result = self._inspect_remote_resource(url)
                if had_retry:
                    self._set_connection_status("Reconnected, resuming download...")
                    self._log("[info] Reconnected, resuming download...")
                else:
                    self._set_connection_status("")
                return result
            except DownloadCancelled:
                raise
            except Exception as e:
                last_exc = e
                if not self._is_transient_network_error(e) or attempt >= self.max_retries:
                    self._set_connection_status("")
                    raise
                had_retry = True
                self._log(f"[warning] Inspect failed for {url}: {e}")
                self._retry_sleep(attempt)
        self._set_connection_status("")
        raise last_exc

    def _download_file_with_retry(self, file_url: str, local_path: Path) -> bool:
        last_exc = None
        had_retry = False
        for attempt in range(1, self.max_retries + 1):
            self._check_cancel()
            try:
                result = self._download_file(file_url, local_path)
                if had_retry:
                    self._set_connection_status("Reconnected, resuming download...")
                    self._log("[info] Reconnected, resuming download...")
                else:
                    self._set_connection_status("")
                return result
            except DownloadCancelled:
                raise
            except Exception as e:
                last_exc = e
                if not self._is_transient_network_error(e) or attempt >= self.max_retries:
                    self._set_connection_status("")
                    self._log(f"[error] Permanent download failure for {file_url}: {e}")
                    self.stats["files_failed"] += 1
                    self._update_global_ui()
                    return False
                had_retry = True
                self._log(f"[warning] Download interrupted for {file_url}: {e}")
                self._retry_sleep(attempt)
        self._set_connection_status("")
        self._log(f"[error] Download failed for {file_url}: {last_exc}")
        self.stats["files_failed"] += 1
        self._update_global_ui()
        return False

    # -----------------------------
    # HTTP helpers
    # -----------------------------
    def _safe_get(self, url: str, stream: bool = False, headers: dict | None = None) -> requests.Response:
        self._check_cancel()

        if not is_same_origin(self.base_url, url):
            raise ValueError(f"Redirection / accès hors domaine interdit: {url}")

        response = self.session.get(
            url,
            stream=stream,
            timeout=self.timeout,
            verify=self.verify_ssl,
            allow_redirects=True,
            headers=headers,
        )

        final_url = response.url
        if not is_same_origin(self.base_url, final_url):
            response.close()
            raise ValueError(f"Redirection finale hors domaine interdite: {final_url}")

        response.raise_for_status()
        return response

    def _safe_head(self, url: str) -> requests.Response | None:
        self._check_cancel()

        if not is_same_origin(self.base_url, url):
            raise ValueError(f"Redirection / accès hors domaine interdit: {url}")

        try:
            response = self.session.head(
                url,
                timeout=self.timeout,
                verify=self.verify_ssl,
                allow_redirects=True,
            )
            final_url = response.url
            if not is_same_origin(self.base_url, final_url):
                response.close()
                raise ValueError(f"Redirection finale hors domaine interdite: {final_url}")
            response.raise_for_status()
            return response
        except Exception:
            return None

    # -----------------------------
    # Listing HTML
    # -----------------------------
    def _parse_directory_listing(self, html: str, current_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[str] = []

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#"):
                continue
            if href.startswith("mailto:") or href.startswith("javascript:"):
                continue
            if href in (".", ".."):
                continue
            if href.startswith("../"):
                continue
            if href.startswith("./../") or href.startswith("./.."):
                continue

            child_url = urljoin(current_url.rstrip("/") + "/", href)
            if not is_same_origin(self.base_url, child_url):
                continue

            child_name = normalize_child_name(href)
            if not child_name:
                continue
            if child_name in (".", ".."):
                continue
            if should_skip_name(child_name):
                continue

            results.append(child_name)

        seen = set()
        deduped = []
        for item in results:
            if item not in seen:
                seen.add(item)
                deduped.append(item)

        return deduped

    def _looks_like_listing(self, content_type: str, text_sample: str) -> bool:
        content_type = (content_type or "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            return False

        soup = BeautifulSoup(text_sample[:500_000], "html.parser")

        links = soup.find_all("a", href=True)
        if not links:
            return False

        title = (soup.title.get_text(" ", strip=True).lower() if soup.title else "")
        h1_tag = soup.find("h1")
        h1 = (h1_tag.get_text(" ", strip=True).lower() if h1_tag else "")

        indicators = [
            "index of",
            "directory listing",
            "listing",
            "contenu de",
            "répertoire",
        ]

        if any(x in title for x in indicators) or any(x in h1 for x in indicators):
            return True

        relative_links = 0
        for a in links[:100]:
            href = a.get("href", "").strip()
            if href and not href.startswith(("http://", "https://", "mailto:", "javascript:", "#")):
                relative_links += 1

        return relative_links >= 2

    # -----------------------------
    # Inspection légère
    # -----------------------------
    def _inspect_remote_resource(self, url: str) -> tuple[bool, str, str]:
        self._check_cancel()

        head_resp = self._safe_head(url)
        if head_resp is not None:
            try:
                final_url = head_resp.url
                content_type = head_resp.headers.get("Content-Type", "")
                if not content_type_is_html_header(content_type):
                    return False, final_url, ""
            finally:
                head_resp.close()

        resp = self._safe_get(url, stream=True)
        try:
            final_url = resp.url
            content_type = resp.headers.get("Content-Type", "")

            if not content_type_is_html_header(content_type):
                return False, final_url, ""

            chunks = []
            total = 0
            max_bytes = 500_000

            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=False):
                self._check_cancel()
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= max_bytes:
                    break

            sample = b"".join(chunks)
            encoding = resp.encoding or "utf-8"
            try:
                text_sample = sample.decode(encoding, errors="replace")
            except Exception:
                text_sample = sample.decode("utf-8", errors="replace")

            is_dir = self._looks_like_listing(content_type, text_sample)
            return is_dir, final_url, text_sample if is_dir else ""

        finally:
            resp.close()

    # -----------------------------
    # Résolution chemin local
    # -----------------------------
    def _resolve_local_file_path(self, target_subfolder: str, remote_url: str) -> Path:
        target_subfolder = sanitize_remote_subpath(target_subfolder)
        local_target = safe_local_path(self.local_dir, target_subfolder)

        if target_subfolder:
            return local_target

        guessed = guess_filename_from_url(remote_url)
        return safe_local_path(self.local_dir, guessed)

    # -----------------------------
    # Téléchargement fichier
    # -----------------------------
    def _download_file(self, file_url: str, local_path: Path) -> bool:
        self._check_cancel()

        if should_skip_name(local_path.name):
            self._log(f"[info] Skipping unwanted file: {file_url}")
            self.stats["files_skipped"] += 1
            self._update_global_ui()
            return False

        self._set_current(f"Downloading: {file_url}")
        self._log(f"Downloading file: {file_url} -> {local_path}")

        relative_for_cache = str(local_path.relative_to(self.local_dir)).replace("\\", "/")
        try:
            already = MetManagement.already_downloaded_compressed_server(
                self.base_url,
                relative_for_cache,
                str(local_path),
            )
        except Exception as e:
            already = False
            self._log(f"[warning] already_downloaded_compressed_server failed: {e}")

        if already:
            self.stats["files_skipped"] += 1
            self._log(f"Skipped already downloaded: {local_path}")
            self._update_global_ui()
            return False

        local_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = local_path.with_suffix(local_path.suffix + ".part")

        accept_ranges = False
        head_response = self._safe_head(file_url)
        if head_response is not None:
            try:
                accept_ranges = "bytes" in head_response.headers.get("Accept-Ranges", "").lower()
            finally:
                head_response.close()

        resume_from = 0
        if tmp_path.exists():
            try:
                resume_from = tmp_path.stat().st_size
            except Exception:
                resume_from = 0

        headers = {"Accept-Encoding": "identity"}
        mode = "wb"

        if accept_ranges and resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
            mode = "ab"
            self._log(f"Resuming download from byte {resume_from}")
        elif resume_from > 0:
            self._log("[info] Server does not support byte ranges, restarting download from zero.")
            try:
                tmp_path.unlink()
            except Exception:
                pass
            resume_from = 0

        response = None
        try:
            response = self._safe_get(file_url, stream=True, headers=headers)

            if resume_from > 0 and "Range" in headers and response.status_code == 200:
                self._log("[warning] Server ignored Range request, restarting from zero.")
                response.close()
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
                resume_from = 0
                headers = {"Accept-Encoding": "identity"}
                mode = "wb"
                response = self._safe_get(file_url, stream=True, headers=headers)

            total_size = 0
            try:
                if response.status_code == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        total_size = int(content_range.rsplit("/", 1)[1])
                else:
                    content_length = response.headers.get("Content-Length")
                    if content_length:
                        total_size = resume_from + int(content_length) if mode == "ab" else int(content_length)
            except Exception:
                total_size = 0

            if self.signals is not None:
                try:
                    if total_size > 0:
                        self.signals.file_progress.emit(int((resume_from / total_size) * 100))
                    else:
                        self.signals.file_progress.emit(0)
                    self.signals.speed.emit("Speed: 0 B/s | ETA: ?")
                except Exception:
                    pass

            written_total = resume_from
            t0 = time.perf_counter()
            last_speed_t = t0
            last_speed_written = written_total

            with open(tmp_path, mode) as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    self._check_cancel()
                    if not chunk:
                        continue

                    f.write(chunk)
                    chunk_len = len(chunk)
                    written_total += chunk_len
                    self.stats["bytes_done"] += chunk_len

                    now = time.perf_counter()
                    dt = max(1e-9, now - last_speed_t)
                    speed_bps = (written_total - last_speed_written) / dt

                    if dt >= 0.25:
                        last_speed_t = now
                        last_speed_written = written_total

                    avg_dt = max(1e-9, now - t0)
                    avg_speed_bps = max(speed_bps, written_total / avg_dt)

                    self._update_file_ui(written_total, total_size, avg_speed_bps)
                    self._update_global_ui()

            final_size = 0
            try:
                final_size = tmp_path.stat().st_size
            except Exception:
                final_size = 0

            if total_size > 0 and final_size != total_size:
                raise DownloadIntegrityError(
                    f"Downloaded size mismatch for {file_url}: expected {total_size}, got {final_size}"
                )

            os.replace(tmp_path, local_path)

            if self.signals is not None:
                try:
                    self.signals.file_progress.emit(100)
                    if total_size > 0:
                        self.signals.speed.emit(
                            f"Speed: 0 B/s | {format_bytes(total_size)} / {format_bytes(total_size)} | ETA: 0s"
                        )
                    else:
                        self.signals.speed.emit(
                            f"Speed: 0 B/s | {format_bytes(final_size)} transferred | ETA: 0s"
                        )
                except Exception:
                    pass

            self.stats["files_done"] += 1
            self._log(f"Downloaded: {local_path}")
            self._update_global_ui()
            return True

        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    # -----------------------------
    # Walk récursif
    # -----------------------------
    def _walk(self, target_subfolder: str):
        self._check_cancel()

        target_subfolder = sanitize_remote_subpath(target_subfolder)
        full_url = build_full_url(self.base_url, target_subfolder)

        if full_url in self.visited:
            self._log(f"Already visited, skip: {full_url}")
            return
        self.visited.add(full_url)

        if target_subfolder and should_skip_name(posixpath.basename(target_subfolder)):
            self._log(f"[info] Skipping unwanted entry: {full_url}")
            return

        self._set_current(f"Inspecting: {full_url}")

        try:
            is_dir, final_url, html_text = self._inspect_remote_resource_with_retry(full_url)

        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            self._log(f"[error] HTTP error on {full_url}: {e}")

            if status in (403, 404, 410):
                self._log(f"[info] Skipping unavailable resource: {full_url}")
                return

            self.stats["files_total_estimated"] += 1
            self._update_global_ui()
            final_local = self._resolve_local_file_path(target_subfolder, full_url)
            self._download_file_with_retry(full_url, final_local)
            return

        except DownloadCancelled:
            raise

        except Exception as e:
            self._log(f"[error] Failed to inspect {full_url}: {e}")
            self.stats["files_total_estimated"] += 1
            self._update_global_ui()
            final_local = self._resolve_local_file_path(target_subfolder, full_url)
            self._download_file_with_retry(full_url, final_local)
            return

        if is_dir:
            self.stats["dirs_seen"] += 1
            self._update_global_ui()
            children = self._parse_directory_listing(html_text, final_url)

            if not children:
                self._log(f"[info] No usable children found in listing: {final_url}")
                return

            self._log(f"Directory detected: {final_url} ({len(children)} item(s))")

            for child_name in children:
                self._check_cancel()

                if target_subfolder:
                    child_subfolder = f"{target_subfolder.rstrip('/')}/{child_name}"
                else:
                    child_subfolder = child_name

                child_subfolder = sanitize_remote_subpath(child_subfolder)

                try:
                    self._walk(child_subfolder)
                except DownloadCancelled:
                    raise
                except Exception as e:
                    child_url = build_full_url(self.base_url, child_subfolder)
                    self._log(f"[error] Failed for {child_url}: {e}")

            return

        self.stats["files_total_estimated"] += 1
        self._update_global_ui()

        final_local = self._resolve_local_file_path(target_subfolder, final_url)
        self._download_file_with_retry(final_url, final_local)

    # -----------------------------
    # API publique
    # -----------------------------
    def download(self, target_subfolder: str = ""):
        self.local_dir.mkdir(parents=True, exist_ok=True)

        parsed = urlparse(self.base_url)
        if parsed.scheme not in ("http", "https"):
            self._log("[error] base_url doit être en http ou https")
            return
        if not parsed.netloc:
            self._log("[error] base_url invalide")
            return

        self._log(f"Start synchronization from: {self.base_url}")
        self._log(f"Local destination: {self.local_dir}")
        self._set_connection_status("")

        try:
            self._walk(target_subfolder)
            self._set_connection_status("")
            self._log("Synchronization finished.")
        except DownloadCancelled:
            self._set_connection_status("")
            self._log("Synchronization cancelled.")
        except Exception as e:
            self._set_connection_status("")
            self._log(f"[error] Synchronization failed but process continues: {e}")


# ============================================================
# Fonction de compatibilité
# ============================================================

def download_from_folder_server(
    base_url: str,
    local_dir: str = ".",
    target_subfolder: str = "",
    visited: set | None = None,
    parent=None,
) -> None:
    dialog = PrettyDownloadDialog(parent=parent) if (QDialog is not object and QThread is not None) else None
    signals = DownloadSignals() if Signal is not None else None

    if dialog is not None and signals is not None:
        signals.log.connect(dialog.append_log)
        signals.current.connect(dialog.set_current)
        signals.global_text.connect(dialog.set_global_text)
        signals.connection.connect(dialog.set_connection_text)
        signals.speed.connect(dialog.set_speed_text)
        signals.file_progress.connect(dialog.set_file_progress)
        signals.global_progress.connect(dialog.set_global_progress)

    downloader = FolderServerDownloader(
        base_url=base_url,
        local_dir=local_dir,
        dialog=dialog,      # uniquement pour cancel_requested
        signals=signals,    # toutes les updates UI
        timeout=(10, 120),
        chunk_size=1024 * 512,
        verify_ssl=True,
        max_redirects=8,
    )

    if visited:
        downloader.visited.update(visited)

    if dialog is None:
        downloader.download(target_subfolder=target_subfolder)
        return

    thread = DownloadThread(downloader, target_subfolder)

    dialog.show()
    dialog.pump()

    thread.start()

    while thread.isRunning():
        QApplication.processEvents()
        time.sleep(0.01)
        if dialog.cancel_requested:
            thread.msleep(20)

    thread.wait()

    if thread.exc is not None:
        if isinstance(thread.exc, DownloadCancelled):
            if dialog.isVisible() and dialog.ui_alive:
                dialog.append_log("Synchronization cancelled.")
                dialog.pump()
            return
        if dialog and dialog.ui_alive:
            dialog.append_log(f"[error] Background error: {thread.exc}")
            dialog.pump()
        else:
            print(f"[error] Background error: {thread.exc}")
        return

    if dialog.isVisible() and dialog.ui_alive:
        dialog.set_connection_text("")
        dialog.set_file_progress(100)
        dialog.set_current("Finished.")
        dialog.set_speed_text("Speed: 0 B/s | ETA: 0s")
        dialog.pump()
        dialog.close()



if __name__ == "__main__":
    # create the json needed to http / zipped stored
    in_repo_file="C:/modele_NLP/IFIA_models/repository.aait"
    create_index_file(in_repo_file)

