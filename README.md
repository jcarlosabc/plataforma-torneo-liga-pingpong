<div align="center">
  <img src="Captura de pantalla 2026-04-17 135410.png" alt="Mini Liga de Ping Pong en el Trabajo" width="180"/>

  # Mini Liga de Ping Pong en el Trabajo

  **Plataforma web para gestionar torneos y ligas de ping pong — individual o dobles**

  ![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
  ![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi)
  ![SQLite](https://img.shields.io/badge/SQLite-3-003B57?style=flat-square&logo=sqlite)
  ![License](https://img.shields.io/badge/licencia-MIT-green?style=flat-square)

</div>

---

## Descripcion

Aplicacion web construida con **FastAPI + SQLite + Jinja2** (server-side rendering, sin frameworks de frontend).
Permite organizar torneos de eliminacion directa y ligas round-robin, registrar resultados partido a partido y compartir tablas de posiciones en tiempo real.

---

## Requisitos

| Herramienta | Version minima |
|-------------|---------------|
| Python      | 3.10+         |
| pip         | ultima estable |

---

## Instalacion

```bash
# 1. Clonar el repositorio
git clone <url-del-repo>
cd plataforma-torneo-liga-pingpong

# 2. Crear y activar entorno virtual
python -m venv venv

# Windows
venv\Scripts\activate
# Mac / Linux
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Uso

```bash
# Iniciar el servidor en modo desarrollo
uvicorn main:app --reload
```

Abrir en el navegador: [http://localhost:8000](http://localhost:8000)

> `--reload` reinicia el servidor automaticamente al detectar cambios en el codigo.

### Cargar datos de ejemplo

```bash
python seed_liga.py
```

---

## Funcionalidades

| Modulo       | Descripcion |
|--------------|-------------|
| **Jugadores** | Alta y listado de jugadores |
| **Equipos**   | Crear equipos de dobles (2 jugadores por equipo) |
| **Torneos**   | Eliminacion directa — bracket automatico con soporte de BYEs |
| **Ligas**     | Round-robin ida simple o ida y vuelta, tabla de posiciones en vivo |
| **Resultados**| Carga de scores partido a partido, bloqueo automatico al completar |

---

## Base de datos

SQLite — el archivo `ping_pong.db` se genera automaticamente en la primera ejecucion.
No requiere configuracion adicional.

---

## Estructura del proyecto

```
plataforma-torneo-liga-pingpong/
├── main.py              # Rutas y logica principal (FastAPI)
├── models.py            # Modelos SQLAlchemy (Player, Team, Tournament, League, Match)
├── database.py          # Configuracion de la base de datos SQLite
├── seed_liga.py         # Script para poblar datos de ejemplo
├── requirements.txt     # Dependencias Python
├── ping_pong.db         # Base de datos SQLite (generada automaticamente)
└── templates/           # Templates HTML (Jinja2)
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

<div align="center">
  Hecho con dedicacion para la comunidad de ping pong en el trabajo
</div>
