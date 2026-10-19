"""
Mini-jeu du jour : il remplace un des trois défis quotidiens (voir missions.py : « Joue au mini-jeu du jour »).
Un jeu par jour et par joueur, qui alterne : jours pairs = TIRS AU BUT, jours impairs = QUIZ FOOT. Il rapporte des points de Pass (10 par bonne réponse ou but, 50 au maximum) ;
la mission du jour se récupère ensuite comme les autres (crédits). Tout se joue côté serveur (la bonne réponse n'est jamais envoyée avant qu'on ait répondu).
"""
import json
import random
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.orm import Session

from .database import Base, get_db
from .models import User
from .security import get_current_user
from . import game_logic, missions, battlepass

router = APIRouter()
ROUNDS, POINTS_EACH = 5, 10
RNG = random.SystemRandom()                  # (remplacé dans les tests)
ZONES = ["à gauche", "au centre", "à droite"]

# (question, bonne réponse, deux mauvaises, explication)
BANK = [
    ("Quel pays a gagné la Coupe du monde 2018 ?", "La France", ["La Croatie", "La Belgique"], "Les Bleus ont battu la Croatie 4-2 en finale, à Moscou."),
    ("Quel pays a gagné la Coupe du monde 2022 ?", "L'Argentine", ["La France", "La Croatie"], "L'Argentine a battu la France aux tirs au but après un 3-3."),
    ("Dans quel pays s'est jouée la Coupe du monde 2022 ?", "Au Qatar", ["En Russie", "Au Brésil"], "C'était la première Coupe du monde organisée au Qatar."),
    ("Quel pays a gagné la Coupe du monde 2014 ?", "L'Allemagne", ["L'Argentine", "Les Pays-Bas"], "L'Allemagne a battu l'Argentine 1-0 en prolongation."),
    ("Quel pays a gagné la Coupe du monde 2006 ?", "L'Italie", ["La France", "L'Allemagne"], "L'Italie a gagné aux tirs au but contre la France."),
    ("Quel pays a gagné la Coupe du monde 2002 ?", "Le Brésil", ["L'Allemagne", "La Turquie"], "Ronaldo a marqué deux buts en finale contre l'Allemagne."),
    ("Quel pays a organisé la Coupe du monde 1998 ?", "La France", ["L'Italie", "Les États-Unis"], "La France a gagné à domicile, au Stade de France."),
    ("Quels pays organisent la Coupe du monde 2026 ?", "États-Unis, Canada et Mexique", ["Espagne, Portugal et Maroc", "Chine, Japon et Corée du Sud"], "C'est la première Coupe du monde à trois pays hôtes."),
    ("Qui a gagné l'Euro 2016 ?", "Le Portugal", ["La France", "L'Allemagne"], "Le Portugal a battu la France 1-0 en prolongation."),
    ("Qui a gagné l'Euro 2024 ?", "L'Espagne", ["L'Angleterre", "La France"], "L'Espagne a battu l'Angleterre 2-1 en finale."),
    ("Qui a marqué la célèbre « main de Dieu » en 1986 ?", "Diego Maradona", ["Pelé", "Michel Platini"], "C'était contre l'Angleterre, en quart de finale."),
    ("Qui a marqué 13 buts en une seule Coupe du monde (1958) ?", "Just Fontaine", ["Pelé", "Gerd Müller"], "Un record toujours inégalé, établi par un Français."),
    ("Qui est le meilleur buteur de l'histoire des Coupes du monde (16 buts) ?", "Miroslav Klose", ["Lionel Messi", "Pelé"], "Klose a marqué 16 buts en quatre Coupes du monde."),
    ("Combien de Coupes du monde Pelé a-t-il gagnées en tant que joueur ?", "3", ["2", "4"], "En 1958, 1962 et 1970."),
    ("Qui a marqué un doublé de la tête en finale de la Coupe du monde 1998 ?", "Zinédine Zidane", ["Thierry Henry", "Didier Deschamps"], "La France a battu le Brésil 3-0."),
    ("Combien de buts Kylian Mbappé a-t-il marqués en finale de la Coupe du monde 2022 ?", "3", ["1", "2"], "Un triplé, mais l'Argentine a gagné aux tirs au but."),
    ("Quel joueur a reçu le Ballon d'or 2018 ?", "Luka Modrić", ["Cristiano Ronaldo", "Antoine Griezmann"], "Modrić avait emmené la Croatie en finale du Mondial."),
    ("Quel joueur a reçu le Ballon d'or 2022 ?", "Karim Benzema", ["Lionel Messi", "Kylian Mbappé"], "Benzema avait gagné la Ligue des champions avec le Real Madrid."),
    ("Quel joueur a reçu le Ballon d'or 2023 ?", "Lionel Messi", ["Erling Haaland", "Kylian Mbappé"], "Messi avait gagné la Coupe du monde 2022."),
    ("Qui est le meilleur buteur de l'histoire de la Ligue des champions ?", "Cristiano Ronaldo", ["Lionel Messi", "Robert Lewandowski"], "Ronaldo a dépassé les 130 buts dans la compétition."),
    ("Quel club a gagné le plus de Ligues des champions ?", "Le Real Madrid", ["L'AC Milan", "Liverpool"], "Le Real Madrid est le recordman de la compétition."),
    ("Quel club français a gagné la Ligue des champions en 1993 ?", "L'Olympique de Marseille", ["Le PSG", "L'AS Monaco"], "L'OM a battu l'AC Milan 1-0."),
    ("Dans quel stade joue le FC Barcelone ?", "Le Camp Nou", ["Santiago Bernabéu", "Anfield"], "Le Camp Nou est l'un des plus grands stades d'Europe."),
    ("Quel club joue à Anfield ?", "Liverpool", ["Manchester United", "Chelsea"], "Anfield est le stade de Liverpool."),
    ("Quel club joue à Old Trafford ?", "Manchester United", ["Manchester City", "Arsenal"], "Old Trafford, surnommé « le Théâtre des rêves »."),
    ("Quel club joue au Parc des Princes ?", "Le Paris Saint-Germain", ["L'Olympique de Marseille", "L'Olympique Lyonnais"], "Le Parc des Princes est le stade du PSG."),
    ("Quel club joue au Stade Vélodrome ?", "L'Olympique de Marseille", ["Le Paris Saint-Germain", "L'AS Monaco"], "Le Vélodrome est le stade de l'OM."),
    ("Quel est le surnom de l'équipe de France ?", "Les Bleus", ["Les Rouges", "Les Diables"], "Les Diables rouges, eux, sont les Belges."),
    ("Quel est le surnom de l'équipe du Brésil ?", "La Seleção", ["La Roja", "La Nazionale"], "La Roja est l'Espagne, la Nazionale l'Italie."),
    ("De quelle couleur est le maillot traditionnel des Pays-Bas ?", "Orange", ["Bleu", "Rouge"], "On les surnomme les « Oranje »."),
    ("Dans quel pays se joue la Bundesliga ?", "L'Allemagne", ["L'Autriche", "Les Pays-Bas"], "La Bundesliga est le championnat d'Allemagne."),
    ("Dans quel pays se joue la Serie A ?", "L'Italie", ["L'Espagne", "L'Allemagne"], "La Serie A est le championnat d'Italie."),
    ("De quel pays vient Erling Haaland ?", "La Norvège", ["La Suède", "Le Danemark"], "Haaland est norvégien."),
    ("À quelle distance du but est tiré un penalty ?", "11 mètres", ["9 mètres", "13 mètres"], "Le point de penalty est à 11 mètres de la ligne de but."),
    ("Combien de joueurs par équipe sur le terrain, gardien compris ?", "11", ["10", "12"], "Onze joueurs par équipe."),
    ("Combien dure un match réglementaire ?", "90 minutes", ["80 minutes", "100 minutes"], "Deux mi-temps de 45 minutes."),
    ("Combien de cartons jaunes dans un même match entraînent une expulsion ?", "2", ["1", "3"], "Le deuxième carton jaune devient un carton rouge."),
    ("Quelle est la hauteur réglementaire d'un but ?", "2,44 m", ["2,00 m", "3,00 m"], "Un but fait 7,32 m de large et 2,44 m de haut."),
    ("Que se passe-t-il quand un joueur est signalé hors-jeu ?", "Coup franc indirect pour l'adversaire", ["Penalty", "Carton jaune"], "Le hors-jeu n'est pas une faute sanctionnée par un carton."),
    ("Quel numéro porte traditionnellement le gardien de but ?", "Le 1", ["Le 9", "Le 10"], "Le 9 est souvent l'avant-centre, le 10 le meneur de jeu."),
    ("Qui a donné un coup de tête à Materazzi en finale 2006 ?", "Zinédine Zidane", ["Patrick Vieira", "Franck Ribéry"], "Zidane a été expulsé lors de son dernier match en professionnel."),
]


