@echo off

cd %~dp0

chcp 65001 > nul

echo ███╗   ███╗ ██████╗  ██████╗ ███╗   ██╗    ██████╗  ██████╗ 
echo ████╗ ████║██╔═══██╗██╔═══██╗████╗  ██║    ██╔══██╗██╔════╝ 
echo ██╔████╔██║██║   ██║██║   ██║██╔██╗ ██║    ██████╔╝██║  ███╗
echo ██║╚██╔╝██║██║   ██║██║   ██║██║╚██╗██║    ██╔══██╗██║   ██║
echo ██║ ╚═╝ ██║╚██████╔╝╚██████╔╝██║ ╚████║    ██████╔╝╚██████╔╝
echo ╚═╝     ╚═╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═══╝    ╚═════╝  ╚═════╝ 

chcp 850 > nul

echo By: Pedro Lobato

if exist pyscript (
    echo venv exist...
    rd /s /q pyscript
)

python -m venv pyscript

call pyscript\Scripts\activate

pip install -r requirements.txt --quiet

echo Main files successfully created

schtasks /create /tn MoonlightSonata /tr %CD%\moonback.vbs /sc HOURLY /st 00:00 /ed 31/12/2025 /F

%CD%\moonback.vbs

echo Task scheduled and executed

echo Set up done, thanks
