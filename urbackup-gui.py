import sys
from qtpy.QtWidgets import QApplication, QMainWindow


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UrBackup Control Panel")
        if sys.platform.startswith("win32"):
            self.__cmd = "UrBackupClient_cmd"
        else:
            self.__cmd = "urbackupclientctl"
        print(self.__cmd)


if __name__ == "__main__":
    app = QApplication([])
    window = App()
    window.show()
    app.exec_()
