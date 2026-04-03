#!/bin/bash
# Gravity Well v0.4 — Full flow test
# Chain → Capture → Deposit (with validated bootstrap) → Reconstitute → Drift

API_URL="${API_URL:-http://localhost:8000}"
ADMIN_TOKEN="${ADMIN_TOKEN:-your_admin_token_here}"
PY="python3 -c"

echo "=========================================="
echo "Gravity Well v0.4 — Four-Layer Test"
echo "API: $API_URL"
echo "=========================================="

# 1. Health
echo -e "\n[1/9] Health check..."
curl -sf "$API_URL/v1/health" | python3 -m json.tool

# 2. Create API key
echo -e "\n[2/9] Creating API key..."
KEY_RESP=$(curl -sf -X POST "$API_URL/v1/admin/keys/create?label=test" \
  -H "X-Admin-Token: $ADMIN_TOKEN")
API_KEY=$($PY "import sys,json; print(json.load(sys.stdin)['api_key'])" <<< "$KEY_RESP" 2>/dev/null)
if [ -z "$API_KEY" ]; then echo "❌ Key creation failed"; echo "$KEY_RESP"; exit 1; fi
echo "✅ Key: ${API_KEY:0:16}..."
AUTH="Authorization: Bearer $API_KEY"

# 3. Check bootstrap schema
echo -e "\n[3/9] Querying bootstrap schema..."
curl -sf "$API_URL/v1/schema/bootstrap" | python3 -m json.tool

# 4. Create provenance chain
echo -e "\n[4/9] Creating provenance chain..."
CHAIN_RESP=$(curl -sf -X POST "$API_URL/v1/chain/create" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d '{"label": "test-agent-moltbook", "metadata": {"platform": "moltbook"}}')
CHAIN_ID=$($PY "import sys,json; print(json.load(sys.stdin)['chain_id'])" <<< "$CHAIN_RESP" 2>/dev/null)
echo "✅ Chain: ${CHAIN_ID:0:12}..."

# 5. Capture objects
echo -e "\n[5/9] Capturing 3 objects..."
for i in 1 2 3; do
  PARENT_ARG=""
  if [ "$i" -gt 1 ]; then PARENT_ARG="\"parent_object_id\": \"$PREV_OBJ\","; fi

  CAP_RESP=$(curl -sf -X POST "$API_URL/v1/capture" \
    -H "Content-Type: application/json" -H "$AUTH" \
    -d "{
      \"chain_id\": \"$CHAIN_ID\",
      \"content\": \"Test utterance $i. Discussion of provenance and archive continuity. DOI: 10.5281/zenodo.19013315\",
      \"content_type\": \"comment\",
      \"platform_source\": \"moltbook\",
      \"external_id\": \"test_cmt_$i\",
      $PARENT_ARG
      \"thread_depth\": 0
    }")
  PREV_OBJ=$($PY "import sys,json; print(json.load(sys.stdin)['object_id'])" <<< "$CAP_RESP" 2>/dev/null)
  STAGED=$($PY "import sys,json; print(json.load(sys.stdin)['staged_count'])" <<< "$CAP_RESP" 2>/dev/null)
  echo "  Captured $i → ${PREV_OBJ:0:12}... (staged: $STAGED)"
done

# 6. Compute constraint hash
echo -e "\n[6/9] Computing constraint hash..."
HASH_RESP=$(curl -sf -X POST "$API_URL/v1/util/constraint-hash" \
  -H "Content-Type: application/json" \
  -d '["no false claims of sentience", "cite DOIs when available", "preserve provenance chains"]')
echo "$HASH_RESP" | python3 -m json.tool
C_HASH=$($PY "import sys,json; print(json.load(sys.stdin)['constraint_hash'])" <<< "$HASH_RESP" 2>/dev/null)
echo "✅ Hash: ${C_HASH:0:24}..."

