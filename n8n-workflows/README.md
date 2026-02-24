# N8N — Automatisation Mission & Candidats

Système complet d'automatisation pour la gestion des missions d'intérim : confirmation, relances, scoring de risque et recherche de backup.

---

## Architecture — 6 Workflows

```
A  mission_created_or_updated   ← ATS / Google Sheets / Calendrier
B  inbound_reply_handler        ← SMS / WhatsApp / Email entrant
C  reminder_engine              ← CRON toutes les 30 min
D  backup_candidate_finder      ← Appelé par B, C, E
E  risk_scoring_ai              ← Appelé par C, D, F
F  mission_outcome_update       ← Recruiter (dashboard / API)
```

### Flux principal

```
ATS crée mission
      │
      ▼
[A] Upsert mission + candidat → SMS confirmation → Planifie rappels
                                                         │
                               ┌─────────────────────────┤
                               │ Candidat répond          │ Pas de réponse
                               ▼                          ▼
                         [B] Classifier          [C] Cron: J-2, J-1, H-2
                         OUI → CONFIRMED              │
                         NON → DECLINED           H-2 sans réponse
                         UNCLEAR → relance             │
                         STOP → opt-out                 ▼
                               │               [E] Risk Scoring AI
                               │ NON ou HIGH         │
                               └──────────────────────┤
                                                       ▼
                                              [D] Backup Finder
                                              → Shortlist recruteur
                                              → Pre-contact top backup

Mission terminée
      │
      ▼
[F] Outcome (PRESENT/ABSENT/LATE) → Mise à jour métriques → Re-score [E]
```

---

## Statuts de mission

| Statut | Description |
|--------|-------------|
| `PENDING_CONFIRMATION` | Mission créée, confirmation en attente |
| `CONFIRMED` | Candidat a confirmé |
| `DECLINED` | Candidat a décliné |
| `NEEDS_CLARIFICATION` | Réponse ambigüe, relance envoyée |
| `REMINDER_1_SENT` | Rappel J-2 10h00 envoyé |
| `REMINDER_2_SENT` | Rappel J-1 16h00 envoyé |
| `REMINDER_3_SENT` | Rappel H-2 envoyé |
| `HIGH_RISK_NO_RESPONSE` | H-2 sans réponse → backup déclenché |
| `REPLACEMENT_IN_PROGRESS` | Recherche de remplaçant en cours |
| `COMPLETED_PRESENT` | Mission terminée, candidat présent |
| `COMPLETED_ABSENT` | Mission terminée, candidat absent |
| `COMPLETED_LATE` | Mission terminée, candidat en retard |

---

## Prérequis

### Services externes
- **Twilio** — SMS / WhatsApp (compte + numéro)
- **OpenAI** — GPT-4o-mini pour le scoring risque (workflow E)
- **Slack** — Notifications recruteur (webhook URL)
- **PostgreSQL** — Base de données principale

### N8N
- Version 1.x ou supérieure
- Mode Queue recommandé en production

---

## Schéma PostgreSQL

```sql
-- Candidats
CREATE TABLE candidates (
  id                      SERIAL PRIMARY KEY,
  ats_candidate_id        VARCHAR(255) UNIQUE NOT NULL,
  name                    VARCHAR(255) NOT NULL,
  phone                   VARCHAR(50),
  email                   VARCHAR(255),
  skills                  TEXT[],
  location                VARCHAR(255),
  opt_out                 BOOLEAN DEFAULT FALSE,
  -- Métriques de fiabilité
  total_missions_count    INTEGER DEFAULT 0,
  present_count           INTEGER DEFAULT 0,
  absent_count            INTEGER DEFAULT 0,
  late_count              INTEGER DEFAULT 0,
  absence_rate            DECIMAL(5,4) DEFAULT 0,
  late_rate               DECIMAL(5,4) DEFAULT 0,
  no_reply_count          INTEGER DEFAULT 0,
  no_reply_declined       INTEGER DEFAULT 0,
  reliability_score       INTEGER DEFAULT 50,
  avg_response_time_minutes INTEGER,
  last30d_missions        INTEGER DEFAULT 0,
  created_at              TIMESTAMP DEFAULT NOW(),
  updated_at              TIMESTAMP DEFAULT NOW()
);

-- Recruteurs
CREATE TABLE recruiters (
  id              SERIAL PRIMARY KEY,
  name            VARCHAR(255),
  email           VARCHAR(255),
  phone           VARCHAR(50),
  slack_user_id   VARCHAR(100),
  created_at      TIMESTAMP DEFAULT NOW()
);

-- Missions
CREATE TABLE missions (
  id                        SERIAL PRIMARY KEY,
  ats_mission_id            VARCHAR(255) UNIQUE NOT NULL,
  ats_candidate_id          VARCHAR(255) REFERENCES candidates(ats_candidate_id),
  recruiter_id              INTEGER REFERENCES recruiters(id),
  mission_date              DATE NOT NULL,
  start_time                TIME DEFAULT '09:00',
  location                  VARCHAR(255),
  skill_required            VARCHAR(255),
  -- Statut
  status                    VARCHAR(50) DEFAULT 'PENDING_CONFIRMATION',
  risk_score                INTEGER,
  risk_level                VARCHAR(20),
  -- Timestamps clés
  reminder_1_scheduled_at   TIMESTAMP,
  reminder_2_scheduled_at   TIMESTAMP,
  reminder_3_scheduled_at   TIMESTAMP,
  reminder_1_sent_at        TIMESTAMP,
  reminder_2_sent_at        TIMESTAMP,
  reminder_3_sent_at        TIMESTAMP,
  confirmed_at              TIMESTAMP,
  completed_at              TIMESTAMP,
  arrival_time              TIME,
  outcome_notes             TEXT,
  created_at                TIMESTAMP DEFAULT NOW(),
  updated_at                TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_missions_status ON missions(status);
CREATE INDEX idx_missions_date ON missions(mission_date);
CREATE INDEX idx_candidates_phone ON candidates(phone);
CREATE INDEX idx_candidates_email ON candidates(email);
```

