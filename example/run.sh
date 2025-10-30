#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

# --- Lecture des options ---
ENTITY_PREFIX="$(jq -r '.entity_prefix // "slqne"' "$OPTIONS_FILE")"
UPDATE_INTERVAL="$(jq -r '.update_interval // 3600' "$OPTIONS_FILE")"

MQTT_HOST="$(jq -r '.mqtt_host // empty' "$OPTIONS_FILE")"
MQTT_PORT="$(jq -r '.mqtt_port // 1883' "$OPTIONS_FILE")"
MQTT_USER="$(jq -r '.mqtt_username // empty' "$OPTIONS_FILE")"
MQTT_PASS="$(jq -r '.mqtt_password // empty' "$OPTIONS_FILE")"
DISCOVERY_PREFIX="$(jq -r '.discovery_prefix // "homeassistant"' "$OPTIONS_FILE")"

# --- Multi-équipes (même logique que RSEQ) ---
TEAMS_JSON="$(jq -c '
  if (.teams // []) | length > 0 then
    .teams
  elif (.team_url // "") != "" then
    [ { "name": "default", "team_url": .team_url } ]
  else
    []
  end
' "$OPTIONS_FILE")"

# --- Validation ---
if [[ "$TEAMS_JSON" == "[]" ]]; then
  echo "[ERREUR] Aucune équipe configurée."
  echo "→ Ajoute dans config :"
  echo "teams:"
  echo "  - name: Hayden Hockey"
  echo "    team_url: https://page.spordle.com/... "
  echo "  - name: Loik Hockey"
  echo "    team_url: https://page.spordle.com/... "
  exit 1
fi

echo "[INFO] Démarrage de l'add-on SLQNE Hockey Stats"
echo "[INFO] MQTT                = ${MQTT_HOST:-<non défini>}:$MQTT_PORT"
echo "[INFO] Discovery prefix    = $DISCOVERY_PREFIX"
echo "[INFO] Intervalle (sec)    = $UPDATE_INTERVAL"
echo "[INFO] Entity prefix       = $ENTITY_PREFIX"
echo "[INFO] Équipes configurées :"
echo "$TEAMS_JSON" | jq -r '.[] | "- \(.name) -> \(.team_url)"'

# --- Boucle principale ---
while true; do
  echo "[INFO] Exécution du script Python SLQNE…"
  python3 /app/script.py \
    --teams-json "$TEAMS_JSON" \
    --entity_prefix "$ENTITY_PREFIX" \
    --mqtt_host "$MQTT_HOST" \
    --mqtt_port "$MQTT_PORT" \
    --mqtt_user "$MQTT_USER" \
    --mqtt_pass "$MQTT_PASS" \
    --discovery_prefix "$DISCOVERY_PREFIX"

  echo "[INFO] Attente ${UPDATE_INTERVAL}s avant prochaine exécution..."
  sleep "$UPDATE_INTERVAL"
done
