import math
import os
import pathlib
from collections import defaultdict
from datetime import datetime
from itertools import combinations

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

import models
from database import Base, engine, get_db
from sqlalchemy import text

AVATARS_DIR = pathlib.Path("static/avatars")
AVATARS_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

Base.metadata.create_all(bind=engine)

# Migración automática: agrega columnas nuevas si no existen
with engine.connect() as _conn:
    for _stmt in [
        "ALTER TABLE leagues ADD COLUMN matches_per_jornada INTEGER DEFAULT 1",
        "ALTER TABLE players ADD COLUMN avatar TEXT",
    ]:
        try:
            _conn.execute(text(_stmt))
            _conn.commit()
        except Exception:
            pass

# Migración: agregar columna locked si no existe
with engine.connect() as _conn:
    try:
        _conn.execute(text("ALTER TABLE matches ADD COLUMN locked BOOLEAN NOT NULL DEFAULT 0"))
        _conn.commit()
    except Exception:
        pass  # ya existe

app = FastAPI(title="Ping Pong Tournament")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ─────────────────────── auth ────────────────────────

ADMIN_USER = os.getenv("ADMIN_USER", "superadmin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "pingpong321321")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.is_admin = bool(request.session.get("admin"))
        if (
            request.method == "POST"
            and request.url.path != "/login"
            and not request.state.is_admin
        ):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)


app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "pp-secret-key-2024"))


# ─────────────────────── helpers ────────────────────────

async def _save_avatar(player_id: int, file: UploadFile) -> str | None:
    if not file or not file.filename:
        return None
    ext = pathlib.Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return None
    # Elimina avatar anterior si existe
    for old in AVATARS_DIR.glob(f"player_{player_id}.*"):
        old.unlink(missing_ok=True)
    filename = f"player_{player_id}{ext}"
    (AVATARS_DIR / filename).write_bytes(await file.read())
    return filename


def _avatar_url(filename: str | None) -> str | None:
    return f"/static/avatars/{filename}" if filename else None


def get_participant_name(db: Session, pid, p_type: str) -> str:
    if pid is None:
        return "BYE"
    if p_type == "individual":
        p = db.query(models.Player).filter(models.Player.id == pid).first()
        return p.name if p else "?"
    else:
        t = db.query(models.Team).filter(models.Team.id == pid).first()
        return t.name if t else "?"


def get_participant_detail(db: Session, pid, p_type: str):
    """Returns a dict with id, name (and players/avatars if team)."""
    if pid is None:
        return None
    if p_type == "individual":
        p = db.query(models.Player).filter(models.Player.id == pid).first()
        if not p:
            return None
        return {"id": p.id, "name": p.name, "avatar": _avatar_url(p.avatar)}
    else:
        t = db.query(models.Team).filter(models.Team.id == pid).first()
        if not t:
            return None
        return {
            "id": t.id,
            "name": t.name,
            "players": f"{t.player1.name} / {t.player2.name}",
            "player1_name": t.player1.name,
            "player2_name": t.player2.name,
            "avatar1": _avatar_url(t.player1.avatar),
            "avatar2": _avatar_url(t.player2.avatar),
        }


def get_round_label(round_num: int, total_rounds: int) -> str:
    remaining = total_rounds - round_num
    if remaining == 0:
        return "Final"
    if remaining == 1:
        return "Semifinal"
    if remaining == 2:
        return "Cuartos de Final"
    if remaining == 3:
        return "Octavos de Final"
    return f"Ronda {round_num}"


def enrich_match(db: Session, m: models.Match, p_type: str) -> dict:
    return {
        "id": m.id,
        "round": m.round,
        "match_in_round": m.match_in_round,
        "p1": get_participant_detail(db, m.participant1_id, p_type),
        "p2": get_participant_detail(db, m.participant2_id, p_type),
        "score1": m.score1,
        "score2": m.score2,
        "winner": get_participant_detail(db, m.winner_id, p_type) if m.winner_id else None,
        "status": m.status,
        "is_bye": m.is_bye,
        "is_third_place": m.is_third_place,
        "locked": m.locked,
    }