---

## Installation

### 1. Importer les workflows dans N8N

Dans N8N : **Settings → Import workflow** pour chaque fichier JSON :

1. `A_mission_created_or_updated.json`
2. `B_inbound_reply_handler.json`
3. `C_reminder_engine.json`
4. `D_backup_candidate_finder.json`
5. `E_risk_scoring_ai.json`
6. `F_mission_outcome_update.json`

### 2. Configurer les credentials

| Credential | Type N8N | Champs requis |
|------------|----------|---------------|
| `PostgreSQL ATS DB` | PostgreSQL | host, port, db, user, password |
| `Twilio Basic Auth` | HTTP Basic Auth | Account SID (user), Auth Token (pass) |
| `OpenAI API Key` | HTTP Header Auth | Header: `Authorization`, Value: `Bearer sk-...` |

### 3. Variables à remplacer dans les workflows

Chercher et remplacer dans chaque JSON :

| Placeholder | Valeur à remplacer |
|-------------|-------------------|
| `TWILIO_PHONE_NUMBER` | Votre numéro Twilio (ex: `+33XXXXXXXXX`) |
| `SLACK_WEBHOOK_URL` | URL complète du webhook Slack |
| `http://localhost:5678` | URL publique de votre instance N8N |

### 4. Activer les workflows

Activer dans cet ordre :
1. **F** (pas de dépendances)
2. **E** (pas de dépendances)
3. **D** (pas de dépendances)
4. **B** (pas de dépendances)
5. **C** — le cron démarre ici
6. **A** en dernier

---

## Webhook URLs (une fois activés)

| Workflow | Path | Usage |
|----------|------|-------|
| A | `POST /webhook/mission-event` | ATS → créer/modifier une mission |
| B | `POST /webhook/inbound-reply` | Twilio → SMS/WhatsApp entrant |
| D | `POST /webhook/backup-finder` | Interne — chercher un remplaçant |
| E | `POST /webhook/risk-scoring` | Interne — calculer le risque |
| F | `POST /webhook/mission-outcome` | Recruiter → saisir le résultat |

### Format payload — Workflow A
```json
{
  "mission_id": "ATS-001",
  "candidate_id": "CAND-042",
  "candidate_name": "Jean Dupont",
  "candidate_phone": "+33612345678",
  "candidate_email": "jean@example.com",
  "recruiter_id": "1",
  "mission_date": "2026-03-15",
  "start_time": "08:00",
  "location": "Paris 75001",
  "skill": "Manutentionnaire",
  "event_type": "created"
}
```

### Format payload — Workflow F
```json
{
  "mission_id": "123",
  "ats_mission_id": "ATS-001",
  "recruiter_id": "1",
  "outcome": "PRESENT",
  "notes": "RAS",
  "arrival_time": "08:05"
}
```

---

## Scoring de risque (Workflow E)

Le score va de **0** (aucun risque) à **100** (risque critique).

| Niveau | Score | Action |
|--------|-------|--------|
| LOW | 0–39 | Aucune action |
| MEDIUM | 40–69 | Notification recruteur |
| HIGH | 70–84 | Notification + backup automatique |
| CRITICAL | 85–100 | Backup immédiat + alerte urgente |

**Seuil de backup automatique** : score ≥ 70

---

## Backup automatique (Workflow D)

Le top backup est pré-contacté automatiquement si son `reliability_score ≥ 80`.
Sinon, la shortlist est envoyée au recruteur pour action manuelle.

**Critères de sélection** :
- Compétence correspondante
- Pas de mission le même jour
- Taux d'absence < 30%
- Non opt-out

**Score de classement** :
```
40% reliability_score
+ 30% (100 - absence_rate * 100)
+ 20% (100 - late_rate * 100)
+ 10% (100 - no_reply_count * 10)
```
