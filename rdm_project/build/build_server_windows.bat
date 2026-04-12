@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

pyinstaller rdm_server_app.py ^
  --name "RDM_Server" ^
  --onefile ^
  --windowed ^
  --icon "rdm_project\assets\icon.ico" ^
  --noconfirm ^
  --clean ^
  --optimize 2 ^
  --add-data "rdm_project;rdm_project" ^
  --hidden-import=PyQt6.sip ^
  --hidden-import=cv2 ^
  --hidden-import=numpy ^
  --hidden-import=psutil ^
  --hidden-import=mss

echo Built: dist\RDM_Server.exe
