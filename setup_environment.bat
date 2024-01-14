@echo off

python -m venv pyscripts

call pyscripts\Scripts\activate

pip install -r requirements.txt

deactivate

