"""Routers FastAPI par domaine — pattern d'éclatement progressif de main.py.

Chaque module expose une fabrique ``create_*_router(dépendances)`` et
main.py l'inclut via ``app.include_router``. Les dépendances sont
injectées explicitement pour éviter les cycles d'import.
"""
