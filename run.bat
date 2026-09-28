@echo off
REM MUZ - zarzadca budzetu. Dwuklik: okno. Przeciagniecie plikow wyciagow na ten plik: okno z tymi plikami.
setlocal
cd /d "%~dp0"

set PY=python
where python >nul 2>nul || set PY=py

%PY% -c "import numpy, reportlab, pdfplumber" >nul 2>nul
if errorlevel 1 (
  echo Pierwsze uruchomienie: instaluje potrzebne biblioteki - chwila...
  %PY% -m pip install --user --quiet numpy reportlab pdfplumber
)

echo Uruchamiam okno MUZ...
%PY% -m muz.gui %*
if errorlevel 1 (
  echo.
  echo Okno programu nie uruchomilo sie - komunikat jest powyzej.
  pause
)
