# UdeSA-X Users API

Microservicio backend responsable de la gestión de identidades, registro de usuarios, edición de perfiles, inicio de sesión (incluyendo Social Login) y seguridad.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async con asyncpg, PostgreSQL y Redis. Gestión de dependencias con uv, linting con Ruff.

## Levantarlo en desarrollo

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

Levanta el servicio junto con PostgreSQL y Redis. Cuando los tres estén arriba:

```bash
curl http://localhost:8000/healthcheck
```

Responde `200` con `{"status": "ok", ...}` si ambas dependencias contestan, y `503` con el detalle de cuál falló si alguna no. Es el mismo endpoint que consume el `readinessProbe` de Kubernetes: un `503` saca al pod de rotación en lugar de mandarle tráfico que va a fallar.

La documentación interactiva de la API queda en `http://localhost:8000/docs`.

## Correr los tests

```bash
uv sync
uv run pytest tests/unit
```

Los de integración necesitan las dependencias reales levantadas:

```bash
docker compose -f docker/docker-compose.dev.yml up -d postgres redis
DATABASE_URL=postgresql+asyncpg://users:users@localhost:5432/users \
REDIS_URL=redis://localhost:6379/0 \
uv run pytest tests/integration
```

Sin esas variables los de integración se saltean, para que la suite corra en cualquier máquina.

## Lint

```bash
uv run ruff check .
uv run ruff format --check .
```

## Estructura

```text
src/users_api/
├── config.py   # configuración leída del entorno
├── health.py   # verificación de dependencias
└── main.py     # aplicación FastAPI
tests/
├── unit/          # sin dependencias externas
└── integration/   # contra PostgreSQL y Redis reales
docker/
├── Dockerfile              # multi-stage sobre python:3.13-slim
└── docker-compose.dev.yml  # servicio, PostgreSQL y Redis
```

## Code Guidelines (Reglas del Equipo)
Para mantener la calidad y consistencia del código, todos los miembros deben seguir estas reglas:
* **Ramas:** Obligatorio usar la convención `feature-[nombre-de-la-funcionalidad]` o `fix-[fix-a-realizar]`. Toda rama se integra a `main`.
* **Issues:** Todas las ramas deben tener un issue asociado con la información necesaria para implementar la tarea.
* **Etiquetas (Labels):** Los issues deben clasificarse usando `feature`, `tech debt`, `spike`, o `bug`.
* **Pull Requests (PR):** Las descripciones de los PR deben redactarse en **español**.
* **Idioma del código:** En inglés todo lo que vive dentro de un archivo de código (variables, funciones, clases, tablas, comentarios y docstrings) y los nombres de los archivos y carpetas de código. En español la documentación, los mensajes de commit y las descripciones de PR.
* **Commits (Opcional):** Recomendamos usar la convención de [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

La versión completa y vigente de estas reglas vive en [`CONVENCIONES.md`](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/CONVENCIONES.md) de `udesa-x-platform`; ante cualquier diferencia, manda ese archivo. El punto de entrada para trabajar en este repo, con o sin agente, es su `AGENTS.md`.
