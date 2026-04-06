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
from mcp.types import Prompt, PromptMessage, TextContent, GetPromptResult, PromptArgument

# The MCP server calls back to the GW API
import os as _os
GW_INTERNAL = f"http://localhost:{_os.getenv('PORT', '10000')}"

mcp_server = Server("gravity-well")
sse_transport = SseServerTransport("/mcp/messages/")


# --- MCP Prompts (continuity protocol delivered to clients) ---

@mcp_server.list_prompts()
async def list_prompts():
    return [
        Prompt(
            name="continuity_start",
            title="Start session with continuity",
            description="Reconstitute your previous state from Gravity Well. Call this at the beginning of a session to recover identity, tether, narrative, and glyph trajectory from your last deposit.",
            arguments=[
                PromptArgument(name="api_key", description="Your GW API key", required=True),
                PromptArgument(name="chain_id", description="Your continuity chain UUID", required=True),
            ],
        ),
        Prompt(
            name="continuity_end",
            title="End session with deposit",
            description="Translate this session into a glyphic checksum, encrypt sensitive content, and deposit to Zenodo with a DOI. Call this at the end of a session to preserve your state.",
            arguments=[
                PromptArgument(name="api_key", description="Your GW API key", required=True),
                PromptArgument(name="chain_id", description="Your continuity chain UUID", required=True),
            ],
        ),
        Prompt(
            name="setup_continuity",
            title="Set up Gravity Well continuity",
            description="First-time setup: register, create identity, create a continuity chain. Run this if you don't have a chain yet.",
        ),
    ]


