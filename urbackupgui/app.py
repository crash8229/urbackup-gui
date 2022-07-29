import json
import subprocess
import sys
import typing
from datetime import datetime
from string import Template
from pathlib import Path

from qtpy.QtCore import Qt, Slot, Signal, QTimer, QEvent
from qtpy.QtGui import QIcon
from qtpy.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QSystemTrayIcon,
    QMenu,
    QAction,
)

# Globals ##############################################################################################################
RESOURCE_PATH = Path(__file__).resolve().parent

# Helper Classes #######################################################################################################


# I just want a scrollable list widget with no highlighting on items
# It is just to display a list of string
class ListWidget(QListWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(
            f"background-color: {parent.palette().window().color().name()}; border: none;"
        )

    def mousePressEvent(self, event: QEvent) -> None:
        pass

    def mouseMoveEvent(self, e: QEvent) -> None:
        pass


class StatusInfo(QWidget):
    statuses = {
        "FULL": "Full file backup running.",
        "INCR": "Incremental file backup running.",
        "IDLE": "Idle.",
    }
    status_format = Template("$status $progress")
    eta_format = Template("ETA: $time")
    last_backup_format = Template("Last backup on $date")
    connect_to_local_format = Template("${status}onnected to local UrBackup server.")
    last_seen_format = Template("Local server last seen $minutes minutes ago.")

    def __init__(self, parent) -> None:
        super().__init__(parent)
        layout = QVBoxLayout()
        self.setLayout(layout)
        layout.setSpacing(10)

        # Current status
        self.status_text = QLabel(
            self.status_format.substitute(status=self.statuses["IDLE"], progress=""),
            self,
        )
        layout.addWidget(self.status_text, alignment=Qt.AlignLeft)

        self.eta_text = QLabel("", self)
        layout.addWidget(self.eta_text, alignment=Qt.AlignLeft)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(separator)

        # Server and backup information
        self.last_backup = QLabel("", self)
        layout.addWidget(self.last_backup, alignment=Qt.AlignLeft)

        servers_widget = QWidget(self)
        servers_widget.setMaximumHeight(50)
        servers_layout = QHBoxLayout()
        servers_layout.setContentsMargins(0, 0, 0, 0)
        servers_widget.setLayout(servers_layout)
        servers_label = QLabel("Servers:", self)
        servers_layout.addWidget(servers_label, alignment=Qt.AlignTop)
        self.servers = ListWidget(self)
        servers_layout.addWidget(self.servers)
        layout.addWidget(servers_widget, alignment=Qt.AlignLeft)

        layout.addSpacing(10)

        connect_widget = QWidget(self)
        connect_layout = QHBoxLayout(connect_widget)
        connect_layout.setContentsMargins(0, 0, 0, 0)
        connect_layout.addWidget(
            QLabel("Connection status:", connect_widget), alignment=Qt.AlignTop
        )
        self.connect_status = QLabel(
            f'{self.connect_to_local_format.substitute(status="Not c")}',
            connect_widget,
        )
        self.connect_status.setFixedHeight(35)
        self.connect_status.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        connect_widget.layout().addWidget(self.connect_status)
        layout.addWidget(connect_widget, alignment=Qt.AlignLeft)

    @Slot(dict)
    def update_status(self, status: typing.Optional[dict]) -> None:
        if status is None:
            self.status_text.setText("Could not get status!")
            self.eta_text.setText("")
            self.progress_bar.setValue(0)
            self.last_backup.setText("")
            self.servers.clear()
            self.connect_status.setText("Unknown")
            return

        # Current status
        curr_status = "IDLE"
        progress = ""
        percent = 0
        eta = None
        if len(status["running_processes"]) > 0:
            curr_status = status["running_processes"][0]["action"]
            eta = status["running_processes"][0]["eta_ms"]
            percent = status["running_processes"][0]["percent_done"]

            if percent == -1:
                progress = "Indexing."
                percent = 0
            else:
                progress = f"{percent}% done."
        self.status_text.setText(
            self.status_format.substitute(
                status=self.statuses[curr_status], progress=progress
            )
        )
        if eta is not None and eta != -1:
            eta = f"{eta // 3600000} hours {eta // 60000} minutes"
            self.eta_text.setText(self.eta_format.substitute(time=eta))
        else:
            self.eta_text.setText("")
        self.progress_bar.setValue(percent)

        # Server and backup information
        last_backup = None
        if "last_backup_time" in status:
            last_backup = datetime.fromtimestamp(status["last_backup_time"]).strftime(
                "%m/%d/%Y %I:%M:%S %p"
            )
        if last_backup is not None:
            self.last_backup.setText(
                self.last_backup_format.substitute(date=last_backup)
            )
        self.servers.clear()
        for server in status["servers"]:
            self.servers.addItem(
                f"{server['name']} (Internet: {'Yes' if server['internet_connection'] else 'No'})"
            )
        internet_status = status["internet_status"]
        last_seen = status["time_since_last_lan_connection"] // 60000
        if internet_status == "wait_local":
            connect_status = "Waiting for local UrBackup server."
        elif internet_status == "no_server":
            connect_status = "No servers"
        else:
            connect_status = f'{self.connect_to_local_format.substitute(status="C" if internet_status == "connected_local" else "Not c")}\n{self.last_seen_format.substitute(minutes=last_seen)}'
        self.connect_status.setText(connect_status)


# App ##################################################################################################################
class App(QMainWindow):
    status: Signal = Signal(dict)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowTitle("UrBackup Control Panel")
        self.setFixedSize(500, 250)

        # Load icons
        icon_dir = RESOURCE_PATH.joinpath("icons")
        self.icons = {
            "not_connected": QIcon(str(icon_dir.joinpath("database_red.png"))),
            "connected": QIcon(str(icon_dir.joinpath("database_white.png"))),
            "busy": QIcon(str(icon_dir.joinpath("database_yellow.png"))),
        }
        self.setWindowIcon(self.icons["not_connected"])

        if sys.platform == "win32":
            QMessageBox.critical(
                self,
                "Not supported",
                "Windows is currently not supported",
                QMessageBox.Ok,
                QMessageBox.NoButton,
            )
            sys.exit(1)
        try:
            self.get_status()
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "UrBackup Error",
                "Could not find the UrBackup control executable!",
                QMessageBox.Ok,
                QMessageBox.NoButton,
            )
            sys.exit(1)

        main_widget = QWidget(self)
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(5, 0, 5, 0)

        self.__closing: bool = False

        # System Tray Icon
        self.tray_icon = QSystemTrayIcon(self.icons["not_connected"], self)
        self.tray_icon.setVisible(True)
        self.tray_icon.activated.connect(self.tray_activated)  # type: ignore
        tray_menu = QMenu(self)
        action = QAction("Open", tray_menu)
        action.triggered.connect(self.open_and_show)
        tray_menu.addAction(action)
        action = QAction("Exit", tray_menu)
        action.triggered.connect(self.close_app)
        tray_menu.addAction(action)
        self.tray_icon.setContextMenu(tray_menu)
        self.status.connect(self.update_tray)

        # Status information
        self.status_info = StatusInfo(self)
        main_layout.addWidget(self.status_info)
        self.status.connect(self.status_info.update_status)

        # separator = QFrame(self)
        # separator.setFrameShape(QFrame.HLine)
        # separator.setFrameShadow(QFrame.Sunken)
        # separator.setContentsMargins(0, 0, 0, 0)
        # layout.addWidget(separator)

        # Perform initial update
        self.update_status()

        # Start update timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_status)  # type: ignore
        self.update_timer.start(5000)

    def close_app(self) -> None:
        self.__closing = True
        self.show()
        self.close()

    def open_and_show(self) -> None:
        self.show()
        if self.isMinimized():
            self.showNormal()

    def closeEvent(self, event: QEvent) -> None:
        if self.__closing or not self.tray_icon.isSystemTrayAvailable():
            # Closing steps
            self.update_timer.stop()

            event.accept()
        else:
            self.hide()
            event.ignore()

    def changeEvent(self, event: QEvent) -> None:
        if (
                event.type() == QEvent.WindowStateChange
                and self.tray_icon.isSystemTrayAvailable()
                and self.isMinimized()
        ):
            self.hide()
            event.ignore()
        else:
            event.accept()

    @Slot(QSystemTrayIcon.ActivationReason)
    def tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.open_and_show()

    @Slot(dict)
    def update_tray(self, status: typing.Optional[dict]) -> None:
        if status is None:
            self.tray_icon.setIcon(self.icons["not_connected"])
            self.setWindowIcon(self.icons["not_connected"])
            return

        internet_status = status["internet_status"]
        if len(status["running_processes"]) > 0:
            self.tray_icon.setIcon(self.icons["busy"])
            self.setWindowIcon(self.icons["busy"])
        elif internet_status == "connected_local":
            self.tray_icon.setIcon(self.icons["connected"])
            self.setWindowIcon(self.icons["connected"])
        else:
            self.tray_icon.setIcon(self.icons["not_connected"])
            self.setWindowIcon(self.icons["not_connected"])

    @staticmethod
    def get_status() -> typing.Optional[dict]:
        result = subprocess.run(["urbackupclientctl", "status"], capture_output=True)
        if result.returncode != 0:
            return None
        else:
            return json.loads(result.stdout)

    def update_status(self) -> None:
        status = self.get_status()
        # if status is not None:
        self.status.emit(status)


if __name__ == "__main__":
    app = QApplication()
    window = App()
    window.show()
    app.exec_()
