# AGENTS.md - udesa-x-<servicio>

<!-- INICIO BLOQUE PROPIO - completado en cada servicio -->

Identidad, perfiles y administradores de UdeSA-X: registro, login/logout, JWT, recuperación de contraseña y perfiles. No manda emails: publica los eventos de cuenta por RabbitMQ (outbox) y `notifications-api` los envía. Cubre E1-H1 a H14, más E5-H1, E5-H2, E5-H6 y E5-H9.

## Stack y herramientas

- Lenguaje y runtime: Python 3.13 / FastAPI, Uvicorn
- Gestor de paquetes: uv
- Persistencia y migraciones: PostgreSQL (SQLAlchemy 2 async con asyncpg) / Alembic
- Cache y estado efímero: Redis (revocación de JWT, lockout de intentos fallidos) — no Valkey, ver `ARQUITECTURA.md`
- Mensajería: RabbitMQ con aio-pika (publicación con outbox y consumo de auditoría)

## Checks y comandos

No hay `scripts/lint.sh` ni `scripts/test.sh` en este repo todavía: los comandos son los que corre el CI (`.github/workflows/ci.yml` vía el reusable `ci-python.yml` de platform).

```bash
uv run ruff check .                                    # Lint
uv run ruff format --check .                           # Formato
uv run pytest tests/unit --cov=src --cov-report=term   # Tests unitarios con cobertura
uv run pytest --cov=src --cov-report=term              # + tests/integration, requiere DATABASE_URL, REDIS_URL y RABBITMQ_URL
                                                        # (levantar con docker/docker-compose.dev.yml)
```

**Gate de cobertura del 85%: arranca en S3.** Hasta entonces el CI reporta el porcentaje pero no bloquea el PR (`bloquear-por-cobertura` en `ci-python.yml`).

## Arquitectura y particularidades locales

- El código se organiza por capa, según el ADR-007 de `udesa-x-platform`: `api/` expone las rutas, sus esquemas y el wiring; `app/` tiene el negocio (`models/`, `repositories/`, `services/`, `events.py`); `config/` la configuración; `infrastructure/` las implementaciones agrupadas por tecnología. No se agrupa por feature: las historias de este servicio comparten la entidad `User`, y agruparlas dejaría a una carpeta siendo dueña de ella.
- **La regla que ordena todo: `app/` no importa nada de `api/` ni de `infrastructure/`.** Se verifica leyendo imports. Hoy en `app/` no aparecen las palabras `sqlalchemy`, `redis` ni `fastapi`, y tiene que seguir así.
- Los servicios piden lo que necesitan a través de interfaces. En `app/repositories/` van las de todo lo que almacena estado, sin importar si detrás hay PostgreSQL o Redis; si aparece una interfaz de lo que habla con un tercero, va en `app/clients/` (hoy no hay ninguna: los emails los manda `notifications-api`). Al agregar una capacidad nueva: la interfaz en `app/`, la clase concreta en `infrastructure/`, y el cable en `api/deps.py`, que es el único módulo que conoce las implementaciones.
- Las tablas viven en `infrastructure/database/models.py`, que es lo que importa `migrations/env.py`. Un modelo que no esté ahí hace que `autogenerate` proponga borrar la tabla.
- **Migraciones incrementales.** Hay un deploy real, así que `0001_esquema_actual.py` es la base fija y cada cambio de esquema suma una migración nueva (`0002_...`, `0003_...`, `0004_outbox.py`). Editar una ya aplicada no llega a la base de producción.
- **Los emails no salen de acá: se publican como eventos.** Los servicios de `app/services/` escriben el evento (`app/events.py`) en el outbox con `OutboxRepository`, dentro de la transacción del request; el publicador (`infrastructure/rabbitmq/`, una tarea del `lifespan`) lo manda a RabbitMQ y borra la fila al confirmar el broker. `verification_url` y `token` de los eventos son secretos: nunca se loguea un payload, solo `id` y `type`.
- **Auditoría remota:** consume `admin.action_recorded.v1` de `posts-api`. `api/event_handlers.py` valida el evento y confirma la transacción antes del ACK; el ID del evento deduplica las reentregas en `admin_audit_log`. El consumidor (`infrastructure/rabbitmq/event_consumer.py`) arranca en el `lifespan`, reintenta los fallos transitorios y manda los inválidos a `users-api.dlq` mediante el exchange propio `users-api.dlx`.
- Tests en `tests/unit/` y `tests/integration/`; `tests/conftest.py` aplica las migraciones de Alembic contra la base real y limpia tablas/Redis entre tests (`clean_state`). La suite de integración se salta sola si no hay `DATABASE_URL`/`REDIS_URL`/`RABBITMQ_URL`; el fixture `api` apunta el publicador a un broker inalcanzable para que los eventos queden en el outbox, y los tests del publicador usan el RabbitMQ real.
- **Identificadores de historia (`E1-H13`, `CA.4`, etc.): solo en el nombre de la función de test**, como pide "Trazabilidad de criterios de aceptación" en `CONVENCIONES.md` (formato `test_e1_h13_ca4_...`). No van en código de producción (`src/`) ni en el docstring o los comentarios del propio archivo de test: ahí se explica el porqué de la regla, no su número. Un identificador que se cuela en un comentario de `src/` sobrevive a un refactor de la historia que lo puso; el nombre del test es el único lugar donde vale la pena que quede fijo, porque es lo que se filtra en la defensa.
- `contracts/events/` es una copia de `udesa-x-platform/docs/eventos/` con los eventos que este servicio publica o consume (ADR-017 de platform). No se edita acá: se cambia en platform y se trae con su `scripts/sync-contracts.sh`. El job `Contratos de eventos al dia` del CI falla si la copia difiere. Los tests validan contra estos esquemas los eventos que arma o recibe el servicio.
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
