@echo off
REM TIMeDR-MUZ etap 0 - tylko odczyt.
REM Dwuklik: okno programu. Przeciagniecie pliku wyciagu na run.bat: przebieg w konsoli.
setlocal
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py

if "%~1"=="" (
  echo Uruchamiam okno TIMeDR-MUZ, to moze potrwac kilka sekund...
  %PY% -m muz.gui
  if errorlevel 1 (
    echo.
    echo Okno programu nie uruchomilo sie - komunikat jest powyzej.
    pause
  )
  goto :eof
)

if not exist "mapowanie.json" (
  echo Brak pliku mapowanie.json. Uruchom run.bat dwuklikiem, wybierz wyciag i kolumny w oknie.
  pause
  goto :eof
)
%PY% -m muz run --in "%~1" --mapping mapowanie.json --out wyniki
echo.
if errorlevel 1 (echo Przebieg zakonczyl sie bledem - komunikat jest powyzej.) else (echo Gotowe. Raport: %CD%\wyniki\raport_etap0.md)
pause
