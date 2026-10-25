# UdeSA-X Users API

Microservicio backend responsable de la gestión de identidades, registro de usuarios, edición de perfiles, inicio de sesión (incluyendo Social Login) y seguridad.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async con asyncpg, PostgreSQL, Redis y RabbitMQ (aio-pika). Gestión de dependencias con uv, linting con Ruff.

## Levantarlo en desarrollo

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

Levanta el servicio junto con PostgreSQL, Redis y RabbitMQ, aplica las migraciones y siembra el primer
superadmin (`admin@udesa.edu.ar` / `Admin1234`, solo para desarrollo). Cuando estén arriba:

```bash
curl http://localhost:8000/healthcheck
```

Responde `200` con `{"status": "ok", ...}` si ambas dependencias contestan, y `503` con el detalle de cuál falló si alguna no. Es el mismo endpoint que consume el `readinessProbe` de Kubernetes: un `503` saca al pod de rotación en lugar de mandarle tráfico que va a fallar.

La documentación interactiva de la API queda en `http://localhost:8000/docs`.

## Endpoints

| Método y ruta | Qué hace |
|---|---|
| `GET /healthcheck` | Verifica PostgreSQL y Redis e informa la versión desplegada |
| `POST /auth/register` | Crea la cuenta y deja en el outbox el evento `user.registered.v1`, con el link de verificación |
| `POST /auth/verify` | Consume el token y valida la cuenta |
| `GET /auth/verify?token=` | Lo mismo, para el link del email: un cliente de correo solo puede abrirlo con `GET` |
| `POST /auth/resend-verification` | Pide un link nuevo cuando el anterior expiró: deja en el outbox `email_verification.requested.v1` |
| `POST /auth/login` | Devuelve el access token y un refresh token que inicia una sesión nueva. El claim `role` lleva el rol real de la cuenta |
| `POST /auth/refresh` | Cuerpo `{"refresh_token": "..."}`. Canjea el refresh token por un access token nuevo y el siguiente refresh token, con la misma forma de respuesta que el login. Un token inválido, vencido o ya revocado responde `401` con el código `invalid-refresh-token` |
| `POST /admin/auth/login` | Login del backoffice, con email. Solo `moderator` y `superadmin`; un usuario común recibe `403`. Tres intentos fallidos bloquean por 30 minutos |
| `POST /admin/users` | Crea un administrador con una contraseña temporal. Solo `superadmin`. La temporal viaja en claro en la respuesta, una única vez |
| `GET /admin/users` | Lista los administradores con el estado de su credencial temporal. Solo `superadmin` |
| `POST /admin/users/{id}/reset-temporary-password` | Genera una temporal nueva para una cuenta que todavía no eligió la suya. Solo `superadmin` |
| `GET /admin/metrics` | Cuentas de la app verificadas y no borradas: activas (`active_users`) y en revisión (`accounts_under_review`). Cualquier administrador; un usuario común recibe `403` |
| `POST /auth/logout` | Revoca el access token activo. Acepta un cuerpo opcional `{"refresh_token": "..."}`: si el token es de la misma cuenta, revoca toda su sesión. Un token desconocido o ajeno se ignora, y el cierre sigue respondiendo `204` |
| `POST /auth/forgot-password` | Pide el código de recuperación, con email o handle: deja en el outbox `password.reset_requested.v1`. El usuario lo pega en la app |
| `POST /auth/reset-password` | Consume el link y cambia la contraseña. Revoca todas las sesiones de la cuenta y todos sus refresh tokens |
| `POST /me/change-password` | Cambia la contraseña sabiendo la actual. Revoca todas las sesiones, la que hizo el pedido incluida, y todos los refresh tokens de la cuenta. Deja en el outbox `password.changed.v1` |
| `GET /me` | Devuelve el perfil de la cuenta autenticada |
| `PATCH /me` | Edita `display_name` y `bio`. Rechaza `email` y `handle`, que no se pueden tocar acá |
| `GET /me/preferences` | Devuelve `profile_visibility` y `feed_language` de la cuenta autenticada |
| `PATCH /me/preferences` | Edita una o las dos preferencias. Cada una es un enum: un valor fuera de lo definido se rechaza con `422` |
| `POST /internal/users/{id}/review` | Pone la cuenta en revisión y revoca todas sus sesiones y todos sus refresh tokens. Fuera de `/api`, así que el gateway no la expone: la llama `posts-api` por la red del cluster ([ADR-011](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-011-denuncias-y-cuenta-en-revision.md)). Exige el header `X-Internal-Token`; sin él o con otro valor responde `401`. Llamarla de nuevo responde `204` y no cambia nada |
| `GET /internal/users/{id}/profile` | Devuelve la parte pública de una cuenta: `id`, `handle`, `display_name`, `bio` y `created_at`, nunca el email. La llama `posts-api` para armar el perfil de otro usuario (E2-H14). Una cuenta inexistente o eliminada responde `404`. Exige el mismo `X-Internal-Token` que la ruta anterior |
| `GET /admin/users/search?q=&cursor=` | Busca cuentas de la app cuyo email o handle contengan `q` (sin distinguir mayúsculas, con `%` y `_` como texto literal). Mínimo 3 caracteres, si no `422`. Veinte por página, de la más nueva a la más vieja, con `next_cursor` para la siguiente. Deja afuera administradores y cuentas borradas. Cualquier administrador (E5-H4) |
| `GET /admin/users/{id}` | Detalle de una cuenta de la app para el backoffice: `email`, `handle`, `display_name`, `status`, `status_reason`, `status_changed_at`, `is_email_verified` y `created_at`. Una cuenta inexistente, borrada o de un administrador responde `404`. Los contadores de seguidores y posts los da `posts-api`. Cualquier administrador (E5-H4) |
| `POST /admin/users/{id}/block` | Bloquea una cuenta de la app con un motivo obligatorio (`{"reason": "..."}`, hasta 500 caracteres sin contar los espacios de los bordes). Sin motivo o en blanco responde `422`. Pasa la cuenta a `suspended`, guarda el motivo y el instante, y revoca todas sus sesiones y todos sus refresh tokens: deja de servir al instante también en `posts-api`. Responde `204`. Bloquearla de nuevo no cambia nada ni pisa el primer motivo. Una cuenta inexistente o borrada responde `404`, y la de un administrador `422`. El dueño ve el mensaje genérico de cuenta suspendida, nunca el motivo. Cualquier administrador (E5-H5) |

