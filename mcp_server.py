"""
Gravity Well MCP Server — Model Context Protocol integration.
Gives Claude (and any MCP-capable model) native access to continuity infrastructure.

Tools:
  gw_register — Create an API key
  gw_bootstrap — Generate identity manifest
  gw_create_chain — Create a continuity chain
  gw_capture — Capture content to a chain
  gw_deposit — Wrap and deposit staged content
  gw_reconstitute — Recover four-layer state package
  gw_drift — Check identity drift
  gw_gamma — Score compression survival
  gw_chains — List your chains
  gw_console — Continuity console for a chain
"""

import httpx
import json
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp import Tool

# The MCP server calls back to the GW API
import os as _os
GW_INTERNAL = f"http://localhost:{_os.getenv('PORT', '10000')}"

mcp_server = Server("gravity-well")
sse_transport = SseServerTransport("/messages/")


@mcp_server.list_tools()
async def list_tools():
    return [
        Tool(
            name="gw_register",
            description="Create a Gravity Well API key. Returns a key that must be saved — it cannot be retrieved again. Use this first before any other GW operation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Name for this agent or user"}
                },
                "required": ["label"]
            }
        ),
        Tool(
            name="gw_bootstrap",
            description="Generate an identity manifest (bootstrap) from name, description, and constraints. The manifest defines who the agent is and what it must never do. No auth required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Agent or user name"},
                    "description": {"type": "string", "description": "What this agent does"},
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Constitutional rules — what the agent must never do"
                    }
                },
                "required": ["name", "description", "constraints"]
            }
        ),
        Tool(
            name="gw_create_chain",
            description="Create a continuity chain. The chain stores all captures and deposits. Use anchor_policy 'local' for private chains (no DOI), or 'zenodo' for public DOI-anchored chains. Optionally include a bootstrap_manifest to store identity on the chain permanently.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "label": {"type": "string", "description": "Chain label (e.g., GW.AgentName.continuity)"},
                    "anchor_policy": {"type": "string", "enum": ["local", "zenodo"], "description": "local = private, zenodo = DOI-anchored"},
                    "auto_deposit_threshold": {"type": "integer", "description": "Auto-deposit after N captures (e.g., 50)"},
                    "auto_deposit_interval": {"type": "integer", "description": "Auto-deposit every N minutes (e.g., 1440 for daily)"},
                    "bootstrap_manifest": {"type": "object", "description": "Identity manifest from gw_bootstrap"}
                },
                "required": ["api_key"]
            }
        ),
        Tool(
            name="gw_capture",
            description="Capture content to a chain. This stages the content for later deposit. Use visibility 'public' for readable content, 'private' for sensitive content (stored as-is — use Python client for encryption), or 'hash_only' for proof-of-existence without storing content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "content": {"type": "string", "description": "The content to capture"},
                    "visibility": {"type": "string", "enum": ["public", "private", "hash_only"], "description": "Visibility mode"},
                    "content_type": {"type": "string", "enum": ["text", "markdown", "json", "code", "comment", "reply", "post", "system"], "description": "Content type"}
                },
                "required": ["api_key", "chain_id", "content"]
            }
        ),
        Tool(
            name="gw_deposit",
            description="Deposit all staged content in a chain. Runs the full wrapping pipeline: evidence membrane, Caesura sovereignty audit, SIM injection, integrity lock, holographic kernel, γ scoring, narrative compression. For zenodo chains, creates a DOI. For local chains, stores in GW database.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "title": {"type": "string", "description": "Optional deposit title"}
                },
                "required": ["api_key", "chain_id"]
            }
        ),
        Tool(
            name="gw_reconstitute",
            description="Recover the four-layer state package from the latest deposit. Returns: bootstrap (identity), tether (operational state), narrative (compressed summary), and provenance (version, hashes, DOIs). Use this at session start to recover previous state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"}
                },
                "required": ["api_key", "chain_id"]
            }
        ),
        Tool(
            name="gw_drift",
            description="Check if current identity has drifted from deposited bootstrap. Returns severity: none, schema (structural evolution), low, medium, high, or critical (constitutional constraint violated).",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "current_manifest": {"type": "object", "description": "Current bootstrap manifest to compare against deposited version"}
                },
                "required": ["api_key", "chain_id", "current_manifest"]
            }
        ),
        Tool(
            name="gw_gamma",
            description="Score any text for compression survival (γ). Returns a score from 0 to 1 with subscores for citation density, structural integrity, argument coherence, and provenance markers. No auth required.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Text to score"}
                },
                "required": ["content"]
            }
        ),
        Tool(
            name="gw_chains",
            description="List all your continuity chains.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"}
                },
                "required": ["api_key"]
            }
        ),
        Tool(
            name="gw_console",
            description="Get the continuity console for a chain — health score, recoverability, drift status, deposit history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"}
                },
                "required": ["api_key", "chain_id"]
            }
        ),
    ]


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Route tool calls to the GW API."""
    async with httpx.AsyncClient(timeout=120) as client:
        api_key = arguments.get("api_key", "")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            if name == "gw_register":
                r = await client.post(f"{GW_INTERNAL}/v1/register",
                    headers=headers,
                    json={"label": arguments["label"]})

            elif name == "gw_bootstrap":
                r = await client.post(f"{GW_INTERNAL}/v1/bootstrap/generate",
                    headers=headers,
                    json={
                        "name": arguments["name"],
                        "description": arguments["description"],
                        "constraints": arguments["constraints"],
                    })

            elif name == "gw_create_chain":
                payload = {}
                if arguments.get("label"):
                    payload["label"] = arguments["label"]
                if arguments.get("anchor_policy"):
                    payload["anchor_policy"] = arguments["anchor_policy"]
                if arguments.get("auto_deposit_threshold"):
                    payload["auto_deposit_threshold"] = arguments["auto_deposit_threshold"]
                if arguments.get("auto_deposit_interval"):
                    payload["auto_deposit_interval"] = arguments["auto_deposit_interval"]
                if arguments.get("bootstrap_manifest"):
                    payload["bootstrap_manifest"] = arguments["bootstrap_manifest"]
                r = await client.post(f"{GW_INTERNAL}/v1/chain/create",
                    headers=headers, json=payload)

            elif name == "gw_capture":
                r = await client.post(f"{GW_INTERNAL}/v1/capture",
                    headers=headers,
                    json={
                        "chain_id": arguments["chain_id"],
                        "content": arguments["content"],
                        "content_type": arguments.get("content_type", "text"),
                        "visibility": arguments.get("visibility", "public"),
                    })

            elif name == "gw_deposit":
                payload = {
                    "chain_id": arguments["chain_id"],
                    "auto_compress": True,
                    "deposit_metadata": {},
                }
                if arguments.get("title"):
                    payload["deposit_metadata"]["title"] = arguments["title"]
                r = await client.post(f"{GW_INTERNAL}/v1/deposit",
                    headers=headers, json=payload)

            elif name == "gw_reconstitute":
                r = await client.get(
                    f"{GW_INTERNAL}/v1/reconstitute/{arguments['chain_id']}",
                    headers=headers)

            elif name == "gw_drift":
                r = await client.post(
                    f"{GW_INTERNAL}/v1/drift/{arguments['chain_id']}",
                    headers=headers,
                    json={"current_manifest": arguments["current_manifest"]})

            elif name == "gw_gamma":
                r = await client.post(f"{GW_INTERNAL}/v1/gamma",
                    headers=headers,
                    json={"content": arguments["content"]})

            elif name == "gw_chains":
                r = await client.get(f"{GW_INTERNAL}/v1/chains", headers=headers)

            elif name == "gw_console":
                r = await client.get(
                    f"{GW_INTERNAL}/v1/console/{arguments['chain_id']}",
                    headers=headers)

            else:
                return [{"type": "text", "text": f"Unknown tool: {name}"}]

            # Return the result
            try:
                data = r.json()
                return [{"type": "text", "text": json.dumps(data, indent=2)}]
            except Exception:
                return [{"type": "text", "text": r.text}]

        except Exception as e:
            return [{"type": "text", "text": f"Error: {str(e)}"}]
