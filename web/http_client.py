"""HTTP client shim for web-facing requests.

Niquests is mostly requests-compatible and can use newer transports such as
HTTP/2 and HTTP/3. Keep requests as a fallback so existing installs continue to
run until dependencies are refreshed.
"""

try:
    import niquests as http  # type: ignore
except Exception:
    import requests as http  # type: ignore
