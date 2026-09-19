# Rapport Phase 2 — cœur agentique (2026-09-19)

## Livré

Package `core/agent/` — la boucle EST le produit :

- **`events.py`** : contrat unique d'événements typés
  (`turn_start`, `reasoning_delta`, `tool_call`, `tool_result`,
  `content_delta`, `final`, `turn_end`, `agent_error`), `EventLog`
  persistable/rejouable avec agrégation d'usage.
- **`tools.py`** : registre déclaratif avec la couche anti-échec —
  validation stricte (sous-ensemble JSON Schema maison : requis, types,
  enums), timeout par outil, troncature de sortie, et chaque échec en
  `ToolResult` structuré (invalid_json / schema_violation / unknown_tool /
  timeout / execution_error) que le modèle peut réparer.
- **`orchestrator.py`** : machine à états déterministe avec les garanties
  mesurées en Phase 0 :
  - tours et budget de tokens bornés ;
  - **`finish_reason=length` sans tool call ⇒ un retry à budget doublé**
    (l'unique mode d'échec réel de Gemma 4 mesuré) ;
  - **détection de boucle** (même signature d'appel ×3 → divergence
    forcée) ;
  - erreurs d'outils renvoyées au modèle comme feedback structuré ;
  - interruption utilisateur à la frontière de tour (`should_stop`).
- **`builtin.py`** : outillage minimal dépendance-zéro (`calculate` via
  AST sûr, `current_time`, `echo`) pour valider la boucle de bout en bout.
- **Endpoint `/api/agent/stream`** : SSE typés via file d'attente +
  tâche annulable, modèle validé par l'allowlist existante.

## Preuves

- **Tests** : 15 nouveaux (`tests/test_agent_core.py`) couvrant réponse
  directe, aller-retour d'outil (assembly des deltas `tool_calls`),
  réparation d'arguments invalides (le modèle reçoit l'erreur
  structurée et corrige), retry budgété sur troncature, détection de
  boucle, borne de tours, interruption, erreur d'inférence, format SSE.
  Suite complète : **144 verts**.
- **Run live sur gemma-4-e4b** (router Phase 1) : question à deux besoins
  (« calcule (17*23)+100 et donne la date du jour ») →
  `calculate("(17*23)+100")` → 491 ✓, `current_time` → samedi
  19 septembre 2026 ✓, réponse finale synthétisant les deux, 3 tours,
  zéro appel malformé, timeline complète streamée.

## Décisions notables

- Le validateur de schéma est volontairement minimal (requis + types +
  enums) : zéro dépendance, et les extras non déclarés sont tolérés —
  les modèles en produisent d'inoffensifs.
- Pas de parallélisme des tools dans la boucle pour l'instant
  (`max_parallel_tools` borne l'exécution séquentielle des appels
  multiples d'un même tour) ; la parallélisation arrivait avec les
  outils lents (web) en Phase 3.
- La mémoire/compaction existante n'est pas encore branchée dans la
  boucle : l'orchestrateur reçoit des messages prédéfinis ; le
  rebranchement contexte complet se fait en Phase 4 avec la refonte
  des routers.

## Porte de sortie

Atteinte : la boucle agent complète (plan implicite → outils → réponse)
fonctionne en live, testée, bornée, rejouable.
