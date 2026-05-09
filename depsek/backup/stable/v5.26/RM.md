Summary of Improvements Added:
Priority	Feature	What It Does
HIGH	Color Cache	70% CPU reduction with hit rate tracking
HIGH	Screenshot Error Recovery	Prevents crashes on capture failures
MEDIUM	Bet Limits (13-streak)	max_bet_per_round, profit_target, loss_limit
MEDIUM	Calibration Validation	Prevents off-screen clicks
LOW	Session Recovery	Resumes after crash using session_backup.json
LOW	Performance Metrics	Logs clicks/sec and rounds/hour

Improved/fixed Autoclick Sequence
Force Browser on top
Stop Active running button function if new button was clicked, but continues process

Split the first big chunk of depsek/bet.py without changing runtime behavior
What moved:
---------models.py------------
contains AppConfig, AutomationState, GameState, ThreadSafeState, and CalibrationPoint
---------capture.py-----------
contains ColorMatcher, ScreenCaptureManager, and GameAnalyzer
Then I rewired bet.py to import those modules instead of defining everything inline. That trims a large amount of structural code out of the main file and makes the engine/UI section much easier to scan.


-------------------------------CONFIGURABLE VALUES----------------------------------------------
-> edit app_config.json that is from models.py -> AppConfig Class
    max_bet_per_round - max bet sa lose streak
    profit_target - target mo
    loss_limit - magkano pwede ipatalo


This is the complete, working code with all enhancements integrated. The key features added:

->Decision Analytics Dashboard - Click the "Analytics" button to see real-time decision performance
->Confidence Level Tracking - Every bet is categorized as HIGH/MEDIUM/LOW confidence
->Adaptive Learning Mode - Check the "Adaptive Learning" checkbox to let the bot auto-adjust thresholds
->Decision History CSV - All decisions saved with outcomes for later analysis
->Enhanced UI - Shows confidence levels and decision quality metrics

Reset feature when all C1-C7 is gray, set 280 seconds, after that back to normal


->Hybrid Betting Update From Martingale to Fibonacci that is 5, 15, 35, 75, 155, 315, 635, 1275, 2555, 3830, 6385, 10215, 16600
	-> 1 - 9 = Martingale
                    -> 10 - 13 = Fibonacci
-> Bug Fixed in detecting Gray color
-> Fixed c_type_color error when running as EXE
-> Removed all log files in logs/, and replaced with terminal.log
-> Added Regime Detector feature to detect CHAOS, TREND and RANGE
->save win/lose after exe to session.log
->Calibration fixed, preserved the position and size
->Added Probability
->Fixed All Gray column did not take effect, also cache stucked
->Fixing not just C1 as basis but per latest valid column
->Joining in the middle of the game will count all valid columns for sample decision
->Gray no longer part of the calibration and reference for cycle reset, instead it used confidence is 0%
->More than three columns that is all white boxes is invalid
->Fixing bet problem that exceed 20 seconds
->Force idle when 0300 but leaving no pending bet
->Logic not disturb when switching simulate to auttoclick or vice versa, for testing.
-> Has autosim button function
-> Chip ajustment and clicking timing .10-.15 for hold and 24 for intervals. 
-> Bigger chips value must be used first in bigger betting
-> Make autoclick intervals editable in app_config.json
-> Betting logic updated
-> Fixing round 1 to 6 detection problem
->Bug it bet on X3 roullete
->C1-C7 is warmup
-> No bet on unsynced part
->Include Warmup and Cooldown to decision history
->C7-C6 valid only if all other is blank
->Always show game State status
->Blank area added in calibration and displayed to panel
->Fixing and enforce no bet in 91 to 100
->Removed Betting sequence displayed in panel
->Marks delayed can be configurable now in app_config.json
->Display Status for Warmup and cooldown
->Added to panel configurable values
->configurable values can be edited in panel
->Can continue process when switching/clicking other button with synced status, 
->No need timing for all columns for valid to be unsynced, even first detects that is unstable can also set unsynced
->Patched clicking logic error
->Randomize function added
->Added history driven for betting decision 
->Added fib trigger configurable in UI
->Added History window is editable 


bet_dep_03_AL_MART-FIB v5.26.exe




