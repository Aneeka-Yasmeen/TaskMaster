@echo off
rem TaskMaster desktop companion for Windows (needs Windows Python; stdlib only).
rem Set TASKMASTER_DB to your workspace database, or edit the default below.
cd /d "%~dp0.."
if "%TASKMASTER_DB%"=="" set TASKMASTER_DB=demo.db
title TaskMaster companion (close this window or press Ctrl+C to quit)
python -m statetrace --db "%TASKMASTER_DB%" companion %*