Una cuenta en revisión no puede iniciar sesión: el login responde `403` con el código
`account-under-review` y un mensaje propio, distinto del de `account-suspended`. Los tokens que ya
tenía dejan de servir al instante, también en `posts-api`, que lee las mismas marcas de revocación
de Redis ([ADR-014](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-014-revocacion-de-sesiones-en-posts-api.md)).
Salir de revisión le toca al backoffice (`E5-H7`). Una cuenta suspendida no pasa a revisión: la
decisión del administrador pesa más, y su motivo no se pisa.

**Refresh tokens.** El access token dura `ACCESS_TOKEN_MINUTES`; el refresh token mantiene la sesión
abierta hasta `REFRESH_TOKEN_DAYS` sin pedir las credenciales de nuevo. Es opaco y en la base solo
queda su hash SHA-256. Cada canje lo consume y entrega el siguiente de la misma familia (la cadena de
tokens de un login), así que cada dispositivo tiene la suya. Si llega un token que ya se canjeó, se
asume que alguien guardó una copia: se revocan todos los refresh tokens de la cuenta y también sus
access tokens vigentes, y la respuesta es la misma `401 invalid-refresh-token`, sin revelar el
reuso. Cada canje vuelve a revisar la cuenta: suspendida o en revisión responde `403`, con el código
de siempre (`account-suspended`, `account-under-review`). El login del backoffice
(`POST /admin/auth/login`) no entrega refresh token.

