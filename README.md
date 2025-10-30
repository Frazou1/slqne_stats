# SLQNE Stats

**RSEQ Team Calendar** est un add-on Home Assistant qui récupère le calendrier d’une équipe sur le site du [RSEQ – Réseau du sport étudiant du Québec](https://diffusion.rseq.ca/) (via Selenium headless).  
L’add-on extrait les prochains matchs depuis la section *Calendrier de l’équipe* et les publie en tant que capteurs MQTT, disponibles automatiquement dans Home Assistant via la découverte MQTT (*MQTT Discovery*).

---

## Comment ça fonctionne

1. **Navigateur headless (Selenium):**  
   L’add-on lance Chromium en mode headless pour ouvrir la page d’une équipe RSEQ.
2. **Parsing HTML (BeautifulSoup):**  
   Une fois le tableau du calendrier chargé, le script lit les informations (date, heure, équipes, résultat, lieu).
3. **Publication de capteurs MQTT:**  
   Grâce à la découverte MQTT, l’add-on publie :  
   - `sensor.rseq_team_status` (état de l’add-on, ex. `success` ou `error`)  
   - `sensor.rseq_team_next_game` (prochain match formaté lisible)  
     - avec les attributs `next_game` (objet JSON) et `upcoming` (jusqu’à 5 prochains matchs)

En option, l’add-on peut aussi créer des événements dans le calendrier Home Assistant si tu fournis un `ha_token` et un `ha_calendar_entity`.

---

## Installation

1. **Ajoute ce dépôt** dans Home Assistant comme dépôt d’add-ons :  
   - Paramètres → Modules complémentaires → Boutique → menu (⋮) → Dépôts → entre l’URL du dépôt.  
   - Ou clique sur le bouton ci-dessous :

   [![Open your Home Assistant instance and show the add add-on repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FFrazou1%2Frseq_calendar)
2. **Installe** l’add-on **RSEQ Team Calendar** depuis la liste de tes add-ons locaux.
3. **Configure** l’add-on (URL d’équipe RSEQ, intervalle de mise à jour, MQTT, options HA).
4. **Démarre** l’add-on et consulte les logs. Tu devrais voir les matchs à venir détectés et publiés dans MQTT.

---

## Options de configuration

| Clé                | Description                                                  | Valeur par défaut                         |
|---------------------|--------------------------------------------------------------|-------------------------------------------|
| `team_url`          | URL de la page d’équipe RSEQ (onglet Calendrier)             | `""`                                      |
| `update_interval`   | Intervalle en secondes pour rafraîchir les données           | `3600` (1h)                               |
| `mqtt_host`         | Hôte du broker MQTT                                         | `"core-mosquitto"`                        |
| `mqtt_port`         | Port du broker MQTT                                         | `1883`                                    |
| `mqtt_username`     | Utilisateur MQTT                                            | `""`                                      |
| `mqtt_password`     | Mot de passe MQTT                                           | `""`                                      |
| `discovery_prefix`  | Préfixe MQTT Discovery                                      | `"homeassistant"`                         |
| `ha_url`            | URL de ton instance Home Assistant (si création d’événements)| `"http://homeassistant.local:8123"`       |
| `ha_token`          | Jeton d’accès longue durée (si création d’événements)        | `""`                                      |
| `ha_calendar_entity`| Entité calendrier HA cible (ex. `calendar.rseq_equipes`)     | `""`                                      |

---

## Architectures supportées

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Supports armhf Architecture][armhf-shield]
![Supports armv7 Architecture][armv7-shield]
![Supports i386 Architecture][i386-shield]

---

## Communauté & Support

- [Home Assistant Community](https://community.home-assistant.io/) – Pour questions, astuces de config ou partages.
- [RSEQ Diffusion](https://diffusion.rseq.ca/) – Site officiel du RSEQ avec les calendriers et résultats.

---

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
