# Remote Desktop Manager

## Project Structure

rdm_project/
- server/
  - core/
    - server.py
  - services/
    - connection_manager.py
  - ui/
    - server_ui.py
  - config.py
  - config.json
  - main.py
- client/
  - core/
    - client.py
    - base_client.py
    - connection.py
    - networking.py
  - system/
    - metrics.py
  - ui/
    - client_ui.py
  - config.py
  - config.json
  - main.py
- shared/
  - packet.py
  - protocol.py
  - constants.py
- assets/
  - icon.ico
  - icon.icns
- build/
  - build_client_windows.bat
  - build_client_mac.sh
  - build_server_windows.bat
  - build_server_mac.sh

## Run

Server:

```bash
python -m rdm_project.server.main
```

Client:

```bash
python -m rdm_project.client.main
```

## Build

Server (macOS):

```bash
bash rdm_project/build/build_server_mac.sh
```

Server (Windows):

```bat
rdm_project\build\build_server_windows.bat
```

Client (macOS):

```bash
bash rdm_project/build/build_client_mac.sh
```

Client (Windows):

```bat
rdm_project\build\build_client_windows.bat
```
