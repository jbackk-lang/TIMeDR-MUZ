@echo off
REM TIMeDR-MUZ etap 0 - tylko odczyt. Uzycie: run.bat wyciag.csv
cd /d "%~dp0"
python -m muz run --in %1 --mapping mapowanie.json --out wyniki