Este servicio no manda emails: publica eventos y `notifications-api` manda el correo (ver
[Eventos](#eventos)). En desarrollo, mientras ese servicio no esté corriendo, el link de
verificación se saca del evento que quedó en el outbox:

```bash
docker compose -f docker/docker-compose.dev.yml exec postgres \
  psql -U users -d users -c "SELECT payload->'data'->>'verification_url' FROM outbox ORDER BY created_at DESC LIMIT 1"
```

La documentación interactiva queda en `http://localhost:8000/docs`.

## Configuración

Variables de entorno que lee el servicio, además de `DATABASE_URL`, `REDIS_URL`,
`RABBITMQ_URL` e `INTERNAL_API_TOKEN`. Las cuatro son obligatorias: sin ellas el servicio no arranca.
`INTERNAL_API_TOKEN` es el secreto que comparte con `posts-api` para las rutas de `/internal`, y
tiene que tener el mismo valor en los dos servicios. `RABBITMQ_URL` es la URL AMQP del broker
(`amqp://usuario:clave@host:5672`) y lleva credenciales: es un secreto.

| Variable | Default | Para qué |
|---|---|---|
| `JWT_PRIVATE_KEY` | efímera | Clave Ed25519 en PEM. Sin definir, se genera una por arranque |
| `JWT_ISSUER` | `users-api` | Emisor incluido en el claim `iss` de los tokens |
| `LOG_LEVEL` | `INFO` | Nivel de log |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base de los links de verificación que viajan en los eventos: el host solo, sin `/api` |
| `ACCESS_TOKEN_MINUTES` | `15` | Vida del access token |
| `REFRESH_TOKEN_DAYS` | `7` | Vida del refresh token, y por lo tanto cuánto dura una sesión sin volver a pedir las credenciales |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Bloqueo del login de la app |
| `ADMIN_LOGIN_MAX_ATTEMPTS` / `ADMIN_LOGIN_LOCKOUT_MINUTES` | `3` / `30` | Bloqueo del login del backoffice. Contador independiente del de la app |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | sin definir | Credenciales del primer superadmin, que siembra el comando de abajo |
| `SUPERADMIN_HANDLE` | `@superadmin` | Handle de esa cuenta: la columna es obligatoria y única |
| `CORS_ALLOWED_ORIGINS` | `[]` | Orígenes de browser permitidos, como lista JSON. Vacío bloquea a todos; mobile no lo necesita, el backoffice sí |
| `ADMINISTRATOR_EMAIL_DOMAIN` | sin definir | Dominio al que tiene que pertenecer el correo de un administrador nuevo. Vacío significa sin restricción |
| `OUTBOX_POLL_SECONDS` | `5` | Cada cuánto busca el publicador eventos pendientes por su cuenta. Es la red de seguridad si se pierde el `LISTEN`, y la pausa entre reintentos mientras RabbitMQ está caído |

## Eventos

Los emails de cuenta (verificación, recuperación de contraseña, aviso de cambio) no salen de este
servicio. `users-api` publica un evento por cada uno y `notifications-api` lo consume y manda el
correo ([ADR-010](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-010-proveedor-de-correo.md),
[ADR-017](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-017-forma-y-versionado-de-eventos.md)).
Los esquemas están en `contracts/events/`, copia de `udesa-x-platform` que no se edita acá.

| `type` | Cuándo | `data` |
|---|---|---|
| `user.registered.v1` | `POST /auth/register` crea la cuenta | `user_id`, `email`, `handle`, `verification_url` |
| `email_verification.requested.v1` | `POST /auth/resend-verification` sobre una cuenta sin verificar. No repite `user.registered`: la cuenta no se creó de nuevo | `user_id`, `email`, `verification_url` |
| `password.reset_requested.v1` | `POST /auth/forgot-password` sobre una cuenta que existe y puede entrar | `user_id`, `email`, `token` |
| `password.changed.v1` | `POST /me/change-password` cambia la contraseña | `user_id`, `email` |

Cada evento es un sobre CloudEvents 1.0 (`specversion`, `id`, `source: users-api`, `type`, `time`,
`data`). El `id` es un UUID nuevo y es la clave de idempotencia del consumidor.

**Outbox.** El evento no se publica dentro del request: se inserta en la tabla `outbox` con la
misma sesión, así que se confirma o se revierte junto con el cambio que lo causó. Una cuenta sin su
evento, o un evento de una cuenta que no se creó, no pueden existir. Las filas guardan el sobre
completo en `payload` (`jsonb`).

**Publicador.** Corre como una tarea de asyncio dentro del proceso, arrancada en el `lifespan` y
cancelada al apagar (`infrastructure/rabbitmq/`). Se despierta con `LISTEN outbox` sobre una conexión
asyncpg propia, que dispara el trigger de la tabla en cada INSERT, y además revisa cada
`OUTBOX_POLL_SECONDS` por si el `LISTEN` se perdió. En cada pasada toma hasta 100 filas con
`FOR UPDATE SKIP LOCKED`, las publica en el exchange `udesa-x.events` (`topic`, durable) con la
routing key igual al `type`, y **borra cada fila apenas el broker confirma**. Publica con
`mandatory` y confirms del publicador: si ninguna cola está ligada (por ejemplo, `notifications-api`
nunca arrancó), el broker devuelve el mensaje y esa fila queda pendiente sin frenar a las que vienen
atrás. Si el broker no está, la pasada se corta y lo ya confirmado se guarda; el resto espera a la
siguiente.

La entrega es al menos una vez: si el proceso cae entre la confirmación y el borrado, el evento se
publica de nuevo y el consumidor lo descarta por su `id`.

RabbitMQ caído no tumba nada. La API arranca y responde igual, el publicador reintenta solo y los
eventos esperan en el outbox hasta que el broker vuelva. Mientras tanto no se mandan emails.

`verification_url` y `token` son secretos: ni el publicador ni el servicio los loguean. En los logs
del publicador aparecen solo el `id` y el `type` del evento.

En desarrollo el compose levanta `rabbitmq:4-management-alpine` (usuario `users`, clave `users`),
con la consola de administración en `http://localhost:15672` y los puertos publicados solo en
`127.0.0.1`.

## Despliegue en Kubernetes

Los cuatro manifiestos de `k8s/` usan el namespace `tds-group-3`, según
[ADR-008](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-008-plataforma-de-despliegue.md).
El Deployment tiene una réplica, requests de `100m` / `128Mi` y limits de
`500m` / `512Mi`, dentro de los límites definidos por la cátedra. El rolling update
requiere un slot adicional de pod y cuota para el surge y los Jobs de migración.
Si no alcanza el margen, esperar o liberar capacidad antes del rollout, sin cambiar
automáticamente la estrategia para interrumpir el servicio.

Cada push a `main` que pasa el CI despliega solo, con el job `deploy` de
`.github/workflows/ci.yml`, que llama a `deploy.yml` de `udesa-x-platform`. Ese pipeline
publica la imagen en ECR y reemplaza `${ECR_IMAGE}` por su referencia por digest antes de
aplicar el Deployment. Kubernetes no expande estas variables. Qué hace paso por paso está en
el README de `udesa-x-platform`, sección "Despliegue continuo".

Copiar `k8s/secret.template.yaml` a `k8s/secret.yaml`, ignorado por git, y completar
`DATABASE_URL` (PostgreSQL con `postgresql+asyncpg://`), `REDIS_URL`,
`JWT_PRIVATE_KEY` (PEM Ed25519, usando un bloque YAML `|` para conservar los saltos),
`RABBITMQ_URL` e `INTERNAL_API_TOKEN`. Nunca aplicar la plantilla vacía sobre un Secret real: sobrescribiría sus
valores. El pipeline arma el Secret real con los GitHub Secrets `DATABASE_URL`, `REDIS_URL`,
`RABBITMQ_URL`, `JWT_PRIVATE_KEY` e `INTERNAL_API_TOKEN`; sin alguno de ellos el pipeline corta antes
de tocar el cluster. `envFrom` inyecta las
variables al crear el contenedor: el pipeline pone el hash del ConfigMap y del Secret en el
pod template, así que un cambio solo de configuración también reemplaza los pods. Los integrantes conservan acceso de solo
lectura al cluster.

Las migraciones (`alembic upgrade head`) las corre el pipeline como Job con la misma imagen,
antes del rollout, y si fallan el despliegue se corta con los pods anteriores sirviendo. No
se incluyen Jobs en `k8s/` ni se aplica esa carpeta entera, que incluye la plantilla vacía.
Después de las migraciones, el mismo Job siembra el superadmin (`python -m users_api.seed_superadmin`)
con `SUPERADMIN_EMAIL` y `SUPERADMIN_PASSWORD`, que son GitHub Secrets del repo. Corre en cada
despliegue y desde el segundo no hace nada: encuentra la cuenta.

`PUBLIC_BASE_URL` es el host público solo, sin `/api`: la aplicación agrega
`/api/auth/verify` al construir el link, con el mismo `API_PREFIX` que usan las rutas. `JWT_ISSUER` (`users-api`) configura el claim `iss`
de los tokens emitidos y es validado estrictamente al verificar la firma de tokens recibidos.
Los tokens anteriores sin `iss` dejan de ser válidos; hay que iniciar sesión de nuevo.
La privada debe ser estable en producción y posts debe recibir su pública correspondiente.

El Service es interno (`ClusterIP`, puerto `80` hacia el targetPort nombrado `http` que resuelve
al containerPort `8000`); la entrada externa pasa por el Ingress y el gateway.
Las sondas de Kubernetes utilizan el puerto nombrado `http`:
- `readinessProbe` consulta `/healthcheck`: comprueba PostgreSQL y Redis; un fallo saca
  al pod de rotación sin reiniciarlo.
- `livenessProbe` consulta `/livez`: comprueba únicamente la vitalidad del proceso Python/FastAPI
  sin tocar dependencias externas, evitando reinicios en cascada por caídas transitorias de BD o Redis.
Ambos endpoints quedan fuera del prefijo `/api` y sin autenticación ni rate limiting.
Para validar sin modificar el cluster:

```bash
kubectl apply --dry-run=client -f k8s/
```

El comando requiere kubectl y un contexto con acceso de lectura al API server
para consultar descubrimiento y esquemas, aunque no requiere permisos de escritura.
La validación de la plantilla no acredita que los secretos ni la imagen estén listos.
La aprobación del tutor se gestiona en el PR.

## Primer superadmin

El panel no puede crear al primer administrador porque nadie puede entrar al panel todavía. Se
siembra con un comando que corre antes de arrancar la API; en desarrollo lo dispara el compose,
en producción lo corre el despliegue después de las migraciones, con credenciales propias cargadas
como GitHub Secrets. Para correrlo a mano:

```bash
SUPERADMIN_EMAIL=admin@udesa.edu.ar SUPERADMIN_PASSWORD=Admin1234 uv run python -m users_api.seed_superadmin
```

Es idempotente: si la cuenta existe, no la toca (ni rol ni contraseña) y termina con código `0`.
Sin las dos variables, o con una contraseña que no cumpla la política del registro, termina con
código `2` y no abre conexión. Los administradores siguientes se crean desde el panel (`E5-H1`).

## Migraciones

El esquema se maneja con Alembic. En desarrollo la migración se aplica sola al levantar el
compose; en producción es un job aparte del pipeline de despliegue.

```bash
uv run alembic upgrade head          # aplicar
```

**Incrementales desde el primer deploy.** Mientras no hubo una base con datos vivos, los cambios
de esquema se editaban en `0001_esquema_actual.py`. Con el servicio desplegado, esa migración
quedó como base fija y cada cambio suma una nueva, como `0002_estado_de_cuenta.py`. Editar una
migración ya aplicada no llega a la base de producción: Alembic la da por corrida.

`0003_refresh_tokens.py` crea la tabla `refresh_tokens` (hash del token, familia, vencimiento, uso y
revocación). Es una tabla nueva y no toca datos existentes: quien tenía una sesión abierta la
conserva hasta que venza su access token, y el próximo login le entrega su primer refresh token.

`0004_outbox.py` crea la tabla `outbox` (`id` del evento, `type`, `payload` con el sobre completo y
`created_at`, con índice por `created_at`) y un trigger `AFTER INSERT` que hace
`pg_notify('outbox', id)` para despertar al publicador. Es una tabla nueva: no toca datos existentes.

`0005_motivo_del_estado.py` suma a `users` `status_reason` (texto) y `status_changed_at`
(instante), los dos opcionales: por qué y cuándo cambió el estado por última vez. El bloqueo de un
administrador (`E5-H5`) deja los dos, y la revisión por denuncias (`E3-H5`) solo el instante. Las
cuentas existentes quedan en `NULL`: no hay un motivo verdadero que ponerles.

## Correr los tests

```bash
uv sync
uv run pytest tests/unit
```

Los de integración necesitan las dependencias reales levantadas:

```bash
docker compose -f docker/docker-compose.dev.yml up -d postgres redis rabbitmq
DATABASE_URL=postgresql+asyncpg://users:users@localhost:5432/users \
REDIS_URL=redis://localhost:6379/0 \
RABBITMQ_URL=amqp://users:users@localhost:5672 \
uv run pytest tests/integration
```

Los tests del publicador hablan con el RabbitMQ real: ligan una cola temporal al exchange y
verifican que el mensaje llega con el contrato y que la fila se borra. Los demás tests de
integración apuntan el publicador de la app a un broker inalcanzable, para que los eventos queden
en el outbox y se puedan leer. Sin esas variables los de integración se saltean, para que la suite corra en cualquier máquina.

Los de integración aplican la migración real antes de correr, así que también verifican que el
esquema coincida con los modelos: una columna agregada sin su migración falla acá y no en
producción.

### Como los corre el CI: dentro de la imagen

Lo de arriba corre sobre tu máquina y sirve para iterar. **El CI los corre adentro de la imagen
Docker del servicio**, que es lo que hace que el resultado no dependa de cómo esté armada la
máquina. El `Dockerfile` tiene un stage `test` que suma las dependencias de desarrollo y la
carpeta `tests/` sobre el mismo build que va a producción.

Para reproducirlo hay un servicio en el compose que construye ese stage y lo corre contra
PostgreSQL, Redis y RabbitMQ, esperando a que estén sanos:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm --build tests
```

Ese servicio **no monta el código como volumen** a propósito. Montarlo reemplazaría lo que hay
adentro de la imagen por lo que hay en el disco, y se dejaría de probar el artefacto que
efectivamente se despliega, que es todo el punto de correrlos así.

Adentro del contenedor los nombres de host son `postgres`, `redis` y `rabbitmq`, no `localhost`: ahí
`localhost` es el propio contenedor. El CI usa `--network host` en su lugar, que en los
runners de Linux hace que el contenedor comparta la red de la máquina; en Docker Desktop sobre
Windows o macOS eso no funciona igual.

La suite corre como el usuario `app`, sin privilegios, igual que el servicio en producción.
Correrla como `root` escondería cualquier problema de permisos hasta después de desplegar.

La versión de Python está fijada en `.python-version`. Sin ese archivo, `uv` toma la más nueva
que encuentre y podrías terminar probando en una versión distinta de la que corre en
producción, lo que además hace que el porcentaje de cobertura no coincida con el del CI.

## Lint

```bash
uv run ruff check .
uv run ruff format --check .
```

## Estructura

El código se organiza **por capa**, siguiendo el ADR-007. Cada capa tiene un responsable claro y
el negocio no depende de ninguna tecnología: `app/` declara qué necesita e `infrastructure/` lo
provee.

```text
src/users_api/
├── main.py                 # aplicación FastAPI y ciclo de vida de las conexiones
├── seed_superadmin.py      # siembra del primer administrador, otro punto de entrada
├── api/                    # lo que se expone hacia afuera
│   ├── auth.py             # registro, validación, login y cierre de sesión
│   ├── admin_auth.py       # login del backoffice, con su propia política
│   ├── password_reset.py   # recuperación de contraseña olvidada
│   ├── password_change.py  # cambio de contraseña sabiendo la actual
│   ├── profile.py          # lectura y edición del propio perfil
│   ├── preferences.py      # visibilidad del perfil e idioma del feed
│   ├── internal.py         # rutas que solo llaman los otros servicios, fuera de /api
│   ├── health.py           # verificación de dependencias
│   ├── deps.py             # qué implementación recibe cada interfaz, y la autenticación
│   ├── errors.py           # traduce los errores al formato RFC 9457
│   └── schemas/            # qué entra y qué sale de cada ruta
├── app/                    # el negocio, sin nombrar ninguna tecnología
│   ├── models/             # User y los tokens, con sus reglas
│   ├── repositories/       # interfaces de dónde vive el estado, outbox incluido
│   ├── services/           # los casos de uso
│   ├── events.py           # arma el sobre CloudEvents de cada evento que se publica
│   ├── security.py         # hasheo de contraseñas, tokens y JWT
│   └── errors.py           # el error que levantan los servicios
├── config/
│   └── settings.py         # configuración leída del entorno
└── infrastructure/         # las implementaciones, agrupadas por tecnología
    ├── database/           # tablas de SQLAlchemy y los repositorios que las usan
    ├── redis/              # contador de intentos y revocación de sesiones
    ├── rabbitmq/           # publicador del outbox hacia RabbitMQ
    └── health.py           # consulta real a PostgreSQL y a Redis
tests/
├── unit/                   # sin dependencias externas, con dobles de las interfaces
└── integration/            # contra PostgreSQL, Redis y RabbitMQ reales
docker/
├── Dockerfile              # multi-stage sobre python:3.13-slim
└── docker-compose.dev.yml  # servicio, PostgreSQL, Redis y RabbitMQ
```

**La regla es una sola: `app/` no importa nada de `api/` ni de `infrastructure/`.** Se verifica
leyendo imports, y hoy se cumple: en `app/` no aparecen las palabras `sqlalchemy`, `redis` ni
`fastapi`.

El único módulo que conoce las implementaciones concretas es `api/deps.py`. Cambiar de motor de
base o de broker es escribir la clase nueva en `infrastructure/` y tocar ese
archivo.

En `app/repositories/` viven las interfaces de todo lo que **almacena estado**: usuarios,
tokens, eventos pendientes de publicar, contadores de intentos y revocaciones de sesión. Que unas
se guarden en PostgreSQL y otras en Redis es problema de `infrastructure/`. Hoy no hay ninguna
interfaz de lo que **habla con un tercero**: los emails los manda `notifications-api`. Si aparece
una, va en `app/clients/`, junto a `repositories/`.

Cuando se agrega una tabla, su modelo va en `infrastructure/database/models.py`, que es lo que
`migrations/env.py` importa. Un modelo que quede afuera hace que
`alembic revision --autogenerate` proponga borrar la tabla.

## Code Guidelines (Reglas del Equipo)
Para mantener la calidad y consistencia del código, todos los miembros deben seguir estas reglas:
* **Ramas:** Obligatorio usar la convención `feature-[nombre-de-la-funcionalidad]` o `fix-[fix-a-realizar]`. Toda rama se integra a `main`.
* **Issues:** Todas las ramas deben tener un issue asociado con la información necesaria para implementar la tarea.
* **Etiquetas (Labels):** Los issues deben clasificarse usando `feature`, `tech debt`, `spike`, o `bug`.
* **Pull Requests (PR):** Las descripciones de los PR deben redactarse en **español**.
* **Idioma del código:** En inglés todo lo que vive dentro de un archivo de código (variables, funciones, clases, tablas, comentarios y docstrings) y los nombres de los archivos y carpetas de código. En español la documentación, los mensajes de commit y las descripciones de PR.
* **Commits (Opcional):** Recomendamos usar la convención de [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

La versión completa y vigente de estas reglas vive en [`CONVENCIONES.md`](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/CONVENCIONES.md) de `udesa-x-platform`; ante cualquier diferencia, manda ese archivo. El punto de entrada para trabajar en este repo, con o sin agente, es su `AGENTS.md`.
