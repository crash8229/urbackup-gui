#!/bin/bash

poetry run pyinstaller --clean --onefile --name urbackup_status --add-data="urbackupgui/icons:icons"  urbackupgui/app.py
