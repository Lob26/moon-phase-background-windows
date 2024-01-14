@echo off

cd %~dp0

python -m venv pyscript

call pyscript\Scripts\activate

pip install -r requirements.txt

deactivate

schtasks /create /tn MoonlightSonata /tr %CD%\moonback.vbs /sc HOURLY /ed 31/12/2024