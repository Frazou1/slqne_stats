#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

# --------------------------------------------------------------------------
# Lecture des options de configuration
# --------------------------------------------------------------------------
ENTITY_PREFIX="$(jq -r '.entity_prefix // "slqne"' "$OPTIONS_FILE")"
UPDATE_INTERVAL="$(jq -r '.update_interval // 3600' "$OPTIONS_FILE")"

MQTT_HOST="$(jq -r '.mqtt_host // empty' "$OPTIONS_FILE")"
MQTT_PORT="$(jq -r '.mqtt_port // 1883' "$OPTIONS_FILE")"
MQTT_USER="$(jq -r '.mqtt_username // empty' "$OPTIONS_FILE")"
MQTT_PASS="$(jq -r '.mqtt_password // empty' "$OPTIONS_FILE")"
DISCOVERY_PREFIX="$(jq -r '.discovery_prefix // "homeassistant"' "$OPTIONS_FILE")"

# --------------------------------------------------------------------------
# Lecture du bloc "teams"
# --------------------------------------------------------------------------
TEAMS_JSON="$(jq -c '
  if (.teams // []) | length > 0 then
    .teams
  elif (.team_url // "") != "" then
    [ { "name": "default", "team_url": .team_url } ]
  else
    []
  end
' "$OPTIONS_FILE")"

if [[ "$TEAMS_JSON" == "[]" ]]; then
  echo "[ERREUR] Aucune équipe configurée."
  echo "→ Exemple attendu dans la configuration :"
  echo "teams:"
  echo "  - name: Hayden Hockey"
  echo "    league_id: bf27e08e-8d52-41be-a097-a6cf79f4466a"
  echo "    schedule_id: 183363"
  echo "  - name: Loik Hockey"
  echo "    league_id: 13c38dd1-e464-4835-af5f-75be8561daf6"
  echo "    schedule_id: 183367"
  exit 1
fi

# --------------------------------------------------------------------------
# Lecture du bloc "players" (nouveau)
# --------------------------------------------------------------------------
PLAYERS_JSON="$(jq -c '
  if (.players // []) | length > 0 then
    .players
  else
    []
  end
' "$OPTIONS_FILE")"

if [[ "$PLAYERS_JSON" != "[]" ]]; then
  echo "[INFO] Joueurs suivis :"
  echo "$PLAYERS_JSON" | jq -r '.[] | "- \(.player_name) (\(.team_name))"'
else
  echo "[INFO] Aucun joueur spécifique configuré."
fi

# --------------------------------------------------------------------------
# Informations de démarrage
# --------------------------------------------------------------------------
echo "[INFO] --------------------------------------------------------"
echo "[INFO] Démarrage de l'add-on SLQNE Hockey Stats"
echo "[INFO] MQTT                = ${MQTT_HOST:-<non défini>}:$MQTT_PORT"
echo "[INFO] Discovery prefix    = $DISCOVERY_PREFIX"
echo "[INFO] Intervalle (sec)    = $UPDATE_INTERVAL"
echo "[INFO] Entity prefix       = $ENTITY_PREFIX"
echo "[INFO] Équipes configurées :"
echo "$TEAMS_JSON" | jq -r '.[] | "- \(.name) -> \(.league_id // "?") / \(.schedule_id // "?")"'
echo "[INFO] --------------------------------------------------------"

# --------------------------------------------------------------------------
# Boucle principale
# --------------------------------------------------------------------------
while true; do
  echo "[INFO] Exécution du script Python SLQNE…"

  python3 /script.py \
    --teams-json "$TEAMS_JSON" \
    --players-json "$PLAYERS_JSON" \
    --entity_prefix "$ENTITY_PREFIX" \
    --mqtt_host "$MQTT_HOST" \
    --mqtt_port "$MQTT_PORT" \
    --mqtt_user "$MQTT_USER" \
    --mqtt_pass "$MQTT_PASS" \
    --discovery_prefix "$DISCOVERY_PREFIX"

  echo "[INFO] Attente ${UPDATE_INTERVAL}s avant prochaine exécution..."
  sleep "$UPDATE_INTERVAL"
done
