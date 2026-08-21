"""Mécanique relationnelle Ami(e) IA — logique 100 % déterministe.

Ce paquet reprend, côté serveur dédié, tout ce qui était confié aux Tools et
au Filter OpenWebUI du projet d'origine :
- stages   : échelle de score → stade + consignes de comportement ;
- scoring  : évaluation automatique des messages (mots-clés + patterns) ;
- presets  : personnages prédéfinis + scénarios d'événements (gates par stade) ;
- state    : profil persistant par session (écritures atomiques) ;
- memory   : souvenirs sémantiques (embeddings via llamaembed).

Le LLM n'appelle AUCUN outil : il incarne le personnage, le serveur gère
toute la mécanique (score, stades, scénarios, photos, souvenirs).
"""