class MinigameRun(Base):
    __tablename__ = "minigame_runs"
    user_id = Column(String, primary_key=True)
    day = Column(String, primary_key=True)            # « AAAA-MM-JJ »
    kind = Column(String, nullable=False)
    state = Column(Text, nullable=False, default="{}")
    score = Column(Integer, nullable=False, default=0)
    finished = Column(Integer, nullable=False, default=0)


def _today() -> str:
    return game_logic.today_paris().isoformat()


def kind_for(day: str) -> str:
    return "penalty" if date.fromisoformat(day).toordinal() % 2 == 0 else "quiz"


def questions_for(day: str) -> list:
    """Les 5 questions du jour (les mêmes pour tout le monde), avec l'ordre des réponses mélangé de façon fixe."""
    r = random.Random("quiz-" + day); picks = r.sample(BANK, ROUNDS); out = []
    for i, (q, good, bad, why) in enumerate(picks):
        choices = [good] + list(bad); random.Random("%s-%d" % (day, i)).shuffle(choices)
        out.append({"q": q, "choices": choices, "answer": choices.index(good), "why": why})
    return out


def _run(db: Session, user: User, create: bool = False):
    day = _today(); run = db.get(MinigameRun, (user.id, day))
    if run is None and create:
        run = MinigameRun(user_id=user.id, day=day, kind=kind_for(day), state=json.dumps({"answers": [], "shots": []})); db.add(run); db.flush()
    return day, run


