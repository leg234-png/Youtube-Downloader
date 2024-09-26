import requests
from packaging import version
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
import logging

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

    # ... Le reste de la classe YouTubeDownloader reste inchangé ...