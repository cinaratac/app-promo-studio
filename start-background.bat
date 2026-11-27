@echo off
rem Starts the panel + automatic production minimized in the background.
rem To start it when you log in, put a SHORTCUT to this file into: Win+R -> shell:startup
cd /d "%~dp0"
start "Promo Studio" /min python -m studio.panel --no-browser