def _view(day: str, run) -> dict:
    kind = run.kind if run else kind_for(day); st = json.loads(run.state) if run else {"answers": [], "shots": []}
    out = {"day": day, "kind": kind, "title": "Quiz foot" if kind == "quiz" else "Tirs au but", "rounds": ROUNDS, "started": run is not None, "finished": bool(run and run.finished),
           "score": run.score if run else 0, "pass_points": min(ROUNDS * POINTS_EACH, (run.score if run else 0) * POINTS_EACH) if run and run.finished else 0, "points_each": POINTS_EACH}
    if kind == "quiz":
        qs = questions_for(day); n = len(st["answers"]); out["answers"] = [{"correct": a["correct"], "choice": a["choice"], "answer": qs[i]["answer"], "why": qs[i]["why"]} for i, a in enumerate(st["answers"])]
        if not out["finished"] and n < ROUNDS:
            out["question"] = {"index": n, "text": qs[n]["q"], "choices": qs[n]["choices"]}
    else:
        out["shots"] = st["shots"]
        if not out["finished"]:
            out["remaining"] = ROUNDS - len(st["shots"])
    return out


def _finish(db: Session, user: User, run) -> None:
    run.finished = 1
    battlepass.add_points(db, user, "minigame", run.score * POINTS_EACH, cap=ROUNDS * POINTS_EACH)
    db.commit()
    missions.safe_record(db, user, "minigame")


@router.get("/minigame")
def get_minigame(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    day, run = _run(db, user)
    return _view(day, run)


class AnswerRequest(BaseModel):
    choice: int = Field(ge=0, le=2)


class ShootRequest(BaseModel):
    zone: int = Field(ge=0, le=2)


@router.post("/minigame/answer")
def answer(payload: AnswerRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    day, run = _run(db, user, create=True)
    if run.kind != "quiz":
        raise HTTPException(status_code=400, detail="Le mini-jeu du jour est une séance de tirs au but")
    if run.finished:
        raise HTTPException(status_code=400, detail="Tu as déjà terminé le mini-jeu du jour : reviens demain !")
    st = json.loads(run.state); qs = questions_for(day); i = len(st["answers"]); good = payload.choice == qs[i]["answer"]
    st["answers"].append({"choice": payload.choice, "correct": good}); run.state = json.dumps(st); run.score += 1 if good else 0
    if len(st["answers"]) >= ROUNDS:
        _finish(db, user, run)
    else:
        db.commit()
    return {"correct": good, "answer": qs[i]["answer"], "why": qs[i]["why"], **_view(day, run)}


@router.post("/minigame/shoot")
def shoot(payload: ShootRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    day, run = _run(db, user, create=True)
    if run.kind != "penalty":
        raise HTTPException(status_code=400, detail="Le mini-jeu du jour est un quiz")
    if run.finished:
        raise HTTPException(status_code=400, detail="Tu as déjà terminé le mini-jeu du jour : reviens demain !")
    st = json.loads(run.state); prev = st["shots"][-1]["zone"] if st["shots"] else None
    keeper = prev if (prev is not None and RNG.random() < 0.4) else RNG.randrange(3)          # le gardien devine un peu : il a tendance à replonger du côté de ton dernier tir
    missed = RNG.random() < 0.1                                                                  # 10 % : le tir passe à côté ou sur le poteau
    goal = payload.zone != keeper and not missed
    st["shots"].append({"zone": payload.zone, "keeper": keeper, "goal": goal, "missed": missed}); run.state = json.dumps(st); run.score += 1 if goal else 0
    if len(st["shots"]) >= ROUNDS:
        _finish(db, user, run)
    else:
        db.commit()
    return {"goal": goal, "missed": missed, "keeper": keeper, "zone_name": ZONES[payload.zone], **_view(day, run)}


def on_user_deleted(db: Session, user_id: str) -> None:
    db.query(MinigameRun).filter_by(user_id=user_id).delete()
