# Quick Start

Right-click `start_all.ps1` -> **Run with PowerShell**, or from a terminal:

```powershell
Set-Location "C:\LocationToProject"
powershell -ExecutionPolicy Bypass -File start_all.ps1
```

This opens 4 windows automatically, loads API keys from `.env`, and sets the IPs:

| Window | Service | Interpreter | Port |
|--------|---------|-------------|------|
| 1 | Facial Recognition API | `py -3.11` | 5002 |
| 2 | ChatGPT API | `py -3.11` | 5001 |
| 3 | Song Recognition API | `py -3.11` | 5003 |
| 4 | NAO Main Program | `python` (2.7) | 9559 |

**Current IPs:** Laptop `YOUR_LAPTOP_IP` / Robot `YOUR_ROBOT_IP`
