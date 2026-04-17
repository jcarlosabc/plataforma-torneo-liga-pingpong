# -*- coding: utf-8 -*-
"""
Carga la Liga de Duplas con los resultados del archivo orden.txt.
Limpia y recrea todas las tablas. Ejecutar una sola vez.

  python seed_liga.py
"""
import os, sys
from itertools import combinations
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# ── 1. Recrear tablas ──────────────────────────────────────
from database import Base, engine, SessionLocal
import models

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
db = SessionLocal()
print("OK - Tablas recreadas.")

# ── 2. Jugadores ────────────────────────────────────────────
PLAYERS = ["Jean", "Jairo", "Orlando", "Fermin",
           "Christian", "Julio", "Jose", "Greyson",
           "Luis Angel", "Alex"]

for name in PLAYERS:
    db.add(models.Player(name=name))
db.flush()

players = {p.name: p.id for p in db.query(models.Player).all()}
print(f"OK - {len(players)} jugadores creados.")

# ── 3. Equipos ──────────────────────────────────────────────
TEAMS_DEF = [
    ("JJ",               "Jean",        "Jairo"),
    ("Orlando y Fermin", "Orlando",     "Fermin"),
    ("Christian y Julio","Christian",   "Julio"),
    ("Jose y Greyson",   "Jose",        "Greyson"),
    ("Luis Angel y Alex","Luis Angel",  "Alex"),
]

for t_name, p1, p2 in TEAMS_DEF:
    db.add(models.Team(name=t_name,
                       player1_id=players[p1],
                       player2_id=players[p2]))
db.flush()

teams = {t.name: t.id for t in db.query(models.Team).all()}
print(f"OK - {len(teams)} equipos creados.")

# ── 4. Liga Ida y Vuelta ────────────────────────────────────
league = models.League(
    name="Liga Duplas 2024",
    type="doubles",
    double_rr=True,
    status="active",
)
db.add(league)
db.flush()
lid = league.id
print(f"OK - Liga creada (id={lid}).")

for tid in teams.values():
    db.add(models.LeagueParticipant(league_id=lid, participant_id=tid))
db.flush()

# ── 5. Generar calendario ──────────────────────────────────
# IDA: 9 pares (se excluye Christian y Julio vs Luis Angel y Alex)
# VUELTA: los 10 pares invertidos (todos los enfrentamientos en casa)
tid_list = list(teams.values())
all_pairs_ida = list(combinations(tid_list, 2))

# Par que NO se jugo en ida
skip_ida = frozenset([teams["Christian y Julio"], teams["Luis Angel y Alex"]])
pairs_ida    = [p for p in all_pairs_ida if frozenset(p) != skip_ida]
pairs_vuelta = [(b, a) for a, b in all_pairs_ida]   # los 10 pares invertidos

n_ida    = len(pairs_ida)
n_vuelta = len(pairs_vuelta)
counter  = 1

for p1, p2 in pairs_ida:
    db.add(models.Match(league_id=lid, round=1, match_in_round=counter,
                        participant1_id=p1, participant2_id=p2, status="pending"))
    counter += 1

for p1, p2 in pairs_vuelta:
    db.add(models.Match(league_id=lid, round=2, match_in_round=counter,
                        participant1_id=p1, participant2_id=p2, status="pending"))
    counter += 1

db.commit()
total = n_ida + n_vuelta
print(f"OK - {total} partidos generados ({n_ida} ida + {n_vuelta} vuelta).")

# ── 6. Registrar resultados ya jugados (TODOS son IDA, round=1) ──
# Formato: (p1_segun_combinacion, p2_segun_combinacion, score_p1, score_p2)
# Las combinaciones generan pares en el orden de la lista de equipos:
# JJ(1) Orlando(2) Christian(3) Jose(4) Luis(5)
# Pares ida: (1,2)(1,3)(1,4)(1,5)(2,3)(2,4)(2,5)(3,4)(3,5)(4,5)
# El que aparece primero en la lista es siempre participant1.
# "Orlando gano 6-4 a JJ" => par ida es (JJ, Orlando), score1=4, score2=6
# "Luis gano 5-2 a Jose"  => par ida es (Jose, Luis),  score1=2, score2=5
RESULTS_IDA = [
    # (p1_combo,           p2_combo,            s1, s2)
    ("JJ",               "Orlando y Fermin",   4, 6),  # Orlando gano 6-4
    ("JJ",               "Christian y Julio",  6, 4),  # JJ gano 6-4
    ("JJ",               "Jose y Greyson",     5, 2),  # JJ gano 5-2
    ("JJ",               "Luis Angel y Alex",  5, 1),  # JJ gano 5-1
    ("Orlando y Fermin", "Christian y Julio",  9, 7),  # Orlando gano 9-7
    ("Orlando y Fermin", "Jose y Greyson",     5, 2),  # Orlando gano 5-2
    ("Orlando y Fermin", "Luis Angel y Alex",  5, 1),  # Orlando gano 5-1
    ("Christian y Julio","Jose y Greyson",     5, 0),  # Christian gano 5-0
    # (Christian y Julio vs Luis Angel y Alex) <- FALTA, no se ha jugado
    ("Jose y Greyson",   "Luis Angel y Alex",  2, 5),  # Luis gano 5-2
]

