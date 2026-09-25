# ADR-001 — Stockage des données : SQLite unique, un seul écrivain

**Statut** : accepté · **Date** : 2026-09-25 · **Phase** : D3 de la ROADMAP

## Contexte

La refacto modulaire (phases A→E) introduit des modules métier, une file de
jobs durable et un worker. Faut-il découper `lasme_llm.db` (4 stores
logiques : mémoire, RAG, fichiers, artefacts) en bases par module, ou
passer à Postgres ?

## Décision

**Garder un fichier SQLite unique, avec un seul process écrivain, tant que
l'application reste locale et mono-machine.**

- Le schéma est déjà séparé par tables : le découpage logique existe
  (repositories par domaine, voir `core/memory/repos.py`). Le découpage
  *physique* n'apporte rien tant qu'il n'y a pas de scaling horizontal.
- Le worker de jobs tourne **dans le process API** par défaut (mode
  « in-process » du lifespan) : il partage donc le même fichier sans
  arbitrage multi-écrivains. Le binaire séparé `python -m chat.worker`
  n'est activé qu'en phase F, avec la règle « un seul écrivain fort »
  (le worker devient alors l'écrivain des tâches de fond, l'API reste
  l'écrivain du flux utilisateur — SQLite WAL le supporte, le vrai
  interdit reste de manipuler les journaux).

## Conséquences

1. **Ne jamais supprimer `lasme_llm.db-wal` / `-shm`** : les écritures
   récentes y vivent jusqu'au checkpoint ; suppression = perte définitive.
   L'arrêt propre passe par `DatabaseManager.checkpoint()`
   (`PRAGMA wal_checkpoint(TRUNCATE)`) — câblé dans le lifespan, à
   conserver dans tout nouveau process qui ouvre la base.
2. `PRAGMA wal_autocheckpoint = 64` est posé à chaque connexion pour
   garder le fichier principal à jour.
3. **Migration Postgres** : à envisager uniquement si (a) plusieurs
   machines écrivent, ou (b) le volume/la concurrence dépasse SQLite.
   Les repositories (`core/memory/repos.py`) sont la couture de
   remplacement : un seul module à réimplémenter, les modules métier
   ne parlent qu'à eux.

## Alternatives rejetées

- **SQLite par module** : coordination multi-fichiers (pas de jointures,
  sauvegardes croisées) sans bénéfice en local.
- **Postgres dès maintenant** : coût d'exploitation (service à installer,
  à sauvegarder, à versionner) pour une app locale mono-utilisateur.
