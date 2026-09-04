# AGENTS.md - udesa-x-<servicio>

<!-- INICIO BLOQUE PROPIO - completado en cada servicio -->

Identidad, perfiles y administradores de UdeSA-X: registro, login/logout, JWT, recuperación de contraseña y perfiles. Cubre E1-H1 a H14, más E5-H1, E5-H2 y E5-H9.

## Stack y herramientas

- Lenguaje y runtime: Python 3.13 / FastAPI, Uvicorn
- Gestor de paquetes: uv
- Persistencia y migraciones: PostgreSQL (SQLAlchemy 2 async con asyncpg) / Alembic
- Cache y estado efímero: Redis (revocación de JWT, lockout de intentos fallidos) — no Valkey, ver `ARQUITECTURA.md`

## Checks y comandos

No hay `scripts/lint.sh` ni `scripts/test.sh` en este repo todavía: los comandos son los que corre el CI (`.github/workflows/ci.yml` vía el reusable `ci-python.yml` de platform).

```bash
uv run ruff check .                                    # Lint
uv run ruff format --check .                           # Formato
uv run pytest tests/unit --cov=src --cov-report=term   # Tests unitarios con cobertura
uv run pytest --cov=src --cov-report=term              # + tests/integration, requiere DATABASE_URL y REDIS_URL
                                                        # (levantar con docker/docker-compose.dev.yml)
```

**Gate de cobertura del 85%: arranca en S3.** Hasta entonces el CI reporta el porcentaje pero no bloquea el PR (`bloquear-por-cobertura` en `ci-python.yml`).

## Arquitectura y particularidades locales

- El código se organiza por capa, según el ADR-007 de `udesa-x-platform`: `api/` expone las rutas, sus esquemas y el wiring; `app/` tiene el negocio (`models/`, `repositories/`, `clients/`, `services/`); `config/` la configuración; `infrastructure/` las implementaciones agrupadas por tecnología. No se agrupa por feature: las historias de este servicio comparten la entidad `User`, y agruparlas dejaría a una carpeta siendo dueña de ella.
- **La regla que ordena todo: `app/` no importa nada de `api/` ni de `infrastructure/`.** Se verifica leyendo imports. Hoy en `app/` no aparecen las palabras `sqlalchemy`, `redis` ni `fastapi`, y tiene que seguir así.
- Los servicios piden lo que necesitan a través de interfaces. En `app/repositories/` van las de todo lo que almacena estado, sin importar si detrás hay PostgreSQL o Redis; en `app/clients/`, las de lo que habla con un tercero. Al agregar una capacidad nueva: la interfaz en `app/`, la clase concreta en `infrastructure/`, y el cable en `api/deps.py`, que es el único módulo que conoce las implementaciones.
- Las tablas viven en `infrastructure/database/models.py`, que es lo que importa `migrations/env.py`. Un modelo que no esté ahí hace que `autogenerate` proponga borrar la tabla.
- Tests en `tests/unit/` y `tests/integration/`; `tests/conftest.py` aplica las migraciones de Alembic contra la base real y limpia tablas/Redis entre tests (`clean_state`). La suite de integración se salta sola si no hay `DATABASE_URL`/`REDIS_URL`.
- Documentación general del sistema: consultar `../udesa-x-platform/docs/` (`ARQUITECTURA.md`, `CONVENCIONES.md`, `PLANIFICACION.md`).

<!-- FIN BLOQUE PROPIO -->

<!-- INICIO BLOQUE COMUN - sincronizado desde udesa-x-platform, no editar la copia local -->

## Reglas del equipo

- **Ramas e issues**: Rama base `main`. Ramas de trabajo `feature-<nombre>` (funcionalidad), `fix-<nombre>` (defecto) o `chore-<nombre>` (mantenimiento y tooling, etiqueta `tech debt`), siempre asociadas a un issue en el mismo repositorio.
- **Idiomas**:
  - Código (`src/`, `tests/`), nombres de archivos, identificadores y comentarios en código: **inglés**.
  - Documentación (`docs/`, `README.md`), mensajes de commit y Pull Requests: **español**.
- **Commits**: Formato Conventional Commits (`feat:`, `fix:`, `docs:`, etc.) con descripción en español.
- **Simplicidad**: Soluciones mínimas y directas para el criterio de aceptación. No introducir librerías, patrones ni abstracciones nuevas sin un ADR aprobado en `docs/adr/`.

## Límites y flujo de trabajo del agente

- El agente inspecciona el repositorio (`git status`, `git diff`), edita archivos en el working tree, ejecuta checks locales y redacta propuestas de commit y PR.
- **El agente nunca commitea, pushea ni abre/aprueba/mergea Pull Requests.** La revisión y confirmación en Git la realiza siempre un integrante del equipo.
- **Sin firmas**: Nunca agregar `Co-Authored-By`, firmas o menciones del agente en commits, PRs ni código.

## Modo de planificación

- Planes extremadamente concisos: priorizar brevedad y concreción por sobre prosa formal.
- Al final de cada plan, incluir la lista de preguntas o dudas pendientes a resolver (si las hay).

## Skills (.agents/skills/)

- `explicar-implementacion`: Genera la explicación detallada del cambio para incluir en la descripción del PR.
- `revisar-pr`: Guía paso a paso para la revisión técnica de Pull Requests.

<!-- FIN BLOQUE COMUN -->
