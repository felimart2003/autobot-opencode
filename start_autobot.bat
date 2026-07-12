@echo off
rem Start autobot in watch mode: run queued Notion projects back-to-back,
rem sleep through usage-limit windows, poll for new projects.
cd /d "%~dp0"
python -m autobot --watch
pause
