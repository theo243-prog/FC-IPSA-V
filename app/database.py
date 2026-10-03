"""
Connexion à la base de données.

En local : pas besoin de rien configurer, ça utilise un fichier SQLite
(fc_format_a5.db) créé automatiquement à côté de ce fichier.

En production : définis la variable d'environnement DATABASE_URL fournie
par Railway/Render (format postgresql://user:password@host:port/dbname)
et tout le reste du code fonctionne sans modification.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./fc_format_a5.db")

# SQLite a besoin de cet argument en plus quand on l'utilise avec FastAPI
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """À utiliser comme dépendance FastAPI : ouvre une session, la ferme après la requête."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
