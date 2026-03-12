# HyperBot — Bot de Trading Automatisé Hyperliquid

> ⚠️ **Avertissement** : Ce bot est un outil de trading automatisé. Le trading de cryptomonnaies comporte des risques significatifs de perte en capital. Toujours tester en mode **paper trading** avant de passer en mode live. Ne jamais risquer plus que ce que l'on peut se permettre de perdre.

## Description

HyperBot est un bot de trading algorithmique complet pour la plateforme [Hyperliquid](https://hyperliquid.xyz), un DEX de trading perpétuel on-chain. Il supporte le trading spot et les futures perpétuels (perps) avec plusieurs stratégies modulaires.

### Fonctionnalités

- **Multi-stratégies** : Trend Following, Mean Reversion, Breakout, Scalping
- **Multi-marchés** : Spot + Perps avec levier configurable
- **Gestion du risque** : Risk per trade, max drawdown, taille de position via ATR
- **Paper trading** : Simulation complète avant passage en live
- **Dashboard web** : Interface temps réel sur `http://localhost:8080`
- **Backtesting** : Testez vos stratégies sur des données historiques
- **Notifications** : Alertes Telegram optionnelles

## Installation

### Prérequis

- Python 3.11+
- pip

### Étapes

```bash
# 1. Cloner le repo
git clone <repo-url>
cd hyperliquid-bot

# 2. Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou : venv\Scripts\activate  # Windows

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés

# 5. Configurer les stratégies
# Éditer config.yaml selon vos besoins
```

## Configuration

### Fichier `.env`

```env
HYPERLIQUID_PRIVATE_KEY=votre_clé_privée_sans_0x
HYPERLIQUID_WALLET_ADDRESS=votre_adresse_wallet
HYPERLIQUID_NETWORK=mainnet  # ou testnet
DASHBOARD_PORT=8080
```

> 🔒 **Sécurité** : Ne jamais partager votre clé privée. Le fichier `.env` est exclu de git par `.gitignore`.

### Fichier `config.yaml`

Le fichier `config.yaml` contrôle tous les paramètres du bot :

| Section | Description |
|---------|-------------|
| `bot.mode` | `"paper"` pour simulation, `"live"` pour trading réel |
| `bot.update_interval` | Fréquence d'analyse en secondes |
| `risk` | Paramètres de gestion du risque |
| `trading_pairs` | Paires tradées et stratégies associées |
| `strategies` | Configuration de chaque stratégie |
| `paper_trading` | Capital virtuel et simulation de frais |

## Lancement

```bash
# Mode paper (simulation) — recommandé pour démarrer
python main.py

# Le dashboard est accessible sur http://localhost:8080

# Backtesting d'une stratégie
python -m backtesting.engine --strategy trend_following --symbol BTC --days 90
```

## Stratégies

### 1. Trend Following (`trend_following`)

Suivi de tendance basé sur les moyennes mobiles exponentielles et le MACD.

- **Signal BUY** : EMA20 > EMA50 > EMA200 + MACD > Signal line
- **Signal SELL** : EMA20 < EMA50 + MACD < Signal line
- **Timeframe** : 1h (configurable)

### 2. Mean Reversion (`mean_reversion`)

Retour à la moyenne basé sur RSI et Bollinger Bands.

- **Signal BUY** : RSI < 30 + prix sous Bollinger Band inférieure
- **Signal SELL** : RSI > 70 + prix au-dessus Bollinger Band supérieure
- **Timeframe** : 15m (configurable)

### 3. Breakout (`breakout`)

Cassure de niveaux clés avec confirmation du volume.

- **Signal BUY** : cassure au-dessus résistance + volume > moyenne × 1.5
- **Stop-loss** : ATR × 1.5 sous le point de cassure
- **Timeframe** : 1h (configurable)

### 4. Scalping (`scalping`)

Scalping rapide sur petits timeframes (désactivé par défaut).

- **Signal BUY** : EMA5 > EMA13 + RSI entre 45-65
- **TP** : 0.8%, **SL** : 0.3%
- **Timeframe** : 5m (configurable)

## Dashboard

Le dashboard web est accessible sur `http://localhost:8080` et affiche :

- **Solde et PnL** : Capital total, gain/perte du jour
- **Graphique d'équity** : Courbe de performance du portefeuille
- **Graphique de prix** : Prix en temps réel avec indicateurs
- **Positions ouvertes** : Tableau avec entrée, PnL, SL/TP
- **Historique des trades** : Dernières transactions
- **Statut des stratégies** : Win rate, signaux générés

Toutes les données sont mises à jour en temps réel via WebSocket.

## Structure du projet

```
hyperliquid-bot/
├── main.py                  # Point d'entrée
├── config.yaml              # Configuration
├── .env                     # Secrets (non commité)
├── core/                    # Logique métier principale
│   ├── client.py            # Connexion Hyperliquid
│   ├── order_manager.py     # Gestion des ordres
│   ├── position_manager.py  # Gestion des positions
│   ├── risk_manager.py      # Contrôle du risque
│   └── portfolio.py         # Suivi du portefeuille
├── strategies/              # Stratégies de trading
├── indicators/              # Indicateurs techniques
├── data/                    # Flux de données
├── database/                # Persistance SQLite
├── dashboard/               # Serveur web + frontend
├── backtesting/             # Backtesting engine
└── notifications/           # Alertes Telegram
```

## Gestion du risque

Le bot intègre plusieurs niveaux de protection :

1. **Risk per trade** : Maximum 1% du capital par trade (configurable)
2. **Stop-loss obligatoire** : Chaque position a un SL calculé via ATR
3. **Take-profit** : Ratio risk/reward minimum de 2:1
4. **Max drawdown** : Arrêt automatique si perte > 10% (configurable)
5. **Max positions** : Limite à 5 positions simultanées (configurable)

## Sécurité

- La clé privée est uniquement stockée dans `.env` (jamais dans le code)
- `.env` est exclu de git
- Toutes les réponses API sont validées avant utilisation
- Retry automatique avec backoff exponentiel sur les erreurs réseau
- Logs complets de toutes les erreurs sans exposer les secrets

## Avertissements

- **Toujours** commencer par le mode paper trading
- **Jamais** investir plus que ce que vous pouvez vous permettre de perdre
- Les performances passées ne garantissent pas les performances futures
- Ce bot est fourni à titre éducatif et expérimental

## Licence

MIT License — Utilisation à vos propres risques.
