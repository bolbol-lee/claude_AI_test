@echo off
chcp 65001 > nul
title 칩이 - 삼성전자 DS 반도체 챗봇
cd /d "%~dp0"
python app.py
pause
