"""Formulaires des commandes d'administration ajoutées après coup (éditions libres)."""
from typing import Optional

from pydantic import BaseModel


class DefineEditionRequest(BaseModel):
    label: str                          # nom de l'édition (ex. « Saint-Valentin »)
    icon: str                           # un emoji (ex. 💘)
    color1: str                         # couleur foncée, #RRGGBB
    color2: str                         # couleur claire, #RRGGBB
    start: str                          # premier jour, AAAA-MM-JJ
    end: str                            # dernier jour, AAAA-MM-JJ
    slot: Optional[str] = "auto"        # ed1 à ed6, ou « auto » = le premier emplacement libre


class RemoveEditionRequest(BaseModel):
    edition: str                        # ed1 à ed6
