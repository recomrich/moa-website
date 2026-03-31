# Hyperliquid Trading Bot

Bot de trading automatise pour la plateforme **Hyperliquid** (DEX de trading perpetuel), avec support spot et futures/perps, dashboard web temps reel, et architecture multi-strategies modulaire.

> **Avertissement** : Ce bot est un outil de trading automatise. Le trading de cryptomonnaies comporte des risques significatifs de perte en capital. Toujours tester en mode paper avant de passer en mode live. Ne jamais risquer plus que ce que l'on peut se permettre de perdre.

## Fonctionnalites

- **Multi-strategies** : Trend Following, Mean Reversion, Breakout, Scalping
- **Spot + Perps** : Support du trading spot et des futures perpetuels avec levier configurable
- **Gestion du risque** : Stop-loss obligatoire, max drawdown, taille de position dynamique (ATR)
- **Dashboard web temps reel** : Interface dark theme avec graphiques, positions, trades, strategies
- **Paper trading** : Mode simulation complet avant passage en reel
- **Base de donnees** : Historique des trades et snapshots de performance (SQLite)
- **Backtesting** : Moteur de backtesting avec rapports de performance (Sharpe, drawdown)
- **Notifications Telegram** : Alertes optionnelles sur evenements critiques

## Installation

### Prerequis

- Python 3.11+
- Un wallet Hyperliquid avec cle privee

### Etapes

```bash
# 1. Cloner le depot
git clone <repo-url>
cd hyperliquid-bot

# 2. Creer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# 3. Installer les dependances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Editer .env avec votre cle privee et adresse wallet
```

## Configuration

### Variables d'environnement (`.env`)

```env
HL_PRIVATE_KEY=votre_cle_privee
HL_ACCOUNT_ADDRESS=votre_adresse_wallet
HL_TESTNET=true
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8080
```

### Configuration des strategies (`config.yaml`)

Le fichier `config.yaml` controle :

- **`bot.mode`** : `"paper"` (simulation) ou `"live"` (reel)
- **`bot.update_interval`** : Frequence d'analyse en secondes
- **`risk`** : Parametres de gestion du risque (max drawdown, risk par trade, etc.)
- **`trading_pairs`** : Paires a trader en spot et perps, avec strategies assignees
- **`strategies`** : Activation et parametres de chaque strategie

## Utilisation

### Lancer le bot

```bash
python main.py
```

Le bot demarre en mode paper par defaut. Le dashboard est accessible sur `http://localhost:8080`.

### Strategies disponibles

| Strategie | Description | Timeframe |
|---|---|---|
| **Trend Following** | EMA 20/50/200 + MACD crossover | 1h / 4h |
| **Mean Reversion** | RSI + Bollinger Bands | 15m / 1h |
| **Breakout** | Cassure de niveaux + volume confirmation | 1h |
| **Scalping** | EMA 5/13 + RSI filter | 5m |

### Dashboard

Le dashboard web affiche en temps reel :

- Valeur du portefeuille et PnL journalier
- Courbe d'equity
- Positions ouvertes avec SL/TP
- Historique des trades
- Statut de chaque strategie (activation/desactivation via l'interface)

## Architecture

```
hyperliquid-bot/
  core/           # Client API, ordres, positions, risque, portefeuille
  strategies/     # Strategies de trading modulaires
  indicators/     # Indicateurs techniques (EMA, RSI, MACD, BB, ATR)
  data/           # Feed temps reel, historique, cache
  database/       # Modeles SQLAlchemy et operations CRUD
  dashboard/      # Serveur FastAPI + frontend HTML/CSS/JS
  backtesting/    # Moteur de backtest et rapports
  notifications/  # Alertes Telegram
  logs/           # Fichiers de logs
```

## Gestion du risque

- **Risk par trade** : Configurable (defaut 1% du capital)
- **Max drawdown** : Arret automatique si perte depasse le seuil
- **Max positions simultanees** : Limite configurable
- **Stop-loss** : Toujours obligatoire, calcule dynamiquement via ATR
- **Take-profit** : Ratio risk/reward minimum 2:1
- **Taille de position** : Ajustee a la volatilite (ATR-based)

## Mode Paper vs Live

Le mode est controle par `config.yaml` -> `bot.mode` :

- **Paper** : Simule les ordres, capital virtuel de 10 000$, aucune interaction reelle avec l'exchange
- **Live** : Execute les ordres sur Hyperliquid (testnet ou mainnet selon `HL_TESTNET`)

## Licence

Usage personnel uniquement. Pas de garantie de profit.
