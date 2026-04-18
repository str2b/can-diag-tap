# CAN Diagnostic Trace

Setup:

```powershell
cd can_diag_trace
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

CLI:

```powershell
can-diag-trace -t ..\test_input\msvread_sorted.asc -P ..\plugins\trace_printer.py --defs ..\test_input\kwp_defs.json
```
