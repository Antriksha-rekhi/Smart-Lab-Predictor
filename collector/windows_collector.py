"""Send anonymous active-session status from a Windows lab PC to Spacewise."""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WTSSessionInfo(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", ctypes.c_int),
    ]


def has_active_user_session():
    """Check for an active non-system Windows session without reading its user name."""
    if os.name != "nt":
        raise RuntimeError("This collector runs on Windows lab computers only.")

    wts = ctypes.WinDLL("Wtsapi32", use_last_error=True)
    sessions = ctypes.POINTER(WTSSessionInfo)()
    count = wintypes.DWORD()
    wts.WTSEnumerateSessionsW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(WTSSessionInfo)), ctypes.POINTER(wintypes.DWORD),
    ]
    wts.WTSEnumerateSessionsW.restype = wintypes.BOOL
    wts.WTSFreeMemory.argtypes = [wintypes.LPVOID]

    if not wts.WTSEnumerateSessionsW(None, 0, 1, ctypes.byref(sessions), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        # WTSActive is 0. Session zero is reserved for Windows services.
        return any(sessions[index].SessionId != 0 and sessions[index].State == 0
                   for index in range(count.value))
    finally:
        wts.WTSFreeMemory(sessions)


def send_status(api_url, computer_id, token, status):
    payload = json.dumps({"computer_id": computer_id, "status": status}).encode("utf-8")
    request = Request(
        api_url.rstrip("/") + "/api/computer-status",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        response.read()


def main():
    api_url = os.environ.get("SPACEWISE_API_URL", "").strip()
    token = os.environ.get("COMPUTER_STATUS_TOKEN", "").strip()
    try:
        computer_id = int(os.environ.get("SPACEWISE_COMPUTER_ID", ""))
    except ValueError as error:
        raise RuntimeError("Set SPACEWISE_COMPUTER_ID to this PC's database ID.") from error
    if not api_url or not token or computer_id < 1:
        raise RuntimeError("Set SPACEWISE_API_URL, SPACEWISE_COMPUTER_ID, and COMPUTER_STATUS_TOKEN.")
    if api_url.startswith("http://") and "127.0.0.1" not in api_url and "localhost" not in api_url:
        print("Warning: use HTTPS for a deployed server so the token is encrypted in transit.", file=sys.stderr)

    print(f"Sending session status for computer ID {computer_id}; no usernames are collected.")
    while True:
        try:
            status = "occupied" if has_active_user_session() else "available"
            send_status(api_url, computer_id, token, status)
            print(f"Status sent: {status}")
        except (OSError, URLError, HTTPError, RuntimeError) as error:
            print(f"Status not sent: {error}", file=sys.stderr)
        time.sleep(30)


if __name__ == "__main__":
    main()
