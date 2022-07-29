#!/bin/bash

poetry run pyinstaller --clean --onefile --name urbackup_status --icon "urbackupgui/icons/database_white.ico" --add-data "urbackupgui/icons:icons"  urbackupgui/app.py
