# SLQNE Hockey Stats

**SLQNE Hockey Stats** est un add-on Home Assistant qui récupère automatiquement les **statistiques et classements** des équipes sur le site du [Spordle – Ligue de hockey mineur de la Capitale-Nationale (SLQNE)](https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/).  
L’add-on lit les sections *Classements* et *Statistiques* des pages d’équipes Spordle, et publie les données dans Home Assistant via MQTT Discovery.

---

## ⚙️ Fonctionnement

1. **Requête HTTP et parsing HTML (Requests + BeautifulSoup)**  
   L’add-on interroge la page Spordle d’une équipe et extrait les tableaux HTML de statistiques et de classement.

2. **Conversion structurée**  
   Les données sont nettoyées et converties en structures JSON pour être lisibles par les cartes Lovelace personnalisées (`rseq-standings-card`, `rseq-lastgame-card`, etc.), entièrement compatibles.

3. **Publication MQTT**  
   Grâce à *MQTT Discovery*, les capteurs apparaissent automatiquement dans Home Assistant, sans configuration manuelle.  
   Les entités publiées comprennent notamment :
   - `sensor.slqne_<equipe>_status` — état du scraping (succès/erreur)
   - `sensor.slqne_<equipe>_standings` — classement général
   - `sensor.slqne_<equipe>_players` — statistiques des joueurs
   - `sensor.slqne_<equipe>_goalies` — statistiques des gardiens

---

## 🚀 Installation

1. **Ajoute ce dépôt** dans Home Assistant :  
   Paramètres → Modules complémentaires → Boutique → menu (⋮) → **Dépôts** → entre l’URL du dépôt.  
   Ou clique sur le bouton ci-dessous :

   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FFrazou1%2Fslqne_hockey_stats)

2. **Installe** l’add-on **SLQNE Hockey Stats** depuis la liste des add-ons locaux.

3. **Configure** les équipes et les paramètres MQTT (voir plus bas).

4. **Démarre** l’add-on et vérifie les logs Home Assistant — les capteurs MQTT devraient être automatiquement créés.

---

## 🧩 Exemple de configuration

```yaml
entity_prefix: slqne
update_interval: 3600  # vérifie les données toutes les heures
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: tonuser
mqtt_password: tonmotdepasse
discovery_prefix: homeassistant

teams:
  - name: "joueur1 Hockey"
    team_url: "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/00000000-0000-0000-0000-000000000002?tab=standings&scheduleId=000002"
  - name: "joueur2 Hockey"
    team_url: "https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/schedule-stats-standings/00000000-0000-0000-0000-000000000001?tab=standings&scheduleId=000003"
```

---

## 🔧 Options disponibles

| Clé                | Description                                           | Valeur par défaut  |
|---------------------|-------------------------------------------------------|--------------------|
| `teams`             | Liste des équipes (nom + URL Spordle)                | `[]`               |
| `entity_prefix`     | Préfixe des entités MQTT publiées                    | `"slqne"`          |
| `update_interval`   | Intervalle de mise à jour en secondes                | `3600`             |
| `mqtt_host`         | Adresse du broker MQTT                               | `"core-mosquitto"` |
| `mqtt_port`         | Port du broker MQTT                                  | `1883`             |
| `mqtt_username`     | Nom d’utilisateur MQTT                               | `""`               |
| `mqtt_password`     | Mot de passe MQTT                                    | `""`               |
| `discovery_prefix`  | Préfixe MQTT Discovery                               | `"homeassistant"`  |

---

## 🧠 Capteurs publiés

Chaque équipe configurée publie plusieurs capteurs MQTT :

| Entité exemple | Description |
|----------------|--------------|
| `sensor.slqne_joueur1_hockey_status` | État de l’extraction (succès/erreur) |
| `sensor.slqne_joueur1_hockey_standings` | Classement complet (avec `standings[]`) |
| `sensor.slqne_joueur1_hockey_players` | Statistiques détaillées des joueurs |
| `sensor.slqne_joueur1_hockey_goalies` | Statistiques des gardiens |
| `sensor.slqne_joueur1_hockey_last_game` *(optionnel)* | Dernier match détecté, si disponible |

---

## 🧱 Intégration Lovelace

Compatible avec les mêmes cartes personnalisées utilisées pour RSEQ :

- `rseq-standings-card.js` — affichage dynamique des classements  
- `rseq-lastgame-card.js` — affichage du dernier match avec logos  
- `rseq-nextgame-card.js` *(facultatif pour autres ligues)*

💡 Tu peux réutiliser ces cartes simplement en changeant le `entity:` vers les entités `sensor.slqne_*`.

---

## 🧰 Architectures supportées

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Supports armhf Architecture][armhf-shield]
![Supports armv7 Architecture][armv7-shield]
![Supports i386 Architecture][i386-shield]

---

## 🧑‍💻 Communauté & Support

- [Home Assistant Community](https://community.home-assistant.io/) — pour questions, partages et exemples Lovelace.  
- [Spordle – Ligue de hockey mineur de la Capitale-Nationale](https://page.spordle.com/fr/ligue-hockey-mineur-capitale-nationale/) — source officielle des données.  

---

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg  
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg  
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg  
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg  
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
