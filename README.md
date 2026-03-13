# 🐐 Goat Discord Bot

Bot Discord multi-instance avec IA (LLM), chat vocal (TTS) et support MCP.

## Fonctionnalités

### 🤖 Chat IA
- **Réponse Intelligente** : Répond aux mentions et aux réponses (replies).
- **Vision & Images** : Analyse nativement les images jointes (vision LLM).
- **Mémoire Contextuelle** : Historique des conversations via SQLite.
- **Profils Utilisateurs** : Mémorisation des préférences et faits concernant chaque utilisateur.

### 🎙️ Chat Vocal
- **Interaction Vocale** : Rejoindre/quitter les salons vocaux via slash commands.
- **Synthèse Vocale (TTS)** : Réponses vocales naturelles générées via FishAudio.
- **Play TTS** : Commande `/tts` pour générer un message audio personnalisé.

### 🛠️ Intégration MCP (Outils)
- **Exa Web Search** : Recherche web en temps réel pour des réponses à jour.
- **Giphy** : Recherche et envoi de GIFs de manière autonome.

### ⚡ Commandes Slash
| Commande | Description |
|----------|-------------|
| `/clear_memory` | Effacer l'historique du salon actuel |
| `/analyze_chat` | Analyse intelligente du chat par l'IA |
| `/analyze_image` | Analyser une image avec un prompt personnalisé |
| `/join` | Faire rejoindre le salon vocal au bot |
| `/leave` | Faire quitter le salon vocal au bot |
| `/tts` | Générer et jouer une réponse audio |

### 🔔 Extra
- **Réponses Automatiques** : Répond automatiquement à des mots-clés configurés.
- **Stalk (Surveillance)** : Notifie quand un utilisateur spécifique se connecte.

## Installation

1. Installer les dépendances :
```bash
pip install -r requirements.txt
```

2. Configurer les variables d'environnement (`.env`) :
```env
# Clés API (selon vos providers)
KILOCODE_API_KEY=votre_cle_api
OPENROUTER_API_KEY=votre_cle_api
FISHAUDIO_API_KEY=votre_cle_api
```

3. Lancer le bot :
```bash
python main.py
```

## Multi-bot

Chaque instance est isolée dans le dossier `bots/<nom_bot>/`. Vous pouvez configurer pour chaque bot :
- Son propre **Token** Discord.
- Son propre **Modèle** (Gemini, Llama, etc.).
- Son propre **Prompt** de personnalité (`prompt.txt`).
- Des **Plugins** spécifiques (Cogs additionnels).

## Configuration (`config.json`)

| Option | Description |
|--------|-------------|
| `llm_provider` | Provider LLM (ex: `openrouter`) |
| `model` | Nom du modèle à utiliser |
| `api_key_env` | Nom de la variable d'env contenant la clé API |
| `base_url` | Endpoint API personnalisé (optionnel) |
| `mcp_servers` | Liste des serveurs MCP activés |
| `tts_provider` | Provider vocal (ex: `fishaudio`) |
| `keyword_responses` | Mapping de mots-clés -> réponses |
| `stalk_id` | ID Discord de l'utilisateur à surveiller |
| `general_channel_id`| Salon pour les notifications automatiques |

