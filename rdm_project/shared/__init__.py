"""
Shared library for Nexus Remote Desktop Manager.
Contains constants, packet serialization, and core protocol definitions 
used by both the server and the client.
"""
from rdm_project.shared.constants import *
from rdm_project.shared.packet import Packet, pack_packet, recv_packet, send_packet
from rdm_project.shared.protocol import MessageType
