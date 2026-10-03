# UdeSA-X Users API

Microservicio backend responsable de la gestión de identidades, registro de usuarios, edición de perfiles, inicio de sesión (incluyendo Social Login) y seguridad.

**Stack:** Python 3.13, FastAPI, SQLAlchemy 2 async con asyncpg, PostgreSQL y Redis. Gestión de dependencias con uv, linting con Ruff.

## Levantarlo en desarrollo

```bash
docker compose -f docker/docker-compose.dev.yml up --build
```

Levanta el servicio junto con PostgreSQL y Redis, aplica las migraciones y siembra el primer
superadmin (`admin@udesa.edu.ar` / `Admin1234`, solo para desarrollo). Cuando los tres estén arriba:

```bash
curl http://localhost:8000/healthcheck
```

Responde `200` con `{"status": "ok", ...}` si ambas dependencias contestan, y `503` con el detalle de cuál falló si alguna no. Es el mismo endpoint que consume el `readinessProbe` de Kubernetes: un `503` saca al pod de rotación en lugar de mandarle tráfico que va a fallar.

La documentación interactiva de la API queda en `http://localhost:8000/docs`.

## Endpoints

| Método y ruta | Qué hace |
|---|---|
| `GET /healthcheck` | Verifica PostgreSQL y Redis e informa la versión desplegada |
| `POST /auth/register` | Crea la cuenta y envía el link de verificación |
| `POST /auth/verify` | Consume el token y valida la cuenta |
| `GET /auth/verify?token=` | Lo mismo, para el link del correo: un cliente de correo solo puede abrirlo con `GET` |
| `POST /auth/resend-verification` | Pide un link nuevo cuando el anterior expiró |
| `POST /auth/login` | Devuelve el access token. El claim `role` lleva el rol real de la cuenta |
| `POST /admin/auth/login` | Login del backoffice, con email. Solo `moderator` y `superadmin`; un usuario común recibe `403`. Tres intentos fallidos bloquean por 30 minutos |
| `POST /admin/users` | Crea un administrador con una contraseña temporal. Solo `superadmin`. La temporal viaja en claro en la respuesta, una única vez |
| `GET /admin/users` | Lista los administradores con el estado de su credencial temporal. Solo `superadmin` |
| `POST /admin/users/{id}/reset-temporary-password` | Genera una temporal nueva para una cuenta que todavía no eligió la suya. Solo `superadmin` |
| `GET /admin/metrics` | Cuentas de la app verificadas y no borradas: activas (`active_users`) y en revisión (`accounts_under_review`). Cualquier administrador; un usuario común recibe `403` |
| `POST /auth/logout` | Revoca el token de sesión activo |
| `POST /auth/forgot-password` | Manda el código de recuperación, con email o handle. El usuario lo pega en la app |
| `POST /auth/reset-password` | Consume el link y cambia la contraseña |
| `POST /me/change-password` | Cambia la contraseña sabiendo la actual. Revoca todas las sesiones, la que hizo el pedido incluida |
| `GET /me` | Devuelve el perfil de la cuenta autenticada |
| `PATCH /me` | Edita `display_name` y `bio`. Rechaza `email` y `handle`, que no se pueden tocar acá |
| `GET /me/preferences` | Devuelve `profile_visibility` y `feed_language` de la cuenta autenticada |
| `PATCH /me/preferences` | Edita una o las dos preferencias. Cada una es un enum: un valor fuera de lo definido se rechaza con `422` |
| `POST /internal/users/{id}/review` | Pone la cuenta en revisión y revoca todas sus sesiones. Fuera de `/api`, así que el gateway no la expone: la llama `posts-api` por la red del cluster ([ADR-011](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-011-denuncias-y-cuenta-en-revision.md)). Exige el header `X-Internal-Token`; sin él o con otro valor responde `401`. Llamarla de nuevo responde `204` y no cambia nada |