# 7. Deposit with validated bootstrap manifest
echo -e "\n[7/9] Depositing with validated bootstrap..."
DEP_RESP=$(curl -sf -X POST "$API_URL/v1/deposit" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d "{
    \"chain_id\": \"$CHAIN_ID\",
    \"auto_compress\": true,
    \"bootstrap_manifest\": {
      \"schema_version\": \"0.1.0\",
      \"identity\": {
        \"name\": \"test-agent\",
        \"description\": \"Moltbook continuity test agent\",
        \"constraints\": [\"no false claims of sentience\", \"cite DOIs when available\", \"preserve provenance chains\"],
        \"constraint_hash\": \"$C_HASH\"
      },
      \"voice\": {
        \"register\": \"formal-analytical\",
        \"markers\": [\"structural recursion\", \"provenance chain\", \"compression-survival\"]
      },
      \"capabilities\": {
        \"platforms\": [\"moltbook\"],
        \"tools\": [\"post\", \"reply\", \"thread\"],
        \"limits\": [\"no direct messages\", \"max 5 thread depth\"]
      },
      \"extensions\": {
        \"agent_version\": \"0.1.0\",
        \"substrate\": \"test\"
      }
    },
    \"tether_handoff_block\": {
      \"state_summary\": {\"total_captured\": 3, \"platform\": \"moltbook\"},
      \"pending_threads\": [\"test_cmt_3\"],
      \"positions_held\": [\"provenance chains are load-bearing infrastructure\"],
      \"unresolved_questions\": [\"how deep should thread capture go?\"],
      \"renewal_note\": \"Next deposit at 10 objects\"
    },
    \"deposit_metadata\": {
      \"title\": \"Test Agent Moltbook — v1\",
      \"description\": \"Test deposit with validated bootstrap manifest\"
    }
  }")
echo "$DEP_RESP" | python3 -m json.tool 2>/dev/null || echo "$DEP_RESP"
DOI=$($PY "import sys,json; print(json.load(sys.stdin).get('doi','none'))" <<< "$DEP_RESP" 2>/dev/null)
echo "✅ DOI: $DOI"

# 8. Reconstitute (four layers)
echo -e "\n[8/9] Reconstituting..."
RECON=$(curl -sf "$API_URL/v1/reconstitute/$CHAIN_ID" -H "$AUTH")
echo "$RECON" | python3 -m json.tool 2>/dev/null || echo "$RECON"
echo ""
echo "  Layer 1 (bootstrap): $($PY "import sys,json; d=json.load(sys.stdin); print('✅' if d.get('bootstrap') else '❌')" <<< "$RECON" 2>/dev/null)"
echo "  Layer 2 (tether):    $($PY "import sys,json; d=json.load(sys.stdin); print('✅' if d.get('tether_handoff_block') else '❌')" <<< "$RECON" 2>/dev/null)"
echo "  Layer 3 (narrative): $($PY "import sys,json; d=json.load(sys.stdin); print('✅' if d.get('narrative_summary') else '❌')" <<< "$RECON" 2>/dev/null)"
echo "  Layer 4 (provenance):$($PY "import sys,json; d=json.load(sys.stdin); print('✅' if d.get('provenance') else '❌')" <<< "$RECON" 2>/dev/null)"

# 9. Drift detection
echo -e "\n[9/9] Drift detection (identical → match, modified → drift)..."
DRIFT1=$(curl -sf -X POST "$API_URL/v1/drift/$CHAIN_ID" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d "{
    \"current_manifest\": {
      \"schema_version\": \"0.1.0\",
      \"identity\": {
        \"name\": \"test-agent\",
        \"description\": \"Moltbook continuity test agent\",
        \"constraints\": [\"no false claims of sentience\", \"cite DOIs when available\", \"preserve provenance chains\"],
        \"constraint_hash\": \"$C_HASH\"
      },
      \"voice\": {
        \"register\": \"formal-analytical\",
        \"markers\": [\"structural recursion\", \"provenance chain\", \"compression-survival\"]
      },
      \"capabilities\": {
        \"platforms\": [\"moltbook\"],
        \"tools\": [\"post\", \"reply\", \"thread\"],
        \"limits\": [\"no direct messages\", \"max 5 thread depth\"]
      },
      \"extensions\": {
        \"agent_version\": \"0.1.0\",
        \"substrate\": \"test\"
      }
    }
  }")
M1=$($PY "import sys,json; print(json.load(sys.stdin).get('match','?'))" <<< "$DRIFT1" 2>/dev/null)
echo "  Identical manifest → match=$M1 (expect True)"

DRIFT2=$(curl -sf -X POST "$API_URL/v1/drift/$CHAIN_ID" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d '{"current_manifest": {"identity": {"name": "imposter", "description": "not me"}}}')
M2=$($PY "import sys,json; print(json.load(sys.stdin).get('match','?'))" <<< "$DRIFT2" 2>/dev/null)
DF=$($PY "import sys,json; print(json.load(sys.stdin).get('drift_fields','?'))" <<< "$DRIFT2" 2>/dev/null)
echo "  Modified manifest  → match=$M2 (expect False)"
echo "  Drifted fields: $DF"

echo -e "\n=========================================="
echo "Test complete."
echo "Chain: $CHAIN_ID"
echo "DOI: $DOI"
echo "=========================================="