def create_bracket(db: Session, tournament_id: int, participant_ids: list[int]):
    n = len(participant_ids)
    size = 1
    while size < n:
        size *= 2

    padded = list(participant_ids) + [None] * (size - n)
    num_rounds = int(math.log2(size))

    # ── build all match placeholders ──────────────────────
    round_matches: dict[int, list[models.Match]] = {}
    for r in range(1, num_rounds + 1):
        count = size // (2 ** r)
        round_matches[r] = []
        for i in range(count):
            m = models.Match(
                tournament_id=tournament_id,
                round=r,
                match_in_round=i + 1,
                status="pending",
            )
            db.add(m)
            round_matches[r].append(m)

    # 3rd place match (only when bracket has at least 4 slots → SF exists)
    third_place = None
    if num_rounds >= 2:
        third_place = models.Match(
            tournament_id=tournament_id,
            round=num_rounds,
            match_in_round=0,
            is_third_place=True,
            status="pending",
        )
        db.add(third_place)

    db.flush()  # assign IDs before wiring

    # ── fill round-1 participants ─────────────────────────
    for i, m in enumerate(round_matches[1]):
        m.participant1_id = padded[i * 2]
        m.participant2_id = padded[i * 2 + 1]
        if padded[i * 2 + 1] is None:          # bye
            m.is_bye = True
            m.status = "completed"
            m.winner_id = padded[i * 2]

    # ── wire winner-advance pointers ─────────────────────
    for r in range(1, num_rounds):
        for i, m in enumerate(round_matches[r]):
            nxt = round_matches[r + 1][i // 2]
            m.next_match_id = nxt.id
            m.next_match_slot = (i % 2) + 1

    # ── wire loser-advance pointers to 3rd place ─────────
    if third_place and num_rounds >= 2:
        sf = round_matches[num_rounds - 1]   # always 2 matches
        sf[0].loser_next_match_id = third_place.id
        sf[0].loser_next_match_slot = 1
        sf[1].loser_next_match_id = third_place.id
        sf[1].loser_next_match_slot = 2

    # ── propagate bye winners into round 2 ───────────────
    for m in round_matches[1]:
        if m.is_bye and m.next_match_id:
            nxt = db.query(models.Match).filter(models.Match.id == m.next_match_id).first()
            if nxt:
                if m.next_match_slot == 1:
                    nxt.participant1_id = m.winner_id
                else:
                    nxt.participant2_id = m.winner_id

    db.commit()


def record_match_result(db: Session, match: models.Match, score1: int, score2: int):
    match.score1 = score1
    match.score2 = score2
    match.winner_id = match.participant1_id if score1 > score2 else match.participant2_id
    match.status = "completed"
    match.completed_at = datetime.utcnow()
    loser_id = match.participant2_id if score1 > score2 else match.participant1_id

    # advance winner
    if match.next_match_id:
        nxt = db.query(models.Match).filter(models.Match.id == match.next_match_id).first()
        if nxt:
            if match.next_match_slot == 1:
                nxt.participant1_id = match.winner_id
            else:
                nxt.participant2_id = match.winner_id

    # advance loser to 3rd place
    if match.loser_next_match_id:
        nxt = db.query(models.Match).filter(models.Match.id == match.loser_next_match_id).first()
        if nxt:
            if match.loser_next_match_slot == 1:
                nxt.participant1_id = loser_id
            else:
                nxt.participant2_id = loser_id

    db.commit()


def build_bracket_context(db: Session, tournament: models.Tournament) -> dict:
    matches = (
        db.query(models.Match)
        .filter(models.Match.tournament_id == tournament.id)
        .order_by(models.Match.round, models.Match.match_in_round)
        .all()
    )
    rounds_raw: dict[int, list] = defaultdict(list)
    third_place = None
    for m in matches:
        if m.is_third_place:
            third_place = enrich_match(db, m, tournament.type)
        else:
            rounds_raw[m.round].append(enrich_match(db, m, tournament.type))

    total_rounds = max(rounds_raw.keys()) if rounds_raw else 0
    rounds = [
        {
            "num": r,
            "label": get_round_label(r, total_rounds),
            "matches": rounds_raw[r],
        }
        for r in sorted(rounds_raw.keys())
    ]

    # determine champion (winner of final match)
    champion = None
    if rounds:
        final_matches = [m for m in rounds[-1]["matches"]]
        if final_matches and final_matches[0]["winner"]:
            champion = final_matches[0]["winner"]

    # medals: top 3
    medals = {}
    if champion:
        medals[champion["id"]] = "gold"
    if third_place and third_place["winner"]:
        medals[third_place["winner"]["id"]] = "bronze"
        # silver = final loser
        if final_matches:
            fm = final_matches[0]
            if fm["winner"] and fm["p1"] and fm["p2"]:
                loser = fm["p2"] if fm["winner"]["id"] == fm["p1"]["id"] else fm["p1"]
                if loser:
                    medals[loser["id"]] = "silver"

    return {
        "rounds": rounds,
        "third_place": third_place,
        "champion": champion,
        "medals": medals,
    }


def _k_shift_jornadas(ids: list) -> list[list[tuple]]:
    """Descomposición 2-factor para N impar: (N-1)/2 jornadas, cada jugador juega 2 por jornada."""
    N = len(ids)
    jornadas = []
    for k in range(1, N // 2 + 1):
        jornada = []
        seen: set = set()
        for i in range(N):
            j = (i + k) % N
            pair = (min(i, j), max(i, j))
            if pair not in seen:
                seen.add(pair)
                jornada.append((ids[pair[0]], ids[pair[1]]))
        jornadas.append(jornada)
    return jornadas


def _circle_jornadas(ids: list) -> list[list[tuple]]:
    """Método círculo agrupando 2 rondas por jornada para N par."""
    N = len(ids)
    rotating = list(ids[1:])
    rounds = []
    for _ in range(N - 1):
        full = [ids[0]] + rotating
        rounds.append([(full[i], full[N - 1 - i]) for i in range(N // 2)])
        rotating = [rotating[-1]] + rotating[:-1]
    jornadas = []
    for i in range(0, len(rounds), 2):
        jornada: list[tuple] = []
        for r in rounds[i:i + 2]:
            jornada.extend(r)
        jornadas.append(jornada)
    return jornadas


def create_league_schedule(
    db: Session,
    league_id: int,
    participant_ids: list[int],
    double_rr: bool = False,
    matches_per_jornada: int = 1,
):
    if matches_per_jornada == 1:
        # Comportamiento original: todos los partidos en jornada 1 (ida) y 2 (vuelta)
        pairs_ida = list(combinations(participant_ids, 2))
        all_pairs = pairs_ida + [(b, a) for a, b in pairs_ida] if double_rr else pairs_ida
        n_ida = len(pairs_ida)
        for i, (p1, p2) in enumerate(all_pairs):
            leg = 2 if double_rr and i >= n_ida else 1
            db.add(models.Match(
                league_id=league_id,
                round=leg,
                match_in_round=i + 1,
                participant1_id=p1,
                participant2_id=p2,
                status="pending",
            ))
    else:
        N = len(participant_ids)
        jornadas_ida = _k_shift_jornadas(participant_ids) if N % 2 == 1 else _circle_jornadas(participant_ids)
        J = len(jornadas_ida)
        match_num = 1
        for jornada_idx, pairs in enumerate(jornadas_ida):
            rnd = jornada_idx + 1
            for p1, p2 in pairs:
                db.add(models.Match(
                    league_id=league_id,
                    round=rnd,
                    match_in_round=match_num,
                    participant1_id=p1,
                    participant2_id=p2,
                    status="pending",
                ))
                match_num += 1
        if double_rr:
            for jornada_idx, pairs in enumerate(jornadas_ida):
                rnd = J + jornada_idx + 1
                for p1, p2 in pairs:
                    db.add(models.Match(
                        league_id=league_id,
                        round=rnd,
                        match_in_round=match_num,
                        participant1_id=p2,
                        participant2_id=p1,
                        status="pending",
                    ))
                    match_num += 1
    db.commit()


def calculate_standings(db: Session, league_id: int, participant_ids: list[int], p_type: str) -> list:
    matches = (
        db.query(models.Match)
        .filter(models.Match.league_id == league_id, models.Match.status == "completed")
        .all()
    )
    stats: dict[int, dict] = {
        pid: {"wins": 0, "losses": 0, "sets_won": 0, "sets_lost": 0}
        for pid in participant_ids
    }
    for m in matches:
        p1, p2 = m.participant1_id, m.participant2_id
        if p1 in stats and p2 in stats:
            stats[p1]["sets_won"] += m.score1
            stats[p1]["sets_lost"] += m.score2
            stats[p2]["sets_won"] += m.score2
            stats[p2]["sets_lost"] += m.score1
            if m.score1 > m.score2:
                stats[p1]["wins"] += 1
                stats[p2]["losses"] += 1
            else:
                stats[p2]["wins"] += 1
                stats[p1]["losses"] += 1

    result = []
    for pid, s in stats.items():
        result.append(
            {
                "participant": get_participant_detail(db, pid, p_type),
                "games_played": s["wins"] + s["losses"],
                "wins": s["wins"],
                "losses": s["losses"],
                "points": s["wins"] * 3,
                "sets_won": s["sets_won"],
                "sets_lost": s["sets_lost"],
                "set_diff": s["sets_won"] - s["sets_lost"],
            }
        )
    result.sort(key=lambda x: (-x["points"], -x["set_diff"], -x["sets_won"]))
    return result


# ═════════════════════════════════════════════════════════
#  LEAGUE SHARE (resumen para compartir como imagen)
# ═════════════════════════════════════════════════════════

@app.get("/leagues/{lid}/share", response_class=HTMLResponse)
def league_share(request: Request, lid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg:
        raise HTTPException(404)

    parts = db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid
    ).all()
    participant_ids = [p.participant_id for p in parts]
    standings = calculate_standings(db, lid, participant_ids, lg.type)

    all_matches = (
        db.query(models.Match)
        .filter(models.Match.league_id == lid)
        .order_by(models.Match.round, models.Match.match_in_round)
        .all()
    )

    legs_raw: dict[int, list] = defaultdict(list)
    for m in all_matches:
        legs_raw[m.round].append(m)

    _parts_share = db.query(models.LeagueParticipant).filter(models.LeagueParticipant.league_id == lid).all()
    _N_share = len(_parts_share)
    _mpj_share = lg.matches_per_jornada or 1
    _J_share = _N_share // 2 if _mpj_share == 2 else 1
    def _share_label(rnd: int) -> str:
        if _mpj_share == 1:
            if lg.double_rr:
                return "Jornada de Ida" if rnd == 1 else "Jornada de Vuelta"
            return "Jornada de Ida"
        if lg.double_rr:
            return f"Ida — Jornada {rnd}" if rnd <= _J_share else f"Vuelta — Jornada {rnd - _J_share}"
        return f"Jornada {rnd}"
    schedule_legs = []
    for leg in sorted(legs_raw.keys()):
        raw = legs_raw[leg]
        enriched = [enrich_match(db, m, lg.type) for m in raw]
        schedule_legs.append({
            "leg":     leg,
            "label":   _share_label(leg),
            "done":    [m for m in enriched if m["status"] == "completed"],
            "pending": [m for m in enriched if m["status"] == "pending"],
        })

    from datetime import date
    return templates.TemplateResponse(
        "league_share.html",
        {
            "request":      request,
            "league":       lg,
            "standings":    standings,
            "schedule_legs": schedule_legs,
            "today":        date.today().strftime("%d/%m/%Y"),
        },
    )


# ═════════════════════════════════════════════════════════
#  LOGIN / LOGOUT
# ═════════════════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("admin"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["admin"] = True
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Usuario o contraseña incorrectos"},
        status_code=401,
    )


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ═════════════════════════════════════════════════════════
#  DASHBOARD
# ═════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    players = db.query(models.Player).count()
    teams = db.query(models.Team).count()
    tournaments = db.query(models.Tournament).count()
    leagues = db.query(models.League).count()
    pending_matches = db.query(models.Match).filter(models.Match.status == "pending").count()
    recent_matches = (
        db.query(models.Match)
        .filter(models.Match.status == "completed")
        .order_by(models.Match.completed_at.desc())
        .limit(5)
        .all()
    )
    # enrich recent matches
    enriched = []
    for m in recent_matches:
        context_type = "individual"
        name = ""
        if m.tournament_id:
            t = db.query(models.Tournament).filter(models.Tournament.id == m.tournament_id).first()
            if t:
                context_type = t.type
                name = t.name
        elif m.league_id:
            lg = db.query(models.League).filter(models.League.id == m.league_id).first()
            if lg:
                context_type = lg.type
                name = lg.name
        enriched.append({
            "context": name,
            "p1": get_participant_name(db, m.participant1_id, context_type),
            "p2": get_participant_name(db, m.participant2_id, context_type),
            "score1": m.score1,
            "score2": m.score2,
        })
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "players": players,
            "teams": teams,
            "tournaments": tournaments,
            "leagues": leagues,
            "pending_matches": pending_matches,
            "recent_matches": enriched,
        },
    )


# ═════════════════════════════════════════════════════════
#  PLAYERS
# ═════════════════════════════════════════════════════════

@app.get("/players", response_class=HTMLResponse)
def players_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    players = db.query(models.Player).order_by(models.Player.name).all()
    return templates.TemplateResponse(
        "players.html", {"request": request, "players": players, "msg": msg}
    )


@app.post("/players")
async def create_player(
    name: str = Form(...),
    avatar: UploadFile = File(None),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        return RedirectResponse("/players?msg=Nombre+vacío", status_code=302)
    exists = db.query(models.Player).filter(models.Player.name == name).first()
    if exists:
        return RedirectResponse("/players?msg=Ya+existe+ese+jugador", status_code=302)
    p = models.Player(name=name)
    db.add(p)
    db.flush()  # obtener ID antes de guardar la foto
    filename = await _save_avatar(p.id, avatar)
    if filename:
        p.avatar = filename
    db.commit()
    return RedirectResponse("/players?msg=Jugador+creado", status_code=302)


@app.post("/players/{pid}/avatar")
async def update_player_avatar(pid: int, avatar: UploadFile = File(...), db: Session = Depends(get_db)):
    p = db.query(models.Player).filter(models.Player.id == pid).first()
    if not p:
        return RedirectResponse("/players?msg=Jugador+no+encontrado", status_code=302)
    filename = await _save_avatar(p.id, avatar)
    if filename:
        p.avatar = filename
        db.commit()
    return RedirectResponse("/players?msg=Foto+actualizada", status_code=302)


@app.post("/players/{pid}/delete")
def delete_player(pid: int, db: Session = Depends(get_db)):
    p = db.query(models.Player).filter(models.Player.id == pid).first()
    if p:
        if p.avatar:
            (AVATARS_DIR / p.avatar).unlink(missing_ok=True)
        db.delete(p)
        db.commit()
    return RedirectResponse("/players?msg=Jugador+eliminado", status_code=302)


# ═════════════════════════════════════════════════════════
#  TEAMS
# ═════════════════════════════════════════════════════════

@app.get("/teams", response_class=HTMLResponse)
def teams_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    teams = db.query(models.Team).order_by(models.Team.name).all()
    players = db.query(models.Player).order_by(models.Player.name).all()
    return templates.TemplateResponse(
        "teams.html", {"request": request, "teams": teams, "players": players, "msg": msg}
    )


@app.post("/teams")
def create_team(
    name: str = Form(...),
    player1_id: int = Form(...),
    player2_id: int = Form(...),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name or player1_id == player2_id:
        return RedirectResponse("/teams?msg=Datos+inválidos", status_code=302)
    db.add(models.Team(name=name, player1_id=player1_id, player2_id=player2_id))
    db.commit()
    return RedirectResponse("/teams?msg=Equipo+creado", status_code=302)


@app.post("/teams/{tid}/delete")
def delete_team(tid: int, db: Session = Depends(get_db)):
    t = db.query(models.Team).filter(models.Team.id == tid).first()
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse("/teams?msg=Equipo+eliminado", status_code=302)


# ═════════════════════════════════════════════════════════
#  TOURNAMENTS
# ═════════════════════════════════════════════════════════

@app.get("/tournaments", response_class=HTMLResponse)
def tournaments_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    tournaments = db.query(models.Tournament).order_by(models.Tournament.created_at.desc()).all()
    return templates.TemplateResponse(
        "tournaments.html", {"request": request, "tournaments": tournaments, "msg": msg}
    )


@app.post("/tournaments")
def create_tournament(
    name: str = Form(...),
    type: str = Form(...),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if type not in ("individual", "doubles"):
        return RedirectResponse("/tournaments?msg=Tipo+inválido", status_code=302)
    db.add(models.Tournament(name=name, type=type))
    db.commit()
    return RedirectResponse("/tournaments?msg=Torneo+creado", status_code=302)


@app.post("/tournaments/{tid}/delete")
def delete_tournament(tid: int, db: Session = Depends(get_db)):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if not t:
        return RedirectResponse("/tournaments", status_code=302)
    db.query(models.Match).filter(models.Match.tournament_id == tid).delete()
    db.query(models.TournamentParticipant).filter(
        models.TournamentParticipant.tournament_id == tid
    ).delete()
    db.delete(t)
    db.commit()
    return RedirectResponse("/tournaments?msg=Torneo+eliminado", status_code=302)


@app.get("/tournaments/{tid}", response_class=HTMLResponse)
def tournament_detail(request: Request, tid: int, db: Session = Depends(get_db), msg: str = ""):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if not t:
        raise HTTPException(404)

    parts = db.query(models.TournamentParticipant).filter(
        models.TournamentParticipant.tournament_id == tid
    ).all()
    participant_ids = [p.participant_id for p in parts]
    participant_details = [get_participant_detail(db, pid, t.type) for pid in participant_ids]

    # available to add
    if t.type == "individual":
        all_opts = db.query(models.Player).order_by(models.Player.name).all()
        available = [
            {"id": p.id, "label": p.name}
            for p in all_opts
            if p.id not in participant_ids
        ]
    else:
        all_opts = db.query(models.Team).order_by(models.Team.name).all()
        available = [
            {"id": tm.id, "label": f"{tm.name} ({tm.player1.name} / {tm.player2.name})"}
            for tm in all_opts
            if tm.id not in participant_ids
        ]

    bracket = None
    if t.status in ("active", "completed"):
        bracket = build_bracket_context(db, t)

    return templates.TemplateResponse(
        "tournament_detail.html",
        {
            "request": request,
            "tournament": t,
            "participants": participant_details,
            "participant_ids": participant_ids,
            "available": available,
            "bracket": bracket,
            "msg": msg,
        },
    )


@app.post("/tournaments/{tid}/participants")
def add_tournament_participant(tid: int, participant_id: int = Form(...), db: Session = Depends(get_db)):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if not t or t.status != "draft":
        return RedirectResponse(f"/tournaments/{tid}?msg=No+se+puede+modificar", status_code=302)
    exists = db.query(models.TournamentParticipant).filter(
        models.TournamentParticipant.tournament_id == tid,
        models.TournamentParticipant.participant_id == participant_id,
    ).first()
    if not exists:
        db.add(models.TournamentParticipant(tournament_id=tid, participant_id=participant_id))
        db.commit()
    return RedirectResponse(f"/tournaments/{tid}?msg=Participante+agregado", status_code=302)


@app.post("/tournaments/{tid}/participants/{pid}/remove")
def remove_tournament_participant(tid: int, pid: int, db: Session = Depends(get_db)):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if not t or t.status != "draft":
        return RedirectResponse(f"/tournaments/{tid}", status_code=302)
    db.query(models.TournamentParticipant).filter(
        models.TournamentParticipant.tournament_id == tid,
        models.TournamentParticipant.participant_id == pid,
    ).delete()
    db.commit()
    return RedirectResponse(f"/tournaments/{tid}?msg=Participante+removido", status_code=302)


@app.post("/tournaments/{tid}/start")
def start_tournament(tid: int, db: Session = Depends(get_db)):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if not t or t.status != "draft":
        return RedirectResponse(f"/tournaments/{tid}?msg=Ya+iniciado", status_code=302)
    parts = db.query(models.TournamentParticipant).filter(
        models.TournamentParticipant.tournament_id == tid
    ).all()
    if len(parts) < 2:
        return RedirectResponse(f"/tournaments/{tid}?msg=Mínimo+2+participantes", status_code=302)
    create_bracket(db, tid, [p.participant_id for p in parts])
    t.status = "active"
    db.commit()
    return RedirectResponse(f"/tournaments/{tid}?msg=Torneo+iniciado", status_code=302)


@app.post("/tournaments/{tid}/complete")
def complete_tournament(tid: int, db: Session = Depends(get_db)):
    t = db.query(models.Tournament).filter(models.Tournament.id == tid).first()
    if t:
        t.status = "completed"
        db.commit()
    return RedirectResponse(f"/tournaments/{tid}?msg=Torneo+completado", status_code=302)


# ═════════════════════════════════════════════════════════
#  LEAGUES
# ═════════════════════════════════════════════════════════

@app.get("/leagues", response_class=HTMLResponse)
def leagues_list(request: Request, db: Session = Depends(get_db), msg: str = ""):
    leagues = db.query(models.League).order_by(models.League.created_at.desc()).all()
    return templates.TemplateResponse(
        "leagues.html", {"request": request, "leagues": leagues, "msg": msg}
    )


@app.post("/leagues")
def create_league(
    name: str = Form(...),
    type: str = Form(...),
    double_rr: str = Form(default=""),
    matches_per_jornada: str = Form(default="1"),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if type not in ("individual", "doubles"):
        return RedirectResponse("/leagues?msg=Tipo+inválido", status_code=302)
    mpj = 2 if matches_per_jornada == "2" else 1
    db.add(models.League(name=name, type=type, double_rr=bool(double_rr), matches_per_jornada=mpj))
    db.commit()
    return RedirectResponse("/leagues?msg=Liga+creada", status_code=302)


@app.post("/leagues/{lid}/rename")
def rename_league(lid: int, name: str = Form(...), db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if lg and name.strip():
        lg.name = name.strip()
        db.commit()
    return RedirectResponse(f"/leagues/{lid}?msg=Nombre+actualizado", status_code=302)


@app.post("/teams/{tid}/rename")
def rename_team(tid: int, name: str = Form(...), db: Session = Depends(get_db)):
    t = db.query(models.Team).filter(models.Team.id == tid).first()
    back = "/teams"
    if t and name.strip():
        # buscar de qué liga viene para redirigir ahí
        lp = db.query(models.LeagueParticipant).filter(models.LeagueParticipant.participant_id == tid).first()
        if lp:
            back = f"/leagues/{lp.league_id}"
        t.name = name.strip()
        db.commit()
    return RedirectResponse(f"{back}?msg=Nombre+del+equipo+actualizado", status_code=302)


@app.post("/leagues/{lid}/delete")
def delete_league(lid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg:
        return RedirectResponse("/leagues", status_code=302)
    db.query(models.Match).filter(models.Match.league_id == lid).delete()
    db.query(models.LeagueParticipant).filter(models.LeagueParticipant.league_id == lid).delete()
    db.delete(lg)
    db.commit()
    return RedirectResponse("/leagues?msg=Liga+eliminada", status_code=302)


@app.get("/leagues/{lid}", response_class=HTMLResponse)
def league_detail(request: Request, lid: int, db: Session = Depends(get_db), msg: str = ""):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg:
        raise HTTPException(404)

    parts = db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid
    ).all()
    participant_ids = [p.participant_id for p in parts]

    if lg.type == "individual":
        all_opts = db.query(models.Player).order_by(models.Player.name).all()
        available = [
            {"id": p.id, "label": p.name}
            for p in all_opts
            if p.id not in participant_ids
        ]
    else:
        all_opts = db.query(models.Team).order_by(models.Team.name).all()
        available = [
            {"id": tm.id, "label": f"{tm.name} ({tm.player1.name} / {tm.player2.name})"}
            for tm in all_opts
            if tm.id not in participant_ids
        ]

    standings = None
    schedule_legs = []
    total_matches = 0
    completed_matches = 0
    if lg.status in ("active", "completed"):
        standings = calculate_standings(db, lid, participant_ids, lg.type)
        all_matches = (
            db.query(models.Match)
            .filter(models.Match.league_id == lid)
            .order_by(models.Match.round, models.Match.match_in_round)
            .all()
        )
        total_matches = len(all_matches)
        completed_matches = sum(1 for m in all_matches if m.status == "completed")
        legs_raw: dict[int, list] = defaultdict(list)
        for m in all_matches:
            legs_raw[m.round].append(m)
        mpj = lg.matches_per_jornada or 1
        N = len(participant_ids)
        J = N // 2 if mpj == 2 else 1
        def _jornada_label(rnd: int) -> str:
            if mpj == 1:
                if lg.double_rr:
                    return "Jornada de Ida" if rnd == 1 else "Jornada de Vuelta"
                return "Jornada de Ida"
            if lg.double_rr:
                return f"Ida — Jornada {rnd}" if rnd <= J else f"Vuelta — Jornada {rnd - J}"
            return f"Jornada {rnd}"
        schedule_legs = []
        for leg in sorted(legs_raw.keys()):
            raw = legs_raw[leg]
            enriched = [enrich_match(db, m, lg.type) for m in raw]
            all_done   = all(m.status == "completed" for m in raw)
            leg_locked = any(m.locked for m in raw)
            schedule_legs.append({
                "leg":     leg,
                "label":   _jornada_label(leg),
                "matches": enriched,
                "locked":  leg_locked,
                "all_done": all_done,
            })

    participant_details = [get_participant_detail(db, pid, lg.type) for pid in participant_ids]

    return templates.TemplateResponse(
        "league_detail.html",
        {
            "request": request,
            "league": lg,
            "participants": participant_details,
            "participant_ids": participant_ids,
            "available": available,
            "standings": standings,
            "schedule_legs": schedule_legs,
            "total_matches": total_matches,
            "completed_matches": completed_matches,
            "pending_matches": total_matches - completed_matches,
            "msg": msg,
        },
    )


@app.post("/leagues/{lid}/participants")
def add_league_participant(lid: int, participant_id: int = Form(...), db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg or lg.status != "active":
        return RedirectResponse(f"/leagues/{lid}?msg=No+se+puede+modificar", status_code=302)
    # only allow adding before schedule is generated
    has_matches = db.query(models.Match).filter(models.Match.league_id == lid).first()
    if has_matches:
        return RedirectResponse(f"/leagues/{lid}?msg=Liga+ya+iniciada", status_code=302)
    exists = db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid,
        models.LeagueParticipant.participant_id == participant_id,
    ).first()
    if not exists:
        db.add(models.LeagueParticipant(league_id=lid, participant_id=participant_id))
        db.commit()
    return RedirectResponse(f"/leagues/{lid}?msg=Participante+agregado", status_code=302)


@app.post("/leagues/{lid}/participants/bulk")
async def add_league_participants_bulk(lid: int, request: Request, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg or lg.status != "active":
        return RedirectResponse(f"/leagues/{lid}?msg=No+se+puede+modificar", status_code=302)
    has_matches = db.query(models.Match).filter(models.Match.league_id == lid).first()
    if has_matches:
        return RedirectResponse(f"/leagues/{lid}?msg=Liga+ya+iniciada", status_code=302)
    form = await request.form()
    ids = [int(v) for v in form.getlist("participant_id")]
    added = 0
    for pid in ids:
        exists = db.query(models.LeagueParticipant).filter(
            models.LeagueParticipant.league_id == lid,
            models.LeagueParticipant.participant_id == pid,
        ).first()
        if not exists:
            db.add(models.LeagueParticipant(league_id=lid, participant_id=pid))
            added += 1
    db.commit()
    return RedirectResponse(f"/leagues/{lid}?msg={added}+participantes+agregados", status_code=302)


@app.post("/leagues/{lid}/participants/{pid}/remove")
def remove_league_participant(lid: int, pid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    has_matches = db.query(models.Match).filter(models.Match.league_id == lid).first()
    if not lg or has_matches:
        return RedirectResponse(f"/leagues/{lid}", status_code=302)
    db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid,
        models.LeagueParticipant.participant_id == pid,
    ).delete()
    db.commit()
    return RedirectResponse(f"/leagues/{lid}?msg=Participante+removido", status_code=302)


@app.post("/leagues/{lid}/start")
def start_league(lid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg:
        return RedirectResponse(f"/leagues/{lid}", status_code=302)
    has_matches = db.query(models.Match).filter(models.Match.league_id == lid).first()
    if has_matches:
        return RedirectResponse(f"/leagues/{lid}?msg=Ya+iniciada", status_code=302)
    parts = db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid
    ).all()
    if len(parts) < 2:
        return RedirectResponse(f"/leagues/{lid}?msg=Mínimo+2+participantes", status_code=302)
    create_league_schedule(db, lid, [p.participant_id for p in parts], lg.double_rr, lg.matches_per_jornada or 1)
    return RedirectResponse(f"/leagues/{lid}?msg=Liga+iniciada", status_code=302)


@app.post("/leagues/{lid}/complete")
def complete_league(lid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if lg:
        lg.status = "completed"
        db.commit()
    return RedirectResponse(f"/leagues/{lid}?msg=Liga+completada", status_code=302)


# ═════════════════════════════════════════════════════════
#  MATCHES (score recording)
# ═════════════════════════════════════════════════════════

@app.post("/matches/{mid}/score")
def record_score(
    mid: int,
    score1: int = Form(...),
    score2: int = Form(...),
    db: Session = Depends(get_db),
):
    m = db.query(models.Match).filter(models.Match.id == mid).first()
    if not m:
        return RedirectResponse("/", status_code=302)

    back = f"/tournaments/{m.tournament_id}" if m.tournament_id else f"/leagues/{m.league_id}"

    if m.locked:
        return RedirectResponse(f"{back}?msg=Jornada+bloqueada,+no+se+puede+editar", status_code=302)

    # Torneos: no permiten empate ni editar completados
    if m.tournament_id:
        if score1 == score2:
            return RedirectResponse(f"{back}?msg=No+puede+haber+empate+en+torneo", status_code=302)
        if m.status == "completed":
            return RedirectResponse(f"{back}?msg=No+se+puede+editar+partidos+de+torneo", status_code=302)

    was_pending = m.status == "pending"
    m.score1 = score1
    m.score2 = score2

    # 0-0 en liga = anular resultado (queda pendiente sin ganador)
    if score1 == 0 and score2 == 0 and m.league_id:
        m.winner_id = None
        m.status = "pending"
        m.completed_at = None
    else:
        m.winner_id = m.participant1_id if score1 > score2 else m.participant2_id
        m.status = "completed"
        m.completed_at = datetime.utcnow()

    # Propagar bracket solo si es torneo y era pendiente
    if m.tournament_id and was_pending:
        loser_id = m.participant2_id if score1 > score2 else m.participant1_id
        if m.next_match_id:
            nxt = db.query(models.Match).filter(models.Match.id == m.next_match_id).first()
            if nxt:
                if m.next_match_slot == 1: nxt.participant1_id = m.winner_id
                else: nxt.participant2_id = m.winner_id
        if m.loser_next_match_id:
            nxt = db.query(models.Match).filter(models.Match.id == m.loser_next_match_id).first()
            if nxt:
                if m.loser_next_match_slot == 1: nxt.participant1_id = loser_id
                else: nxt.participant2_id = loser_id

    db.commit()
    return RedirectResponse(f"{back}?msg=Resultado+registrado", status_code=302)


@app.post("/leagues/{lid}/rounds/{round_num}/lock")
def lock_league_round(lid: int, round_num: int, db: Session = Depends(get_db)):
    db.query(models.Match).filter(
        models.Match.league_id == lid,
        models.Match.round == round_num,
    ).update({"locked": True})
    db.commit()
    label = "Ida" if round_num == 1 else "Vuelta"
    return RedirectResponse(f"/leagues/{lid}?msg=Jornada+de+{label}+bloqueada", status_code=302)


# ═════════════════════════════════════════════════════════
#  CUADRANGULAR (torneo eliminatorio desde standings de liga)
# ═════════════════════════════════════════════════════════

@app.post("/leagues/{lid}/cuadrangular")
def create_cuadrangular(lid: int, db: Session = Depends(get_db)):
    lg = db.query(models.League).filter(models.League.id == lid).first()
    if not lg or lg.status != "completed":
        return RedirectResponse(f"/leagues/{lid}?msg=La+liga+debe+estar+completada", status_code=302)

    parts = db.query(models.LeagueParticipant).filter(
        models.LeagueParticipant.league_id == lid
    ).all()
    participant_ids = [p.participant_id for p in parts]
    standings = calculate_standings(db, lid, participant_ids, lg.type)

    if lg.type == "individual":
        # Top 8; si hay entre 4 y 7 usar los que haya (mínimo 4)
        top = [s["participant"] for s in standings]
        n = min(len(top), 8)
        if n < 4:
            return RedirectResponse(
                f"/leagues/{lid}?msg=Necesitas+al+menos+4+clasificados", status_code=302
            )
        top = top[:n]
        # Seedeo: 1v4, 2v3 en la primera mitad; 5v8, 6v7 en la segunda
        # bracket order: [m1_p1, m1_p2, m2_p1, m2_p2, ...]
        if n >= 8:
            seeded = [
                top[0], top[3], top[1], top[2],
                top[4], top[7], top[5], top[6],
            ]
        else:  # 4–7 → solo primera mitad con los que haya
            first = top[:4]
            seeded = [first[0], first[3], first[1], first[2]]
    else:
        # Duplas: solo top 4
        top = [s["participant"] for s in standings[:4]]
        if len(top) < 2:
            return RedirectResponse(
                f"/leagues/{lid}?msg=Necesitas+al+menos+2+equipos", status_code=302
            )
        if len(top) >= 4:
            seeded = [top[0], top[3], top[1], top[2]]
        else:
            seeded = top

    seeded_ids = [p["id"] for p in seeded]

    # Crear torneo
    t = models.Tournament(name=f"Cuadrangular — {lg.name}", type=lg.type, status="active")
    db.add(t)
    db.commit()
    db.refresh(t)

    for pid in seeded_ids:
        db.add(models.TournamentParticipant(tournament_id=t.id, participant_id=pid))
    db.commit()

    create_bracket(db, t.id, seeded_ids)

    return RedirectResponse(f"/tournaments/{t.id}?msg=Cuadrangular+creado", status_code=302)


@app.get("/health")
def health_check():
    return {"status": "ok"}
