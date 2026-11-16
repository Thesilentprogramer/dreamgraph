"""DreamGraph MCP tools, served at /mcp and through ``python -m dreamgraph.mcp``."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

API_URL = os.environ.get("DG_VERDICT_API_URL", f"http://127.0.0.1:{os.environ.get('PORT', '8000')}")
mcp = FastMCP(
    "DreamGraph",
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=["dreamgraph.onrender.com", "localhost:*", "127.0.0.1:*"],
        allowed_origins=["https://dreamgraph.onrender.com"],
    ),
)


@mcp.tool()
def check_vulnerability(cve: str, package: str, version: str) -> dict:
    """Check a CVE and package tag with DreamGraph's weighted trust vote."""

    body = json.dumps({"cve": cve, "package": package, "version": version}).encode()
    request = urllib.request.Request(
        f"{API_URL.rstrip('/')}/api/verdict",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=9) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read().decode()).get("detail", str(exc))
        return {"error": detail, "status_code": exc.code}
    except (TimeoutError, urllib.error.URLError) as exc:
        return {"error": f"DreamGraph request timed out or is unavailable: {exc}", "status_code": 503}


if __name__ == "__main__":
    mcp.run(transport="stdio")
