@echo off
rem Double-click this file to use Civitas without typing commands.
cd /d "%~dp0"
title Civitas
python --version >nul 2>&1 || (echo Python was not found. Install Python 3.10+ from python.org and tick "Add to PATH". & pause & exit /b)
python -c "import numpy" >nul 2>&1 || python -m pip install -r requirements.txt

:menu
cls
echo  ==========================================================
echo                         C I V I T A S
echo  ==========================================================
echo   1. Run the default simulation (40 years)
echo   2. Boom scenario
echo   3. Collapse scenario
echo   4. Tragedy of the commons
echo   5. Ostrom (community-governed commons)
echo   6. My own mix of behaviour and rules (guided)
echo   7. Levers: which factors cause a boom or a collapse? (~10 min)
echo   8. Commons study: the research question (~10 min)
echo   9. Open all saved results in the browser
echo  10. Open the guide for making your own mix
echo   0. Quit
echo.
set "choice="
set /p choice=Choose a number and press Enter:
if "%choice%"=="1" python main.py --no-interactive
if "%choice%"=="2" python main.py --scenario boom --no-interactive
if "%choice%"=="3" python main.py --scenario collapse --no-interactive
if "%choice%"=="4" python main.py --scenario tragedy_of_the_commons --no-interactive
if "%choice%"=="5" python main.py --scenario ostrom --no-interactive
if "%choice%"=="6" goto mix
if "%choice%"=="7" python main.py levers
if "%choice%"=="8" python main.py commons
if "%choice%"=="9" python main.py serve
if "%choice%"=="10" start "" notepad "MY_OWN_MIX_GUIDE.txt"
if "%choice%"=="0" exit /b
goto menu

:mix
cls
echo  Build your own society. Press Enter to keep any default.
echo  Trait shifts are in standard deviations: -1 (much lower) ... 0 (normal) ... +1 (much higher).
echo  See MY_OWN_MIX_GUIDE.txt for what every option means.
echo.
set "h=0" & set "a=0" & set "c=0" & set "o=0" & set "n=0" & set "i=0" & set "x=0"
set /p h=Honesty           [0]:
set /p a=Agreeableness     [0]:
set /p c=Conscientiousness [0]:
set /p o=Openness          [0]:
set /p n=Neuroticism       [0]:
set /p i=Intelligence      [0]:
set /p x=Extraversion      [0]:
echo.
echo  Resource rules: open_access, regulated, equal_shares, need_based, private_ownership
set "rule=regulated"
set /p rule=Resource rule [regulated]:
set "years=40"
set /p years=Years to simulate [40]:
set "seed=42"
set /p seed=Random seed [42]:
echo.
echo  Optional extra settings, e.g.  policy.education_subsidy=0.9 policy.police_per_1000=8
set "extra="
set /p extra=Extra settings [none]:
python main.py --no-interactive --tag my_mix --years %years% --seed %seed% --rule %rule% --trait honesty=%h% --trait agreeableness=%a% --trait conscientiousness=%c% --trait openness=%o% --trait neuroticism=%n% --trait intelligence=%i% --trait extraversion=%x% --extra "%extra%"
pause
goto menu
