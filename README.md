# Ping Pong Tournament

Aplicación web para gestionar torneos y ligas de ping pong — individual o dobles.
Construida con FastAPI + SQLite + Jinja2 (sin frontend framework, todo server-side).

---

## Requisitos

- Python 3.10+
- pip

---

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv venv

# 2. Activar entorno virtual
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Correr el proyecto

```bash
uvicorn main:app --reload
```

Luego abrir en el navegador: [http://localhost:8000](http://localhost:8000)

> `--reload` reinicia el servidor automáticamente al guardar cambios en el código.

---

## Base de datos

SQLite — el archivo `ping_pong.db` se crea automáticamente en la primera ejecución.
No requiere ninguna configuración adicional.

### Cargar datos de ejemplo (liga)
uvicorn main:app --reload
```bash
python seed_liga.py
```

---

## Estructura

```
ping-pong-tournament/
├── main.py            # Rutas y lógica de la app (FastAPI)
├── models.py          # Modelos SQLAlchemy (Player, Team, Tournament, League, Match)
├── database.py        # Configuración de la base de datos SQLite
├── seed_liga.py       # Script para poblar datos de ejemplo
├── requirements.txt   # Dependencias Python
├── ping_pong.db       # Base de datos SQLite (generada automáticamente)
└── templates/         # Templates HTML (Jinja2)
    ├── base.html
    ├── dashboard.html
    ├── players.html
    ├── teams.html
    ├── tournaments.html
    ├── tournament_detail.html
    ├── leagues.html
    ├── league_detail.html
    └── league_share.html
```

---

## Funcionalidades

- **Jugadores** — alta y listado de jugadores
- **Equipos** — crear equipos de dobles (2 jugadores por equipo)
- **Torneos** — formato eliminación directa (individual o dobles), con bracket automático y soporte de BYEs
- **Ligas** — formato todos contra todos (ida simple o ida y vuelta), tabla de posiciones en tiempo real
- **Resultados** — cargar scores partido a partido, bloqueo automático al completar