Una cuenta en revisión no puede iniciar sesión: el login responde `403` con el código
`account-under-review` y un mensaje propio, distinto del de `account-suspended`. Los tokens que ya
tenía dejan de servir en `users-api` al instante. `posts-api` no ve esa revocación y los acepta
hasta que vencen, como máximo `ACCESS_TOKEN_MINUTES`. Salir de revisión le toca al backoffice
(`E5-H7`). Una cuenta suspendida no pasa a revisión: la decisión del administrador pesa más.

En desarrollo el correo no se envía: el adaptador de consola escribe el link en el log (ver
[Correo](#correo) para mandarlo de verdad). Se lo saca así:

```bash
docker compose -f docker/docker-compose.dev.yml logs users-api | grep users_api.infrastructure.email.console
```

La documentación interactiva queda en `http://localhost:8000/docs`.

## Configuración

Variables de entorno que lee el servicio, además de `DATABASE_URL`, `REDIS_URL` e
`INTERNAL_API_TOKEN`. Las tres son obligatorias: sin ellas el servicio no arranca.
`INTERNAL_API_TOKEN` es el secreto que comparte con `posts-api` para las rutas de `/internal`, y
tiene que tener el mismo valor en los dos servicios.

| Variable | Default | Para qué |
|---|---|---|
| `JWT_PRIVATE_KEY` | efímera | Clave Ed25519 en PEM. Sin definir, se genera una por arranque |
| `JWT_ISSUER` | `users-api` | Emisor incluido en el claim `iss` de los tokens |
| `LOG_LEVEL` | `INFO` | Nivel de log |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base de los links enviados por correo: el host solo, sin `/api` |
| `ACCESS_TOKEN_MINUTES` | `15` | Vida del access token |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Bloqueo del login de la app |
| `ADMIN_LOGIN_MAX_ATTEMPTS` / `ADMIN_LOGIN_LOCKOUT_MINUTES` | `3` / `30` | Bloqueo del login del backoffice. Contador independiente del de la app |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | sin definir | Credenciales del primer superadmin, que siembra el comando de abajo |
| `SUPERADMIN_HANDLE` | `@superadmin` | Handle de esa cuenta: la columna es obligatoria y única |
| `CORS_ALLOWED_ORIGINS` | `[]` | Orígenes de browser permitidos, como lista JSON. Vacío bloquea a todos; mobile no lo necesita, el backoffice sí |
| `ADMINISTRATOR_EMAIL_DOMAIN` | sin definir | Dominio al que tiene que pertenecer el correo de un administrador nuevo. Vacío significa sin restricción |
| `EMAIL_PROVIDER` | `console` | `console` escribe cada correo en el log; `resend` lo entrega de verdad |
| `RESEND_API_KEY` | sin definir | Clave de la API de Resend. Obligatoria con `EMAIL_PROVIDER=resend`: sin ella el servicio no arranca |
| `EMAIL_FROM` | `UdeSA-X <no-reply@udesax.app>` | Remitente de todos los correos. Su dominio tiene que estar verificado en Resend |

## Correo

El proveedor es **Resend**, con el dominio `udesax.app` verificado. Sin un dominio verificado,
Resend solo entrega a la dirección dueña de la cuenta. El plan gratuito permite 100 correos
por día y 3.000 por mes.

En desarrollo y en los tests se usa el adaptador de consola: los tests de integración leen el
token del log, y así ninguna corrida manda correo de verdad. Para probar la entrega real en
local, poné la clave en un `.env` en la raíz del repo, que no se versiona y que el compose de
desarrollo le pasa al servicio:

```bash
EMAIL_PROVIDER=resend
RESEND_API_KEY=re_...
```

Un fallo del proveedor no rompe la operación que disparó el correo. La cuenta queda creada, o
la contraseña cambiada, y el error queda en el log sin el link, porque el link es una
credencial de un solo uso. Si el correo de verificación no llegó, se pide otro con
`POST /auth/resend-verification`.

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
`DATABASE_URL` (PostgreSQL con `postgresql+asyncpg://`), `REDIS_URL` y
`JWT_PRIVATE_KEY` (PEM Ed25519, usando un bloque YAML `|` para conservar los saltos),
`RESEND_API_KEY` e `INTERNAL_API_TOKEN`. Nunca aplicar la plantilla vacía sobre un Secret real: sobrescribiría sus
valores. El pipeline arma el Secret real con los GitHub Secrets `DATABASE_URL`, `REDIS_URL`,
`JWT_PRIVATE_KEY`, `INTERNAL_API_TOKEN` y `RESEND_API_KEY`; este último es de la organización, para que otro
servicio pueda usar la misma clave. El ConfigMap fija `EMAIL_PROVIDER=resend`, así que sin
`RESEND_API_KEY` el pipeline corta antes de tocar el cluster. `envFrom` inyecta las
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

Los de integración aplican la migración real antes de correr, así que también verifican que el
esquema coincida con los modelos: una columna agregada sin su migración falla acá y no en
producción.

### Como los corre el CI: dentro de la imagen

Lo de arriba corre sobre tu máquina y sirve para iterar. **El CI los corre adentro de la imagen
Docker del servicio**, que es lo que hace que el resultado no dependa de cómo esté armada la
máquina. El `Dockerfile` tiene un stage `test` que suma las dependencias de desarrollo y la
carpeta `tests/` sobre el mismo build que va a producción.

Para reproducirlo hay un servicio en el compose que construye ese stage y lo corre contra
PostgreSQL y Redis, esperando a que estén sanos:

```bash
docker compose -f docker/docker-compose.dev.yml run --rm --build tests
```

Ese servicio **no monta el código como volumen** a propósito. Montarlo reemplazaría lo que hay
adentro de la imagen por lo que hay en el disco, y se dejaría de probar el artefacto que
efectivamente se despliega, que es todo el punto de correrlos así.

Adentro del contenedor los nombres de host son `postgres` y `redis`, no `localhost`: ahí
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
│   ├── repositories/       # interfaces de dónde vive el estado
│   ├── clients/            # interfaces de lo que habla con un tercero
│   ├── services/           # los casos de uso
│   ├── security.py         # hasheo de contraseñas, tokens y JWT
│   └── errors.py           # el error que levantan los servicios
├── config/
│   └── settings.py         # configuración leída del entorno
└── infrastructure/         # las implementaciones, agrupadas por tecnología
    ├── database/           # tablas de SQLAlchemy y los repositorios que las usan
    ├── redis/              # contador de intentos y revocación de sesiones
    ├── email/              # Resend, y el adaptador de consola para desarrollo y tests
    └── health.py           # consulta real a PostgreSQL y a Redis
tests/
├── unit/                   # sin dependencias externas, con dobles de las interfaces
└── integration/            # contra PostgreSQL y Redis reales
docker/
├── Dockerfile              # multi-stage sobre python:3.13-slim
└── docker-compose.dev.yml  # servicio, PostgreSQL y Redis
```

**La regla es una sola: `app/` no importa nada de `api/` ni de `infrastructure/`.** Se verifica
leyendo imports, y hoy se cumple: en `app/` no aparecen las palabras `sqlalchemy`, `redis` ni
`fastapi`.

El único módulo que conoce las implementaciones concretas es `api/deps.py`. Cambiar de motor de
base o de proveedor de correo es escribir la clase nueva en `infrastructure/` y tocar ese
archivo.

En `app/repositories/` viven las interfaces de todo lo que **almacena estado**: usuarios,
tokens, contadores de intentos y revocaciones de sesión. Que unas se guarden en PostgreSQL y
otras en Redis es problema de `infrastructure/`. En `app/clients/` viven las de lo que **habla
con un tercero**, que hoy es solo el envío de correo.

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
