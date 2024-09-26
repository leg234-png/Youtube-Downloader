import os
import sys
import re
import requests
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QPushButton, QProgressBar, QFileDialog, QLabel, QMessageBox, 
                             QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSize, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QMovie
import yt_dlp

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class ThumbnailThread(QThread):
    thumbnail_ready = pyqtSignal(QPixmap, str, list)
    error = pyqtSignal(str)
    is_playlist = pyqtSignal(bool)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=False)
                if 'entries' in info:
                    self.is_playlist.emit(True)
                    video_info = info['entries'][0]
                else:
                    self.is_playlist.emit(False)
                    video_info = info

                thumbnail_url = video_info['thumbnail']
                title = video_info['title']
                
                formats = video_info['formats']
                available_qualities = ['best']
                for format in formats:
                    if 'height' in format and format['height']:
                        quality = f"{format['height']}p"
                        if quality not in available_qualities:
                            available_qualities.append(quality)
                
                available_qualities = sorted(available_qualities, key=lambda x: int(x[:-1]) if x != 'best' else float('inf'), reverse=True)

                response = requests.get(thumbnail_url)
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                self.thumbnail_ready.emit(pixmap, title, available_qualities)
        except Exception as e:
            self.error.emit(str(e))

class DownloadThread(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url, save_path, quality, is_playlist):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.quality = quality
        self.is_playlist = is_playlist
        self.current_video = 0
        self.total_videos = 1
        self.current_progress = 0
        self.paused = False
        self.stopped = False
        self.ydl = None

    def run(self):
        try:
            video_opts = {
                'outtmpl': os.path.join(self.save_path, '%(title)s.%(ext)s'),
                'progress_hooks': [self.progress_hook],
                'format': self.quality,
                'continuedl': True,
            }
            
            if self.is_playlist:
                video_opts['yes_playlist'] = True
            else:
                video_opts['no_playlist'] = True

            self.ydl = yt_dlp.YoutubeDL(video_opts)
            info = self.ydl.extract_info(self.url, download=False)
            if self.is_playlist:
                self.total_videos = len(info['entries'])
            
            while not self.stopped:
                try:
                    self.ydl.download([self.url])
                    break
                except Exception as e:
                    if "HTTP Error 429" in str(e):
                        self.error.emit("Trop de requêtes. Réessai dans 60 secondes...")
                        for i in range(60):
                            if self.stopped:
                                return
                            self.sleep(1)
                    else:
                        raise

            if not self.stopped:
                subtitle_opts = {
                    'skip_download': True,
                    'writesubtitles': True,
                    'subtitleslangs': ['fr'],
                    'subtitlesformat': 'vtt',
                    'outtmpl': os.path.join(self.save_path, '%(title)s.%(ext)s'),
                }
                
                if self.is_playlist:
                    subtitle_opts['yes_playlist'] = True
                else:
                    subtitle_opts['no_playlist'] = True

                with yt_dlp.YoutubeDL(subtitle_opts) as ydl:
                    ydl.download([self.url])

                self.progress.emit(100)
                self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def progress_hook(self, d):
        if d['status'] == 'downloading':
            while self.paused:
                self.sleep(1)
                if self.stopped:
                    return
            
            p = d.get('_percent_str', '0%')
            p = p.replace('%','').strip()
            p = re.sub(r'\x1b\[[0-9;]*m', '', p)
            try:
                video_progress = float(p)
                self.current_progress = (self.current_video * 100 + video_progress) / self.total_videos
                self.progress.emit(self.current_progress)
            except ValueError:
                pass
        elif d['status'] == 'finished':
            self.current_video += 1
            self.current_progress = (self.current_video * 100) / self.total_videos
            self.progress.emit(self.current_progress)

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stopped = True
        if self.ydl:
            self.ydl.params['abort'] = True
        self.terminate()  # Forcer l'arrêt du thread si nécessaire

class YouTubeDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.is_playlist = False
        self.thumbnail_thread = None
        self.download_thread = None
        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self.start_validate_url)
        self.preview_timer.setSingleShot(True)

    def initUI(self):
        layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.textChanged.connect(self.on_url_changed)
        url_layout.addWidget(QLabel("URL:"))
        url_layout.addWidget(self.url_input)
        layout.addLayout(url_layout)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(320, 180)
        self.preview_label.setStyleSheet("QLabel { background-color: #f0f0f0; }")
        layout.addWidget(self.preview_label)

        self.spinner = QMovie(resource_path("spinner.gif"))
        self.spinner.setScaledSize(QSize(320, 180))
        self.preview_label.setMovie(self.spinner)

        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        quality_layout = QHBoxLayout()
        self.quality_combo = QComboBox()
        quality_layout.addWidget(QLabel("Qualité:"))
        quality_layout.addWidget(self.quality_combo)
        layout.addLayout(quality_layout)

        button_layout = QHBoxLayout()
        self.download_btn = QPushButton('Télécharger')
        self.download_btn.clicked.connect(self.start_download)
        self.pause_resume_btn = QPushButton('Pause')
        self.pause_resume_btn.clicked.connect(self.toggle_pause_resume)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn = QPushButton('Arrêter')
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        button_layout.addWidget(self.download_btn)
        button_layout.addWidget(self.pause_resume_btn)
        button_layout.addWidget(self.stop_btn)
        layout.addLayout(button_layout)

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.progress_label = QLabel()
        layout.addWidget(self.progress_label)

        icon_path = resource_path("youtube_downloader.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.setLayout(layout)
        self.setWindowTitle('YouTube Downloader')
        self.setGeometry(300, 300, 400, 450)

    def on_url_changed(self):
        self.preview_timer.start(500)  # Démarrer le timer pour 500ms

    def start_validate_url(self):
        if self.thumbnail_thread and self.thumbnail_thread.isRunning():
            self.thumbnail_thread.terminate()
            self.thumbnail_thread.wait()

        url = self.url_input.text()
        if not url:
            self.preview_label.clear()
            self.title_label.clear()
            self.quality_combo.clear()
            return

        self.spinner.start()
        self.preview_label.setMovie(self.spinner)
        self.title_label.setText("Chargement...")
        self.quality_combo.clear()

        self.thumbnail_thread = ThumbnailThread(url)
        self.thumbnail_thread.thumbnail_ready.connect(self.update_thumbnail)
        self.thumbnail_thread.error.connect(self.show_thumbnail_error)
        self.thumbnail_thread.is_playlist.connect(self.set_is_playlist)
        self.thumbnail_thread.start()

    def update_thumbnail(self, pixmap, title, qualities):
        self.spinner.stop()
        scaled_pixmap = pixmap.scaled(320, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview_label.setPixmap(scaled_pixmap)
        self.title_label.setText(title)
        self.quality_combo.clear()
        self.quality_combo.addItems(qualities)

    def show_thumbnail_error(self, error):
        self.spinner.stop()
        self.preview_label.setText("URL non valide ou erreur lors de la récupération des informations")
        self.title_label.clear()
        self.quality_combo.clear()
        print(f"Erreur : {error}")

    def set_is_playlist(self, is_playlist):
        self.is_playlist = is_playlist

    def start_download(self):
        url = self.url_input.text()
        if not url:
            QMessageBox.warning(self, "Erreur", "Veuillez entrer une URL valide.")
            return

        save_path = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de sauvegarde")
        if not save_path:
            return

        quality = self.quality_combo.currentText()

        self.progress_bar.setValue(5)  # Commence à 5% pour indiquer que le téléchargement a débuté
        self.progress_label.setText("Démarrage du téléchargement...")

        self.download_thread = DownloadThread(url, save_path, quality, self.is_playlist)
        self.download_thread.progress.connect(self.update_progress)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.error.connect(self.show_error)
        self.download_thread.start()

        self.download_btn.setEnabled(False)
        self.pause_resume_btn.setEnabled(True)
        self.stop_btn.setEnabled(True)

    def update_progress(self, progress):
        self.progress_bar.setValue(int(progress))
        if self.is_playlist:
            self.progress_label.setText(f"Progression totale: {progress:.1f}%")
        else:
            self.progress_label.setText(f"Progression: {progress:.1f}%")

    def download_finished(self):
        self.progress_bar.setValue(100)
        self.download_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Téléchargement terminé!")
        QMessageBox.information(self, "Succès", "Téléchargement terminé!")

    def show_error(self, error_msg):
        QMessageBox.critical(self, "Erreur", f"Une erreur est survenue : {error_msg}")
        self.download_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Erreur lors du téléchargement")
        self.progress_bar.setValue(0)

    def toggle_pause_resume(self):
        if self.download_thread.paused:
            self.download_thread.resume()
            self.pause_resume_btn.setText('Pause')
            self.progress_label.setText("Téléchargement repris")
        else:
            self.download_thread.pause()
            self.pause_resume_btn.setText('Reprendre')
            self.progress_label.setText("Téléchargement en pause")

    def stop_download(self):
        if self.download_thread:
            self.download_thread.stop()
            self.download_thread.wait(5000)  # Attendre 5 secondes max
            if self.download_thread.isRunning():
                self.download_thread.terminate()
                self.download_thread.wait()
        self.download_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Téléchargement arrêté")
        self.progress_bar.setValue(0)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = YouTubeDownloader()
    ex.show()
    sys.exit(app.exec_())