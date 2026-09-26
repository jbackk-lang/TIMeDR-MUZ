@echo off
REM TIMeDR-MUZ etap 0 - tylko odczyt.
REM Uzycie: przeciagnij plik wyciagu (CSV albo MT940) na run.bat albo: run.bat wyciag.csv
setlocal
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py

if "%~1"=="" (
  echo Nie podano pliku wyciagu.
  echo Przeciagnij plik CSV albo MT940 na run.bat albo uruchom: run.bat sciezka\do\wyciagu.csv
  goto koniec
)
if not exist "%~1" (
  echo Nie ma pliku: %~1
  goto koniec
)
if not exist "mapowanie.json" (
  echo Brak pliku mapowanie.json w folderze %CD%
  echo Skopiuj mapowanie_przyklad.json jako mapowanie.json i wpisz nazwy kolumn z naglowka wyciagu swojego banku.
  goto koniec
)

%PY% -m muz run --in "%~1" --mapping mapowanie.json --out wyniki
if errorlevel 1 (
  echo.
  echo Przebieg zakonczyl sie bledem - komunikat jest powyzej.
) else (
  echo.
  echo Gotowe. Raport: %CD%\wyniki\raport_etap0.md
)

:koniec
echo.
pause