ok = 0
for t1_name, t2_name, s1, s2 in RESULTS_IDA:
    p1_id = teams[t1_name]
    p2_id = teams[t2_name]
    # Buscar en IDA (round=1) con el orden exacto de combinaciones
    match = (db.query(models.Match)
               .filter(models.Match.league_id == lid,
                       models.Match.round == 1,
                       models.Match.participant1_id == p1_id,
                       models.Match.participant2_id == p2_id,
                       models.Match.status == "pending")
               .first())
    if match:
        match.score1       = s1
        match.score2       = s2
        match.winner_id    = p1_id if s1 > s2 else p2_id
        match.status       = "completed"
        match.completed_at = datetime.utcnow()
        ok += 1
    else:
        print(f"  WARN - No encontrado en IDA: {t1_name} vs {t2_name}")

db.commit()
print(f"OK - {ok} resultados registrados (todos en IDA).")

# ── 7. Tabla de posiciones actual ──────────────────────────
print("\n" + "="*55)
print("  TABLA DE POSICIONES  (jugados: 9 / 20)")
print("="*55)

stats = {tid: {"name": tname, "W": 0, "L": 0, "SF": 0, "SC": 0}
         for tname, tid in teams.items()}

done = (db.query(models.Match)
          .filter(models.Match.league_id == lid,
                  models.Match.status == "completed")
          .all())

for m in done:
    stats[m.participant1_id]["SF"] += m.score1
    stats[m.participant1_id]["SC"] += m.score2
    stats[m.participant2_id]["SF"] += m.score2
    stats[m.participant2_id]["SC"] += m.score1
    if m.score1 > m.score2:
        stats[m.participant1_id]["W"] += 1
        stats[m.participant2_id]["L"] += 1
    else:
        stats[m.participant2_id]["W"] += 1
        stats[m.participant1_id]["L"] += 1

rows = sorted(stats.values(),
              key=lambda x: (-x["W"]*3, -(x["SF"]-x["SC"]), -x["SF"]))

medals = {0:"1o", 1:"2o", 2:"3o"}
print(f"  {'#':<4} {'Equipo':<22} {'PJ':>3} {'G':>3} {'P':>3} {'SF':>4} {'SC':>4} {'Dif':>5} {'Pts':>4}")
print("  " + "-"*53)
for i, r in enumerate(rows):
    pj  = r["W"] + r["L"]
    pts = r["W"] * 3
    diff = r["SF"] - r["SC"]
    medal = medals.get(i, f"{i+1}o")
    print(f"  {medal:<4} {r['name']:<22} {pj:>3} {r['W']:>3} {r['L']:>3} "
          f"{r['SF']:>4} {r['SC']:>4} {diff:>+5} {pts:>4}")

# ── 8. Partidos pendientes ─────────────────────────────────
pending = (db.query(models.Match)
             .filter(models.Match.league_id == lid,
                     models.Match.status == "pending")
             .order_by(models.Match.round, models.Match.match_in_round)
             .all())

team_by_id = {v: k for k, v in teams.items()}

print(f"\n  PARTIDOS PENDIENTES ({len(pending)} restantes de 20)")
print("="*55)
cur_leg = None
for m in pending:
    if m.round != cur_leg:
        cur_leg = m.round
        label = "-- IDA --" if cur_leg == 1 else "-- VUELTA --"
        print(f"\n  {label}")
    t1 = team_by_id.get(m.participant1_id, "?")
    t2 = team_by_id.get(m.participant2_id, "?")
    print(f"    {t1}  vs  {t2}")

print("\nListo! Corre: uvicorn main:app --reload --port 8080")
print("Busca la liga en http://localhost:8080/leagues")
db.close()
