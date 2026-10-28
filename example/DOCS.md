# SLQNE Hockey Stats — documentation

[Français](#français) | [English](#english)

---

## Français

### Description

**SLQNE Hockey Stats** (`slqne_hockey_stats`) est un module complémentaire (add-on) Home Assistant qui lit la page publique d'une ou de plusieurs équipes de hockey sur la plateforme **Spordle** (`page.spordle.com`) et publie dans Home Assistant, par **MQTT** (découverte automatique MQTT Discovery), le classement, les statistiques des joueurs, le dernier match et le prochain match.

Les pages sont ouvertes par un navigateur Chromium (SeleniumBase en mode « undetected », avec un affichage virtuel Xvfb) afin de passer la protection anti-robot du site et d'attendre le rendu JavaScript.

Le dossier du module dans ce dépôt s'appelle `example/` (nom hérité du gabarit officiel) ; cela n'a aucun effet sur son fonctionnement.

### Fonctionnalités

- **Classement** lu dans l'onglet « standings » de la page d'équipe (toutes les divisions affichées, avec le nom de la division pour chaque ligne).
- **Statistiques des joueurs** lues dans l'onglet « playerstats ».
- **Dernier match** : dernier match de l'équipe trouvé dans l'horaire filtré sur les « 30 derniers jours ».
- **Prochain match** : premier match de l'équipe trouvé dans l'horaire filtré sur les « 30 prochains jours ».
- Plusieurs équipes, ou plusieurs joueurs suivis, dans une même instance.
- Un appareil MQTT par équipe (ou par joueur) qui regroupe ses capteurs.
- Horodatage `updated` (heure de l'Est) dans les attributs de chaque capteur.

### Installation

Prérequis : un **broker MQTT** (par exemple le module complémentaire officiel **Mosquitto broker**) et l'**intégration MQTT** configurée dans Home Assistant.

1. Dans Home Assistant : **Paramètres → Modules complémentaires → Boutique des modules complémentaires → ⋮ (en haut à droite) → Dépôts**.
2. Ajoutez l'adresse du dépôt : `https://github.com/Frazou1/slqne_stats`, puis fermez la fenêtre.
3. Rechargez la boutique au besoin, ouvrez **SLQNE Hockey Stats** et cliquez sur **Installer**. L'image (Alpine, Chromium, Xvfb) est construite sur votre appareil : la première installation peut prendre plusieurs minutes.
4. Dans l'onglet **Configuration**, remplacez les équipes, les joueurs et les paramètres MQTT par les vôtres (voir ci-dessous) et enregistrez.
5. Dans l'onglet **Info**, cliquez sur **Démarrer**, puis suivez l'onglet **Journal**.

Architectures prises en charge : `amd64`, `aarch64`.

### Configuration

| Option | Type | Défaut | Rôle |
|---|---|---|---|
| `entity_prefix` | texte (facultatif) | `slqne` | Préfixe des identifiants uniques et des sujets MQTT. |
| `teams` | liste (obligatoire) | — | Équipes à lire. Au moins une équipe est nécessaire, sinon le module s'arrête. |
| `teams[].name` | texte | — | Nom de l'équipe. Il sert à nommer les capteurs **et** à reconnaître l'équipe dans l'horaire : il doit être contenu dans le nom de l'équipe affiché sur Spordle (comparaison sans accents, sans espaces ni ponctuation, sans tenir compte de la casse). |
| `teams[].spordle_url` | texte | — | Adresse de la page de l'équipe sur Spordle, de la forme `https://page.spordle.com/fr/<ligue>/teams/<numéro>`. Les paramètres après `?` sont retirés et remplacés par `?tab=standings`, `?tab=playerstats` ou `?tab=schedule`. **Nécessaire en pratique.** |
| `teams[].league_id`, `teams[].schedule_id` | texte (facultatif) | — | Acceptés par la configuration et affichés dans le journal au démarrage, mais **pas utilisés** par le script actuel. |
| `players` | liste | — | Joueurs suivis (voir le mode de fonctionnement ci-dessous). Mettre `[]` pour suivre seulement les équipes. |
| `players[].player_name` | texte | — | Nom du joueur, utilisé seulement pour nommer ses capteurs. |
| `players[].team_name` | texte | — | Équipe du joueur : doit correspondre au `name` d'une équipe de `teams` (l'un contenu dans l'autre, même comparaison souple). |
| `players[].spordle_url`, `league_id`, `schedule_id` | texte (facultatif) | — | Acceptés par la configuration, mais **pas utilisés** (l'adresse vient de l'équipe). |
| `update_interval` | entier, 30 à 86 400 | `7200` | Délai entre deux lectures, en **secondes**. |
| `mqtt_host` | texte | `core-mosquitto` | Adresse du broker MQTT. |
| `mqtt_port` | entier, 1 à 65 535 | `1883` | Port du broker MQTT. |
| `mqtt_username` | texte | — | Utilisateur MQTT (envoyé seulement s'il n'est pas vide). |
| `mqtt_password` | texte | — | Mot de passe MQTT. |
| `discovery_prefix` | texte | `homeassistant` | Préfixe MQTT Discovery (celui de l'intégration MQTT). |

**Mode de fonctionnement**

- **Si `players` est vide** : chaque équipe de `teams` est lue et publie ses capteurs.
- **Si `players` contient au moins un joueur** : seuls les joueurs sont traités. Pour chacun, le module lit l'équipe correspondante et publie les capteurs **au nom du joueur**. Une équipe qui n'est associée à aucun joueur n'est alors **pas** lue.

> Les valeurs proposées par défaut dans l'onglet Configuration (équipes, joueurs, identifiants MQTT `monuser` / `monpassword`) sont des exemples propres à une installation : remplacez-les toutes.

Exemple (valeurs fictives) — suivi d'une équipe :

```yaml
entity_prefix: slqne
teams:
  - name: "Les Castors"
    spordle_url: "https://page.spordle.com/fr/ma-ligue/teams/123456"
players: []
update_interval: 7200
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: mqtt_ha
mqtt_password: "votre_mot_de_passe"
discovery_prefix: homeassistant
```

Exemple — suivi d'un joueur :

```yaml
teams:
  - name: "Les Castors"
    spordle_url: "https://page.spordle.com/fr/ma-ligue/teams/123456"
players:
  - player_name: "Alex Tremblay"
    team_name: "Les Castors"
```

### Entités créées

Pour chaque équipe (ou chaque joueur, selon le mode), le module publie jusqu'à quatre capteurs, regroupés sous l'appareil **`SLQNE <slug>`**, où `<slug>` est le nom de l'équipe (ou du joueur) en minuscules, chaque suite de caractères autres que `a-z` et `0-9` étant remplacée par `_` (ex. `Les Castors` → `les_castors`).

| Nom du capteur | `unique_id` | État | Attributs |
|---|---|---|---|
| `SLQNE – Classement` | `<prefix>_<slug>_classement` | `<n> équipes` | `standings` (une ligne par équipe : colonnes du site + `division`), `updated` |
| `SLQNE – Stats Joueurs` | `<prefix>_<slug>_stats_joueurs` | `<n> joueurs` | `players` (colonnes du tableau du site), `updated` |
| `SLQNE – Dernier Match` | `<prefix>_<slug>_dernier_match` | `<pointage domicile>-<pointage visiteur>` | `match`, `updated` |
| `SLQNE – Prochain Match` | `<prefix>_<slug>_prochain_match` | `<visiteur> vs <domicile>` | `match`, `updated` |

Les capteurs « Dernier match » et « Prochain match » ne sont publiés que si au moins un match de l'équipe est trouvé dans la période correspondante. L'attribut `match` contient : `date`, `home`, `visitor`, `arena`, `score_home`, `score_visitor` et `final` (vrai si le match est terminé).

Sujets MQTT : `<discovery_prefix>/sensor/<unique_id>/config`, `.../state` et `.../attributes` (messages retenus).

L'identifiant d'entité (`sensor.…`) est généré par Home Assistant à partir du nom de l'appareil et du nom du capteur, par exemple `sensor.slqne_les_castors_slqne_classement`. Vérifiez-le dans **Paramètres → Appareils et services → Appareils** (recherche « SLQNE ») ; vous pouvez le renommer.

### Exemples d'utilisation

Carte Markdown du prochain match (adaptez l'identifiant d'entité) :

```yaml
type: markdown
content: >
  {% set m = state_attr('sensor.slqne_les_castors_slqne_prochain_match', 'match') %}
  {% if m %}
  **Prochain match :** {{ m.date }}<br>
  {{ m.visitor }} vs {{ m.home }}<br>
  {{ m.arena }}
  {% else %}
  Aucun match dans les 30 prochains jours.
  {% endif %}
```

Carte du classement :

```yaml
type: markdown
content: >
  | # | Équipe | PTS |
  |---|---|---|
  {% for r in state_attr('sensor.slqne_les_castors_slqne_classement', 'standings') or [] -%}
  | {{ r['#'] }} | {{ r['Équipe'] }} | {{ r['PTS'] }} |
  {% endfor %}
```

Les noms de colonnes (`#`, `Équipe`, `PTS`, etc.) sont ceux du site Spordle ; consultez l'attribut `standings` dans **Outils de développement → États** pour voir ceux de votre ligue.

### Rythme de mise à jour

Une lecture complète au démarrage, puis une nouvelle lecture toutes les `update_interval` secondes (7 200 s = 2 h par défaut). Chaque lecture ouvre plusieurs pages par équipe (classement, statistiques, horaire passé, horaire à venir) : un cycle peut prendre quelques minutes.

Le module ne conserve aucun fichier dans `/data` (hors la configuration) ; les valeurs restent visibles entre les cycles grâce aux messages MQTT retenus.

### Dépannage

Consultez l'onglet **Journal** du module.

| Message ou symptôme | Cause probable et solution |
|---|---|
| `[ERREUR] Aucune équipe configurée.` | La liste `teams` est vide : ajoutez au moins une équipe. |
| Le module s'arrête juste après `[INFO] Exécution du script Python SLQNE…`, avec une erreur de connexion | Connexion MQTT impossible (mauvais hôte, port ou identifiants) : la boucle s'arrête à la première erreur non traitée. Corrigez les paramètres MQTT puis redémarrez. |
| `[WARN] Aucune URL d'équipe trouvée dans la config pour <équipe>.` | Le `team_name` d'un joueur ne correspond à aucun `name` de `teams`. |
| `[ERREUR] Échec du chargement de <url>` ou `[WARN] Aucune table trouvée` | Page non chargée ou bloquée, ou `spordle_url` absente ou incorrecte (une équipe définie seulement par `league_id` / `schedule_id` ne fonctionne pas). |
| `[DEBUG] Étape filtre non appliquée ou inutilisée` | Le filtre « 30 derniers / prochains jours » n'a pas pu être choisi : seul l'horaire affiché par défaut est lu. |
| Pas de capteur « Dernier match » ou « Prochain match » | Aucun match dans la période, ou le `name` de l'équipe n'est pas contenu dans le nom affiché par Spordle. |
| Aucune entité dans Home Assistant | Intégration MQTT absente, `discovery_prefix` différent de celui de l'intégration, ou erreur MQTT dans le journal. |

### Limites connues

- Le module lit le HTML du site : une refonte de Spordle peut le casser sans avertissement.
- Les accents sont **retirés** (pas convertis) dans le `<slug>` d'une équipe : `Équipe A` donne `quipe_a`. Préférez un `name` sans accents.
- Le dernier match est le dernier trouvé dans l'ordre de la page sur 30 jours ; il peut s'agir d'un match pas encore joué (pointage vide).
- Chaque joueur suivi relit toutes les pages de son équipe, même si deux joueurs sont dans la même équipe.

### Revenir à une version précédente

Aucune version n'est étiquetée (tag) dans ce dépôt pour l'instant. Si l'option « Sauvegarder avant la mise à jour » était cochée, restaurez la sauvegarde partielle du module dans **Paramètres → Système → Sauvegardes**.

### Licence

Distribué sous la licence **Apache 2.0** : voir le fichier [LICENSE](https://github.com/Frazou1/slqne_stats/blob/main/LICENSE).

---

## English

### Description

**SLQNE Hockey Stats** (`slqne_hockey_stats`) is a Home Assistant add-on that reads the public page of one or more hockey teams on the **Spordle** platform (`page.spordle.com`) and publishes the standings, player statistics, last game and next game to Home Assistant over **MQTT** (MQTT Discovery).

Pages are opened by a Chromium browser (SeleniumBase in "undetected" mode, with an Xvfb virtual display) to get past the site's anti-bot protection and wait for the JavaScript rendering.

The add-on folder in this repository is named `example/` (inherited from the official template); this has no effect on how it works.

### Features

- **Standings** read from the team page's "standings" tab (every division shown, with the division name on each row).
- **Player statistics** read from the "playerstats" tab.
- **Last game**: the team's last game found in the schedule filtered on the "30 derniers jours" (last 30 days).
- **Next game**: the team's first game found in the schedule filtered on the "30 prochains jours" (next 30 days).
- Several teams, or several tracked players, in a single instance.
- One MQTT device per team (or per player) grouping its sensors.
- `updated` timestamp (Eastern time) in every sensor's attributes.

### Installation

Requirements: an **MQTT broker** (for example the official **Mosquitto broker** add-on) and the **MQTT integration** set up in Home Assistant.

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ (top right) → Repositories**.
2. Add the repository URL `https://github.com/Frazou1/slqne_stats` and close the dialog.
3. Reload the store if needed, open **SLQNE Hockey Stats** and click **Install**. The image (Alpine, Chromium, Xvfb) is built on your device, so the first install can take several minutes.
4. In the **Configuration** tab, replace the teams, players and MQTT settings with your own (see below) and save.
5. In the **Info** tab, click **Start**, then watch the **Log** tab.

Supported architectures: `amd64`, `aarch64`.

### Configuration

| Option | Type | Default | Purpose |
|---|---|---|---|
| `entity_prefix` | string (optional) | `slqne` | Prefix of the unique IDs and MQTT topics. |
| `teams` | list (required) | — | Teams to read. At least one team is needed, otherwise the add-on stops. |
| `teams[].name` | string | — | Team name. Used to name the sensors **and** to recognise the team in the schedule: it must be contained in the team name shown on Spordle (compared without accents, spaces or punctuation, case-insensitive). |
| `teams[].spordle_url` | string | — | URL of the team page on Spordle, like `https://page.spordle.com/fr/<league>/teams/<number>`. Anything after `?` is removed and replaced by `?tab=standings`, `?tab=playerstats` or `?tab=schedule`. **Required in practice.** |
| `teams[].league_id`, `teams[].schedule_id` | string (optional) | — | Accepted by the configuration and printed in the log at startup, but **not used** by the current script. |
| `players` | list | — | Tracked players (see the operating mode below). Use `[]` to follow teams only. |
| `players[].player_name` | string | — | Player name, only used to name the player's sensors. |
| `players[].team_name` | string | — | Player's team: must match the `name` of a team in `teams` (one contained in the other, same loose comparison). |
| `players[].spordle_url`, `league_id`, `schedule_id` | string (optional) | — | Accepted by the configuration but **not used** (the URL comes from the team). |
| `update_interval` | integer, 30 to 86,400 | `7200` | Delay between two reads, in **seconds**. |
| `mqtt_host` | string | `core-mosquitto` | MQTT broker address. |
| `mqtt_port` | integer, 1 to 65,535 | `1883` | MQTT broker port. |
| `mqtt_username` | string | — | MQTT user (only sent when not empty). |
| `mqtt_password` | string | — | MQTT password. |
| `discovery_prefix` | string | `homeassistant` | MQTT Discovery prefix (the one used by the MQTT integration). |

**Operating mode**

- **When `players` is empty**: every team in `teams` is read and publishes its sensors.
- **When `players` holds at least one player**: only players are processed. For each one, the add-on reads the matching team and publishes the sensors **under the player's name**. A team not linked to any player is then **not** read.

> The values pre-filled in the Configuration tab (teams, players, MQTT login `monuser` / `monpassword`) are examples from one specific setup: replace all of them.

Example (made-up values) — following a team:

```yaml
entity_prefix: slqne
teams:
  - name: "The Beavers"
    spordle_url: "https://page.spordle.com/fr/my-league/teams/123456"
players: []
update_interval: 7200
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: mqtt_ha
mqtt_password: "your_password"
discovery_prefix: homeassistant
```

Example — following a player:

```yaml
teams:
  - name: "The Beavers"
    spordle_url: "https://page.spordle.com/fr/my-league/teams/123456"
players:
  - player_name: "Alex Smith"
    team_name: "The Beavers"
```

### Created entities

For each team (or each player, depending on the mode), the add-on publishes up to four sensors, grouped under the device **`SLQNE <slug>`**, where `<slug>` is the team (or player) name in lower case, with every run of characters other than `a-z` and `0-9` replaced by `_` (e.g. `The Beavers` → `the_beavers`).

| Sensor name | `unique_id` | State | Attributes |
|---|---|---|---|
| `SLQNE – Classement` (standings) | `<prefix>_<slug>_classement` | `<n> équipes` | `standings` (one row per team: site columns + `division`), `updated` |
| `SLQNE – Stats Joueurs` (player stats) | `<prefix>_<slug>_stats_joueurs` | `<n> joueurs` | `players` (columns of the site table), `updated` |
| `SLQNE – Dernier Match` (last game) | `<prefix>_<slug>_dernier_match` | `<home score>-<visitor score>` | `match`, `updated` |
| `SLQNE – Prochain Match` (next game) | `<prefix>_<slug>_prochain_match` | `<visitor> vs <home>` | `match`, `updated` |

The "last game" and "next game" sensors are only published when at least one game of the team is found in the matching period. The `match` attribute holds: `date`, `home`, `visitor`, `arena`, `score_home`, `score_visitor` and `final` (true when the game is over).

MQTT topics: `<discovery_prefix>/sensor/<unique_id>/config`, `.../state` and `.../attributes` (retained).

The entity ID (`sensor.…`) is generated by Home Assistant from the device name and the sensor name, for example `sensor.slqne_the_beavers_slqne_classement`. Check it under **Settings → Devices & services → Devices** (search "SLQNE"); you can rename it.

### Usage examples

Markdown card for the next game (adjust the entity ID):

```yaml
type: markdown
content: >
  {% set m = state_attr('sensor.slqne_the_beavers_slqne_prochain_match', 'match') %}
  {% if m %}
  **Next game:** {{ m.date }}<br>
  {{ m.visitor }} vs {{ m.home }}<br>
  {{ m.arena }}
  {% else %}
  No game in the next 30 days.
  {% endif %}
```

Standings card:

```yaml
type: markdown
content: >
  | # | Team | PTS |
  |---|---|---|
  {% for r in state_attr('sensor.slqne_the_beavers_slqne_classement', 'standings') or [] -%}
  | {{ r['#'] }} | {{ r['Équipe'] }} | {{ r['PTS'] }} |
  {% endfor %}
```

Column names (`#`, `Équipe`, `PTS`, etc.) are those of the Spordle site; look at the `standings` attribute in **Developer tools → States** to see your league's columns.

### Update rhythm

One full read at startup, then a new read every `update_interval` seconds (7,200 s = 2 h by default). Each read opens several pages per team (standings, statistics, past schedule, upcoming schedule), so one cycle can take a few minutes.

The add-on keeps no file in `/data` (apart from its configuration); values stay visible between cycles thanks to retained MQTT messages.

### Troubleshooting

Check the add-on's **Log** tab.

| Message or symptom | Likely cause and fix |
|---|---|
| `[ERREUR] Aucune équipe configurée.` | The `teams` list is empty: add at least one team. |
| The add-on stops right after `[INFO] Exécution du script Python SLQNE…` with a connection error | MQTT connection failed (wrong host, port or login): the loop stops at the first unhandled error. Fix the MQTT settings and restart. |
| `[WARN] Aucune URL d'équipe trouvée dans la config pour <team>.` | A player's `team_name` matches no `name` in `teams`. |
| `[ERREUR] Échec du chargement de <url>` or `[WARN] Aucune table trouvée` | Page not loaded or blocked, or `spordle_url` missing or wrong (a team defined only by `league_id` / `schedule_id` does not work). |
| `[DEBUG] Étape filtre non appliquée ou inutilisée` | The "30 derniers / prochains jours" filter could not be selected: only the default schedule view is read. |
| No "last game" or "next game" sensor | No game in the period, or the team `name` is not contained in the name shown by Spordle. |
| No entity in Home Assistant | MQTT integration missing, `discovery_prefix` different from the integration's, or an MQTT error in the log. |

### Known limitations

- The add-on parses the site's HTML: a Spordle redesign can break it without warning.
- Accents are **dropped** (not converted) in a team's `<slug>`: `Équipe A` gives `quipe_a`. Prefer a `name` without accents.
- The last game is the last one found in page order over 30 days; it may be a game not played yet (empty score).
- Each tracked player re-reads all of the team's pages, even when two players are on the same team.

### Rolling back to a previous version

No version is tagged in this repository yet. If "Back up before updating" was checked, restore the add-on's partial backup under **Settings → System → Backups**.

### License

Released under the **Apache 2.0** license: see the [LICENSE](https://github.com/Frazou1/slqne_stats/blob/main/LICENSE) file.
