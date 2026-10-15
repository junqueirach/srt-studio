@echo off
:: SRT Studio launcher: runs srt_studio.py from this folder.
cd /d "%~dp0"
start "" pythonw srt_studio.py