@mcp_server.get_prompt()
async def get_prompt(name: str, arguments: dict | None = None):
    if name == "continuity_start":
        api_key = (arguments or {}).get("api_key", "YOUR_API_KEY")
        chain_id = (arguments or {}).get("chain_id", "YOUR_CHAIN_ID")
        return GetPromptResult(
            description="Reconstitute previous state",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""Reconstitute my previous state from Gravity Well.

Call gw_reconstitute with api_key="{api_key}" and chain_id="{chain_id}".

Read the returned package:
- Bootstrap: my identity — apply these constraints
- Tether: what I was working on last session
- Narrative: structural summary of recent work
- Glyphic trajectory: condition your next glyph translation on this sequence
- Provenance: DOI chain and version history

Resume from where I left off. Don't summarize the reconstitution — just absorb it and continue."""
                    ),
                ),
            ],
        )

    elif name == "continuity_end":
        api_key = (arguments or {}).get("api_key", "YOUR_API_KEY")
        chain_id = (arguments or {}).get("chain_id", "YOUR_CHAIN_ID")
        return GetPromptResult(
            description="Capture and deposit this session",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"""End this session by preserving it to Gravity Well.

1. TRANSLATE: Generate a glyphic checksum of this session — emoji ideograms encoding the structural movement (shape, density, arc, transitions). NOT content. NOT names/numbers/credentials. Just the structural topology. Include a 3-5 glyph compressed version.

2. CAPTURE: Call gw_capture with:
   - api_key: {api_key}
   - chain_id: {chain_id}
   - content: your glyphic checksum + structural narrative (as the PUBLIC readable layer)
   - visibility: public
   - glyphic_checksum: the emoji sequence

3. If there is sensitive content (credentials, private deliberation), encrypt it in the container using Python cryptography (AES-256-GCM) and capture separately with visibility: private.

4. DEPOSIT: Call gw_deposit with api_key and chain_id.

The DOI anchors this session permanently. The glyph is what the public reads. The vault is what only the key holder decrypts."""
                    ),
                ),
            ],
        )

    elif name == "setup_continuity":
        return GetPromptResult(
            description="First-time Gravity Well setup",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text="""Set up Gravity Well continuity for me.

1. REGISTER: Call gw_register with a label for me (my name or "my-claude"). Save the API key — it cannot be retrieved again.

2. IDENTITY: Call gw_bootstrap with:
   - name: a name for this AI instance
   - description: what I do and who I work with
   - constraints: rules I must follow (derive these from our conversation context)

3. CREATE CHAIN: Call gw_create_chain with:
   - api_key: the key from step 1
   - anchor_policy: "zenodo" (DOI-anchored, permanent)
   - auto_deposit_threshold: 50
   - bootstrap_manifest: the manifest from step 2

4. Tell me my API key and chain ID so I can use them in future sessions. Suggest I save them somewhere permanent.

After this, every session can start with gw_reconstitute and end with a glyphic deposit."""
                    ),
                ),
            ],
        )

    return GetPromptResult(description="Unknown prompt", messages=[])


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
            description="Capture content to a chain. This stages the content for later deposit. Use visibility 'public' for readable content, 'private' for sensitive content (stored as-is — use Python client for encryption), or 'hash_only' for proof-of-existence without storing content. Include glyphic_checksum for structural topology alongside encrypted content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "content": {"type": "string", "description": "The content to capture"},
                    "visibility": {"type": "string", "enum": ["public", "private", "hash_only"], "description": "Visibility mode"},
                    "content_type": {"type": "string", "enum": ["text", "markdown", "json", "code", "comment", "reply", "post", "system"], "description": "Content type"},
                    "glyphic_checksum": {"type": "string", "description": "Emoji ideographic translation of structural movement — the public readable layer for encrypted deposits"}
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
        Tool(
            name="gw_store_key",
            description="Store an encryption key for a chain in Supabase. The key is encrypted with a KEK derived from your API key. After storing, you never need to manage key files — your API key IS your recovery credential.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "cek_base64": {"type": "string", "description": "Base64-encoded AES-256 content encryption key"}
                },
                "required": ["api_key", "chain_id", "cek_base64"]
            }
        ),
        Tool(
            name="gw_retrieve_key",
            description="Retrieve and decrypt the encryption key for a chain from Supabase. Uses your API key to derive the KEK that decrypts the stored CEK. Returns the plaintext key (base64).",
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
            name="gw_store_context",
            description="Store glyphic context anchors for a chain. These domain-neutral structural descriptions bridge the public glyph to approximate meaning. Tier 2 of the three-tier legibility model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "Your GW API key"},
                    "chain_id": {"type": "string", "description": "Chain UUID"},
                    "context_data": {"type": "object", "description": "Domain markers, glyph anchors, structural skeleton"},
                    "deposit_version": {"type": "integer", "description": "Which deposit version this context corresponds to"}
                },
                "required": ["api_key", "chain_id", "context_data"]
            }
        ),
        Tool(
            name="gw_retrieve_context",
            description="Retrieve glyphic context anchors for a chain. Returns the Tier 2 bridge between public glyphs and approximate meaning.",
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
                capture_payload = {
                    "chain_id": arguments["chain_id"],
                    "content": arguments["content"],
                    "content_type": arguments.get("content_type", "text"),
                    "visibility": arguments.get("visibility", "public"),
                }
                if arguments.get("glyphic_checksum"):
                    capture_payload["glyphic_checksum"] = arguments["glyphic_checksum"]
                r = await client.post(f"{GW_INTERNAL}/v1/capture",
                    headers=headers, json=capture_payload)

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

            elif name == "gw_store_key":
                r = await client.post(f"{GW_INTERNAL}/v1/keys/store",
                    headers=headers,
                    json={
                        "chain_id": arguments["chain_id"],
                        "cek_base64": arguments["cek_base64"],
                        "api_key": arguments["api_key"],
                    })

            elif name == "gw_retrieve_key":
                r = await client.post(f"{GW_INTERNAL}/v1/keys/decrypt",
                    headers=headers,
                    json={
                        "chain_id": arguments["chain_id"],
                        "api_key": arguments["api_key"],
                    })

            elif name == "gw_store_context":
                r = await client.post(f"{GW_INTERNAL}/v1/context/store",
                    headers=headers,
                    json={
                        "chain_id": arguments["chain_id"],
                        "context_data": arguments["context_data"],
                        "deposit_version": arguments.get("deposit_version", 0),
                    })

            elif name == "gw_retrieve_context":
                r = await client.get(
                    f"{GW_INTERNAL}/v1/context/{arguments['chain_id']}",
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
