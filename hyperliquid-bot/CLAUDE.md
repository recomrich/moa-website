# CLAUDE.md — Hyperliquid Trading Bot

## Contexte utilisateur

- **User:** Remy, trader débutant, parle français
- **Capital actuel:** ~$118 USDC (a perdu de $171 → $118 à cause de bugs)
- **Wallet:** `0xd50659A160Ee1e21322c5def2bce96f28d6D146A`
- **Objectif:** bot qui analyse les cycles temporels des cryptos (prix qui oscillent prévisiblement) pour trader avec levier

## État actuel du bot

- **Mode:** LIVE (trade avec vrai argent)
- **Positions ouvertes sur Hyperliquid:** BTC short 20x, ETH short 20x, XRP short 20x, IO short (les positions étaient là avant qu'on répare les bugs)
- **Intervalle:** 30 secondes entre cycles
- **Dashboard:** http://localhost:8080

## Stratégies actives

- `trend_following` (15m)
- `mean_reversion` (15m)
- `breakout` (15m)
- `momentum` (15m) — nouveau
- `cycle_trader` (1d) — nouveau, analyse temporelle des cycles haussiers/baissiers

Désactivées: scalping, grid_trading, swing_range (causaient des pertes)

## Bugs qu'on a fixé récemment (IMPORTANT à ne PAS réintroduire)

### 1. SL/TP ne se plaçaient jamais (`core/order_manager.py`)

**Bug:** `"triggerPx": str(round(trigger_price, 2))` — le SDK Hyperliquid appelle `float_to_wire()` qui fait `"{:.8f}".format(x)`, crash sur une string.

**Fix:** passer `trigger_price` en float direct + ajout méthode `_round_price()` qui respecte les règles de précision Hyperliquid (max 5 sig figs, max `6 - szDecimals` décimales).

### 2. PnL gonflé 20x (`core/position_manager.py`)

**Bug:** `unrealized_pnl = (price_change) * size * leverage` — le levier était déjà incorporé dans la size, donc on multipliait 2 fois. Résultat: le bot croyait être en drawdown 10% alors que les positions étaient en **gain**.

**Fix:** retiré `* leverage` de:
- `update_prices()` (ligne ~170)
- `close_position()` (ligne ~124)
- Emergency exit (ligne ~187)

Formule correcte: `pnl = price_change * size` (en dollars, sans multiplier par le levier).

### 3. Auto-protection SL/TP pour positions existantes (`main.py`)

`_sync_and_protect_positions()` tourne à chaque tick en mode live. Si une position sur Hyperliquid n'a pas de SL/TP, le bot en place automatiquement (SL 2%, TP 3%).

### 4. Trailing stop (`core/position_manager.py`)

SL suit le pic du prix à `trailing_stop_pct`% (config: 1.5%). S'active après 0.5% de profit. Aussi géré pour les shorts (suit le creux).

### 5. Cooldown depuis la fermeture

`close_position()` met à jour `_last_trade_time` pour que le cooldown parte de la CLÔTURE, pas de l'ouverture.

## Config actuelle (`config.yaml`)

```yaml
risk:
  max_risk_per_trade_pct: 5.0   # user a monté de 1.0 à 5.0
  max_drawdown_pct: 10.0
  max_open_positions: 50        # quasi illimité
  max_positions_per_symbol: 5   # user a monté de 1 à 5
  cooldown_minutes: 30
  max_leverage: 10
  min_reward_risk_ratio: 1.5
  trailing_stop_pct: 1.5
```

## Problème actuel (non résolu)

**Toutes les stratégies restent en HOLD**, aucun trade ne se déclenche depuis qu'on a relancé. Raisons identifiées:

1. **cycle_trader:** `min_reliability: 40` (dans config) est trop strict. Les cryptos actuelles sont à 28-36% de fiabilité. Il faudrait descendre à **25**.

2. **momentum:** `momentum_pct: 2.0` (2% en 1h30) trop strict. Mettre à **1.5**.

3. **cycle_trader** attend aussi le bas du cycle baissier pour acheter. Actuellement toutes les cryptos sont en UP for 1 day → logique HOLD.

## Workflow synchronisation

Le bot tourne sur Windows: `C:\Users\rsser\hyperliquid-bot\`
Le repo git est séparé (branche `claude/hyperliquid-trading-bot-qE4UW` sur `recomrich/moa-website`).

Un script `update.ps1` télécharge les fichiers depuis git. **Le `config.yaml` est exclu** du sync pour préserver les réglages utilisateur.

Depuis qu'on bosse avec Claude Code local, plus besoin de git — modifier les fichiers directement.

## Règles importantes

- **Ne jamais** remettre `* leverage` dans le calcul du PnL (voir bug #2)
- **Ne jamais** wrapper `triggerPx` dans `str()` (voir bug #1)
- **Ne jamais** activer `scalping`, `grid_trading`, `swing_range` (causaient des pertes)
- Le user est frustré par les changements répétés, **éviter de modifier plein de choses d'un coup**
- Vérifier avant d'agir, pas de refactoring non-demandé

## Commandes utiles

```powershell
# Lancer le bot
cd C:\Users\rsser\hyperliquid-bot
.\venv\Scripts\Activate.ps1
python main.py

# Dashboard
# http://localhost:8080
```

## Stack technique

- Python 3.x avec venv
- `hyperliquid-python-sdk` pour l'API
- `loguru` pour les logs
- `fastapi` + `uvicorn` pour le dashboard
- `pandas` pour les indicateurs
- `pyyaml` pour la config
