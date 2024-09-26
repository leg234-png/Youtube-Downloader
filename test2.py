import os
import sys
import re
import requests
import json
import logging
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, 
                             QPushButton, QProgressBar, QFileDialog, QLabel, QMessageBox, 
                             QComboBox, QTabWidget, QTextEdit, QSpinBox, QCheckBox, QListWidget)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QSize, QSettings
from PyQt5.QtGui import QIcon, QPixmap, QMovie
import yt_dlp
from moviepy.editor import VideoFileClip
from packaging import version
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
import logging

# Configuration du logging
logging.basicConfig(filename='youtube_downloader.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

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
            logging.error(f"Error in ThumbnailThread: {str(e)}")
            self.error.emit(str(e))

class DownloadThread(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, url, save_path, quality, is_playlist, extract_audio=False):
        super().__init__()
        self.url = url
        self.save_path = save_path
        self.quality = quality
        self.is_playlist = is_playlist
        self.extract_audio = extract_audio
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
            
            if self.extract_audio:
                video_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
                video_opts['format'] = 'bestaudio/best'
            
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
            logging.error(f"Error in DownloadThread: {str(e)}")
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

class ConversionThread(QThread):
    progress = pyqtSignal(float)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, input_file, output_file, target_format):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.target_format = target_format

    def run(self):
        try:
            clip = VideoFileClip(self.input_file)
            total_duration = clip.duration
            
            def progress_callback(t):
                progress = (t / total_duration) * 100
                self.progress.emit(progress)

            if self.target_format == 'mp3':
                clip.audio.write_audiofile(self.output_file, progress_callback=progress_callback)
            else:
                clip.write_videofile(self.output_file, codec='libx264', audio_codec='aac', progress_callback=progress_callback)
            
            clip.close()
            self.finished.emit()
        except Exception as e:
            logging.error(f"Error in ConversionThread: {str(e)}")
            self.error.emit(str(e))

class UpdateChecker(QThread):
    update_available = pyqtSignal(str, str)
    error = pyqtSignal(str)

    def __init__(self, current_version, check_interval=3600):
        super().__init__()
        self.current_version = current_version
        self.check_interval = check_interval  # Intervalle de vérification en secondes
        self.github_api_url = "https://api.github.com/repos/votrecompte/youtube-downloader/releases/latest"
        self.download_url = "https://github.com/votrecompte/youtube-downloader/releases/latest/download/YouTubeDownloader.exe"

    def run(self):
        while True:
            try:
                response = requests.get(self.github_api_url)
                response.raise_for_status()
                latest_release = response.json()
                latest_version = latest_release['tag_name'].lstrip('v')

                if version.parse(latest_version) > version.parse(self.current_version):
                    self.update_available.emit(latest_version, self.download_url)
                
                self.sleep(self.check_interval)
            except Exception as e:
                logging.error(f"Error in UpdateChecker: {str(e)}")
                self.error.emit(str(e))
                self.sleep(self.check_interval)  # Attendre avant de réessayer même en cas d'erreur

class YouTubeDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.is_playlist = False
        self.thumbnail_thread = None
        self.download_thread = None
        self.conversion_thread = None
        self.settings = QSettings("YourCompany", "YouTubeDownloader")
        self.load_settings()
        self.current_version = "1.0.0"
        self.start_update_checker()

    def start_update_checker(self):
        self.update_checker = UpdateChecker(self.current_version)
        self.update_checker.update_available.connect(self.show_update_dialog)
        self.update_checker.error.connect(self.log_update_error)
        self.update_checker.start()
    
    def show_update_dialog(self, new_version, download_url):
        reply = QMessageBox.question(self, 'Mise à jour disponible',
                                     f"Une nouvelle version ({new_version}) est disponible. Voulez-vous la télécharger?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            self.start_update_download(download_url)
    def start_update_download(self, download_url):
        try:
            response = requests.get(download_url, stream=True)
            response.raise_for_status()
            
            save_path = QFileDialog.getSaveFileName(self, "Sauvegarder la nouvelle version", "YouTubeDownloader_new.exe", "Executable (*.exe)")[0]
            
            if save_path:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                QMessageBox.information(self, "Mise à jour téléchargée", f"La nouvelle version a été téléchargée vers {save_path}. Veuillez fermer l'application actuelle et lancer la nouvelle version.")
            else:
                QMessageBox.information(self, "Téléchargement annulé", "Le téléchargement de la mise à jour a été annulé.")
        except Exception as e:
            QMessageBox.critical(self, "Erreur de téléchargement", f"Une erreur est survenue lors du téléchargement de la mise à jour : {str(e)}")

    def log_update_error(self, error_msg):
        logging.error(f"Erreur lors de la vérification des mises à jour : {error_msg}")
        self.log_message(f"Erreur lors de la vérification des mises à jour : {error_msg}")


    def initUI(self):
        layout = QVBoxLayout()

        # Créer un QTabWidget pour organiser les différentes fonctionnalités
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Onglet de téléchargement
        download_tab = QWidget()
        download_layout = QVBoxLayout(download_tab)
        self.setup_download_ui(download_layout)
        self.tab_widget.addTab(download_tab, "Téléchargement")

        # Onglet de conversion
        conversion_tab = QWidget()
        conversion_layout = QVBoxLayout(conversion_tab)
        self.setup_conversion_ui(conversion_layout)
        self.tab_widget.addTab(conversion_tab, "Conversion")

        # Onglet de configuration
        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        self.setup_config_ui(config_layout)
        self.tab_widget.addTab(config_tab, "Configuration")

        # Onglet de journalisation
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        self.setup_log_ui(log_layout)
        self.tab_widget.addTab(log_tab, "Journal")

        self.setLayout(layout)
        self.setWindowTitle('YouTube Downloader')
        self.setGeometry(300, 300, 500, 600)

        icon_path = resource_path("youtube_downloader.ico")
        self.setWindowIcon(QIcon(icon_path))

    def setup_download_ui(self, layout):
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.textChanged.connect(self.start_validate_url)
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

        self.extract_audio_checkbox = QCheckBox("Extraire l'audio (MP3)")
        layout.addWidget(self.extract_audio_checkbox)

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

    def setup_conversion_ui(self, layout):
        self.input_file_edit = QLineEdit()
        self.input_file_btn = QPushButton("Choisir le fichier d'entrée")
        self.input_file_btn.clicked.connect(self.choose_input_file)
        
        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_file_edit)
        input_layout.addWidget(self.input_file_btn)
        layout.addLayout(input_layout)

        self.output_file_edit = QLineEdit()
        self.output_file_btn = QPushButton("Choisir le fichier de sortie")
        self.output_file_btn.clicked.connect(self.choose_output_file)
        
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_file_edit)
        output_layout.addWidget(self.output_file_btn)
        layout.addLayout(output_layout)

        self.format_combo = QComboBox()
        self.format_combo.addItems(['mp4', 'avi', 'mkv', 'mp3'])
        layout.addWidget(QLabel("Format de sortie:"))
        layout.addWidget(self.format_combo)

        self.convert_btn = QPushButton("Convertir")
        self.convert_btn.clicked.connect(self.start_conversion)
        layout.addWidget(self.convert_btn)

        self.conversion_progress_bar = QProgressBar()
        layout.addWidget(self.conversion_progress_bar)

        self.conversion_label = QLabel()
        layout.addWidget(self.conversion_label)

    def setup_config_ui(self, layout):
        self.default_save_path_edit = QLineEdit()
        self.default_save_path_btn = QPushButton("Choisir le dossier de sauvegarde par défaut")
        self.default_save_path_btn.clicked.connect(self.choose_default_save_path)
        
        save_path_layout = QHBoxLayout()
        save_path_layout.addWidget(self.default_save_path_edit)
        save_path_layout.addWidget(self.default_save_path_btn)
        layout.addLayout(save_path_layout)

        self.default_quality_combo = QComboBox()
        self.default_quality_combo.addItems(['best', '1080p', '720p', '480p', '360p', '240p'])
        layout.addWidget(QLabel("Qualité par défaut:"))
        layout.addWidget(self.default_quality_combo)

        self.max_downloads_spin = QSpinBox()
        self.max_downloads_spin.setRange(1, 10)
        layout.addWidget(QLabel("Nombre maximum de téléchargements simultanés:"))
        layout.addWidget(self.max_downloads_spin)

        self.save_config_btn = QPushButton("Sauvegarder la configuration")
        self.save_config_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_config_btn)

    def setup_log_ui(self, layout):
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.clear_log_btn = QPushButton("Effacer le journal")
        self.clear_log_btn.clicked.connect(self.clear_log)
        layout.addWidget(self.clear_log_btn)

    def load_settings(self):
        self.default_save_path_edit.setText(self.settings.value("default_save_path", ""))
        self.default_quality_combo.setCurrentText(self.settings.value("default_quality", "best"))
        self.max_downloads_spin.setValue(int(self.settings.value("max_downloads", 1)))

    def save_settings(self):
        self.settings.setValue("default_save_path", self.default_save_path_edit.text())
        self.settings.setValue("default_quality", self.default_quality_combo.currentText())
        self.settings.setValue("max_downloads", self.max_downloads_spin.value())
        QMessageBox.information(self, "Configuration", "Configuration sauvegardée avec succès!")

    def choose_default_save_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de sauvegarde par défaut")
        if folder:
            self.default_save_path_edit.setText(folder)

    def clear_log(self):
        self.log_text.clear()

    def log_message(self, message):
        self.log_text.append(message)
        logging.info(message)

    def check_for_updates(self):
        self.update_checker = UpdateChecker(self.current_version)
        self.update_checker.update_available.connect(self.show_update_dialog)
        self.update_checker.start()

    def show_update_dialog(self, new_version):
        reply = QMessageBox.question(self, 'Mise à jour disponible',
                                     f"Une nouvelle version ({new_version}) est disponible. Voulez-vous la télécharger?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.Yes:
            # Ici, vous pouvez ajouter le code pour télécharger et installer la mise à jour
            QMessageBox.information(self, "Mise à jour", "La mise à jour va être téléchargée et installée.")

    def choose_input_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Choisir le fichier d'entrée")
        if file:
            self.input_file_edit.setText(file)

    def choose_output_file(self):
        file, _ = QFileDialog.getSaveFileName(self, "Choisir le fichier de sortie")
        if file:
            self.output_file_edit.setText(file)

    def start_conversion(self):
        input_file = self.input_file_edit.text()
        output_file = self.output_file_edit.text()
        target_format = self.format_combo.currentText()

        if not input_file or not output_file:
            QMessageBox.warning(self, "Erreur", "Veuillez sélectionner les fichiers d'entrée et de sortie.")
            return

        self.conversion_thread = ConversionThread(input_file, output_file, target_format)
        self.conversion_thread.progress.connect(self.update_conversion_progress)
        self.conversion_thread.finished.connect(self.conversion_finished)
        self.conversion_thread.error.connect(self.show_conversion_error)
        self.conversion_thread.start()

        self.convert_btn.setEnabled(False)
        self.conversion_label.setText("Conversion en cours...")

    def update_conversion_progress(self, progress):
        self.conversion_progress_bar.setValue(int(progress))

    def conversion_finished(self):
        self.conversion_progress_bar.setValue(100)
        self.convert_btn.setEnabled(True)
        self.conversion_label.setText("Conversion terminée!")
        QMessageBox.information(self, "Succès", "Conversion terminée avec succès!")

    def show_conversion_error(self, error_msg):
        QMessageBox.critical(self, "Erreur", f"Une erreur est survenue lors de la conversion : {error_msg}")
        self.convert_btn.setEnabled(True)
        self.conversion_label.setText("Erreur lors de la conversion")
        self.conversion_progress_bar.setValue(0)

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
        self.log_message(f"Erreur lors de la récupération de la miniature : {error}")

    def set_is_playlist(self, is_playlist):
        self.is_playlist = is_playlist

    def start_download(self):
        url = self.url_input.text()
        if not url:
            QMessageBox.warning(self, "Erreur", "Veuillez entrer une URL valide.")
            return

        save_path = QFileDialog.getExistingDirectory(self, "Sélectionner le dossier de sauvegarde", self.default_save_path_edit.text())
        if not save_path:
            return

        quality = self.quality_combo.currentText()
        extract_audio = self.extract_audio_checkbox.isChecked()

        self.progress_bar.setValue(5)  # Commence à 5% pour indiquer que le téléchargement a débuté
        self.progress_label.setText("Démarrage du téléchargement...")

        self.download_thread = DownloadThread(url, save_path, quality, self.is_playlist, extract_audio)
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
        self.log_message("Téléchargement terminé avec succès")

    def show_error(self, error_msg):
        QMessageBox.critical(self, "Erreur", f"Une erreur est survenue : {error_msg}")
        self.download_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Erreur lors du téléchargement")
        self.progress_bar.setValue(0)
        self.log_message(f"Erreur lors du téléchargement : {error_msg}")

    def toggle_pause_resume(self):
        if self.download_thread.paused:
            self.download_thread.resume()
            self.pause_resume_btn.setText('Pause')
            self.progress_label.setText("Téléchargement repris")
            self.log_message("Téléchargement repris")
        else:
            self.download_thread.pause()
            self.pause_resume_btn.setText('Reprendre')
            self.progress_label.setText("Téléchargement en pause")
            self.log_message("Téléchargement mis en pause")

    def stop_download(self):
        if self.download_thread:
            self.download_thread.stop()
            self.download_thread.wait()
        self.download_btn.setEnabled(True)
        self.pause_resume_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        self.progress_label.setText("Téléchargement arrêté")
        self.progress_bar.setValue(0)
        self.log_message("Téléchargement arrêté par l'utilisateur")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = YouTubeDownloader()
    ex.show()
    sys.exit(app.exec_())