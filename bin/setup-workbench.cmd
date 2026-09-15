@echo off
rem One-click workbench setup for colleagues: pip deps + npm deps + doctor.
rem Safe to re-run. See bin/setup-workbench.py for details.
py -3.11 "%~dp0setup-workbench.py" %*
