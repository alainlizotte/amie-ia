@echo off
rem Arrete le serveur Ami(e) IA (conteneur detached). Les donnees
rem (sessions, photos, comptes) sont conservees.

cd /d "%~dp0.."
docker compose down
echo.
echo Serveur arrete.
timeout /t 3 >nul
