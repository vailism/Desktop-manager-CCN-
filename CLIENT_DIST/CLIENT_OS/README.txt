===========================================================
REMOTE DESKTOP MANAGER - CLIENT AGENT (PRODUCTION BUNDLE)
===========================================================

1. OVERVIEW
-----------
This is a lightweight agent designed for remote monitoring 
and management. It connects back to an RDM Server.

2. PREREQUISITES
----------------
- Python 3.10+ installed.
- Install dependencies:
  pip install -r requirements.txt

3. CONFIGURATION
----------------
Edit 'rdm_project/client/config.json' before launching:

- server_ip:   The IP address of the Server machine.
- port:        The TCP port (Default: 5029).
- password:    Must match the Server's authentication key.
- client_name: Friendly name for this workstation.

4. HOW TO RUN
-------------
Open a terminal in this folder and run:
python rdm_client_app.py

5. NOTES
--------
- Firewall: Ensure port 5029 is allowed for outbound traffic.
- Security: All data is sent over the configured port.
===========================================================
