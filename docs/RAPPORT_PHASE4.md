# Rapport Phase 4 — plateforme & UX agent-first (2026-09-19)

## Périmètre livré (tranche 1 de la refonte plateforme)

Décision assumée : plutôt qu'un éclatement risqué du monolithe de
`main.py` (4 200+ lignes) en une seule fois, la Phase 4 livre d'abord
**l'expérience agent complète utilisable** et installe le pattern
modulaire ES pour la suite.

- **`chat/web/agent.html` + `agent.js`** : console agent autonome —
  premier module ES du frontend (plus de fichier monolithique pour la
  nouvelle surface).
  - timeline des tours : raisonnement repliable, **cartes d'outils**
    (nom, arguments JSON formatés, résultat, durée, échec ouvert par
    défaut avec code d'erreur), réponse finale ;
  - sélecteur de profil (4 modèles v2), budget de tours, métriques
    (tours, caractères de raisonnement, durée totale) ;
  - historique de conversation en mémoire, arrêt en cours de run
    (AbortController), markdown-lite sécurisé (échappement HTML
    systématique, liens `noopener noreferrer`) ;
  - lien « Agent » (éclair) dans la barre latérale du chat principal.
- **Zéro modification du comportement du chat existant** : la console
  consomme `/api/agent/stream` (Phase 2) et cohabite avec l'UI v1.

## Preuve — test GUI navigateur (boîte noire, IAB)

Mission saisie à la main dans la page : « Calcule (19*21)+7 avec l'outil
calculate et donne juste le résultat. »

- modèle par défaut `gemma-4-12b` (chargé à la demande via router) ;
- réponse finale affichée : **406** — exact ;
- timeline complète rendue : bulle utilisateur, TOUR 1 (raisonnement +
  carte `calculate`), TOUR 2 (réponse), métriques « 2 tours · 213 car.
  de raisonnement · 1,4 s » ;
- capture avant/après inspectée visuellement.

**Défauts détectés par le test visuel puis corrigés** (le test a fait
son travail) : contraste insuffisant du titre et de la réponse finale
sur fond sombre → couleurs explicites ; durée « 0 ms » → « < 5 ms » ;
espacement du lien Chat. Re-vérification visuelle après correctif :
conforme, aucun défaut restant.

## Reporter à une tranche 2 (documenté, pas oublié)

- Éclatement de `chat/server/main.py` en routers par domaine —
  mécanique mais conflictuelle ; à faire en session dédiée avec la
  refonte du chat v1 vers la timeline agent.
- Intégration canvas/artefacts comme outils agent (le socle Phase 3
  est prêt à les recevoir).
- Migration complète du chat v1 sur les événements typés (la console
  agent est la référence d'implémentation).

## Porte de sortie

Atteinte : une UI agent-first moderne, testée visuellement en vrai
navigateur, répondant correctement (406) via le chemin complet
navigateur → FastAPI → orchestrateur → llama.cpp.
