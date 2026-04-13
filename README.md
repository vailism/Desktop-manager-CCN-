# Remote Desktop Manager (Nexus)

A high-performance, cross-platform remote desktop management application built with Python. Designed with a premium, glassmorphism-inspired UI and a robust networking layer for real-time interaction, this application enables secure, efficient remote system management.

## Project Description

**Remote Desktop Manager (Nexus)** is a sophisticated, real-time administrative tool designed for IT professionals and power users. It streamlines the management of multiple remote endpoints through a unified, high-fidelity dashboard. By leveraging optimized socket protocols and hardware-accelerated rendering, Nexus provides a near-native experience even over high-latency networks.

Key highlights include:
- **Low-Latency Streaming**: Optimized JPEG compression and frame-skipping algorithms ensure smooth visual feedback.
- **Enterprise-Grade UI**: A cinematic dark-mode interface built on PySide6, featuring smooth transitions and intuitive layout.
- **Unified Control**: Centralized management for file transfers, system power states, volume controls, and network discovery.
- **Security-First**: Token-based authentication and restricted LAN scanning capabilities keep your network environment secure.

## Features

- **High-Performance Networking**: Built on robust socket-based communication with an optimized custom protocol.
- **Real-Time Monitoring**: Crystal-clear system metrics, dynamic latency tracking, and FPS calculation.
- **Premium User Interface**: A modern, Apple-style dark mode theme using PySide6 featuring smooth transitions, rounded corners, and sophisticated layout elements.
- **Cross-Platform**: Seamless operation on macOS and Windows, with standalone executables out-of-the-box.
- **Interactive Controls**: Advanced capabilities including remote screenshot captures, command execution, power state management (shutdown/restart), and volume controls.
- **Secure Connections**: Token-based authentication safeguarding against unauthorized access.

## Project Architecture

The architecture is divided into clear functional boundaries:

- **Server `(rdm_project/server)`**: The backend orchestrating connections and rendering the control interface. It listens for client devices and handles complex command routing and data streaming.
- **Client `(rdm_project/client)`**: A lightweight, resilient daemon that establishes a secure connection to the server, providing local system access with minimal overhead.
- **Shared Protocol `(rdm_project/shared)`**: Strongly-typed payload structures and constants guaranteeing a unified communication standard.

## Installation

### Prerequisites

Ensure you have Python 3.9+ installed and correctly configured in your system environment. Install the needed packages via PIP:

```bash
pip install -r requirements.txt
```

Note: It's highly recommended to use a virtual environment (`python -m venv .venv`).

## Usage During Development

**To start the Server application:**
```bash
python -m rdm_project.server.main
```
*(Or use the top-level script: `python rdm_server_app.py`)*

**To start a Client node:**
```bash
python -m rdm_project.client.main
```
*(Or use the top-level script: `python rdm_client_app.py`)*

## Building Executables

We use `PyInstaller` to bundle the server and the client into standalone, distributable packages that do not require external Python interpreters to run.

### Build Scripts

- **macOS**
  - Server: `bash rdm_project/build/build_server_mac.sh`
  - Client: `bash rdm_project/build/build_client_mac.sh`

- **Windows**
  - Server: `rdm_project\build\build_server_windows.bat`
  - Client: `rdm_project\build\build_client_windows.bat`

Once the build is complete, generated executables are located under the `dist/` directory.

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
