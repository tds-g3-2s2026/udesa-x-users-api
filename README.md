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
| `GET /healthcheck` | Verifica PostgreSQL y Redis |
| `POST /auth/register` | Crea la cuenta y envía el link de verificación |
| `POST /auth/verify` | Consume el token y valida la cuenta |
| `POST /auth/resend-verification` | Pide un link nuevo cuando el anterior expiró |
| `POST /auth/login` | Devuelve el access token. El claim `role` lleva el rol real de la cuenta |
| `POST /admin/auth/login` | Login del backoffice, con email. Solo `moderator` y `superadmin`; un usuario común recibe `403`. Tres intentos fallidos bloquean por 30 minutos |
| `POST /admin/users` | Crea un administrador con una contraseña temporal. Solo `superadmin`. La temporal viaja en claro en la respuesta, una única vez |
| `GET /admin/users` | Lista los administradores con el estado de su credencial temporal. Solo `superadmin` |
| `POST /admin/users/{id}/reset-temporary-password` | Genera una temporal nueva para una cuenta que todavía no eligió la suya. Solo `superadmin` |
| `POST /auth/logout` | Revoca el token de sesión activo |
| `POST /auth/forgot-password` | Manda el link de recuperación, con email o handle |
| `POST /auth/reset-password` | Consume el link y cambia la contraseña |
| `POST /me/change-password` | Cambia la contraseña sabiendo la actual. Revoca todas las sesiones, la que hizo el pedido incluida |
| `GET /me` | Devuelve el perfil de la cuenta autenticada |
| `PATCH /me` | Edita `display_name` y `bio`. Rechaza `email` y `handle`, que no se pueden tocar acá |
| `GET /me/preferences` | Devuelve `profile_visibility` y `feed_language` de la cuenta autenticada |
| `PATCH /me/preferences` | Edita una o las dos preferencias. Cada una es un enum: un valor fuera de lo definido se rechaza con `422` |

En desarrollo el correo no se envía: el adaptador escribe el link en el log. Se lo saca así:

```bash
docker compose -f docker/docker-compose.dev.yml logs users-api | grep users_api.infrastructure.email.console
```

La documentación interactiva queda en `http://localhost:8000/docs`.

## Configuración

Variables de entorno que lee el servicio, además de `DATABASE_URL` y `REDIS_URL`:

| Variable | Default | Para qué |
|---|---|---|
| `JWT_PRIVATE_KEY` | efímera | Clave Ed25519 en PEM. Sin definir, se genera una por arranque |
| `JWT_ISSUER` | `users-api` | Emisor incluido en el claim `iss` de los tokens |
| `LOG_LEVEL` | `INFO` | Nivel de log |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Base de los links enviados por correo; en el cluster incluye `/api` |
| `ACCESS_TOKEN_MINUTES` | `15` | Vida del access token |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Bloqueo del login de la app |
| `ADMIN_LOGIN_MAX_ATTEMPTS` / `ADMIN_LOGIN_LOCKOUT_MINUTES` | `3` / `30` | Bloqueo del login del backoffice. Contador independiente del de la app |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | sin definir | Credenciales del primer superadmin, que siembra el comando de abajo |
| `SUPERADMIN_HANDLE` | `@superadmin` | Handle de esa cuenta: la columna es obligatoria y única |
| `CORS_ALLOWED_ORIGINS` | `[]` | Orígenes de browser permitidos, como lista JSON. Vacío bloquea a todos; mobile no lo necesita, el backoffice sí |
| `ADMINISTRATOR_EMAIL_DOMAIN` | sin definir | Dominio al que tiene que pertenecer el correo de un administrador nuevo. Vacío significa sin restricción |

## Despliegue en Kubernetes

Los cuatro manifiestos de `k8s/` usan el namespace `tds-group-3`, según
[ADR-008](https://github.com/tds-g3-2s2026/udesa-x-platform/blob/main/docs/adr/ADR-008-plataforma-de-despliegue.md).
El Deployment tiene una réplica, requests de `100m` / `128Mi` y limits de
`500m` / `512Mi`, dentro de los límites definidos por la cátedra. El rolling update
requiere un slot adicional de pod; si no queda espacio en la cuota compartida,
hay que usar `maxSurge: 0` y `maxUnavailable: 1`, aceptando la interrupción.

La imagen queda parametrizada hasta contar con la URI asignada de ECR. El futuro
pipeline debe reemplazar `${ECR_URI_PREFIX}/users-api:${IMAGE_TAG}` por la URI real
y un tag inmutable antes de aplicar el Deployment. `ECR_URI_PREFIX` no lleva barra
final; si ECR asigna otro nombre o separador de repositorio, se reemplaza la referencia
completa. Kubernetes no expande estas variables.

Copiar `k8s/secret.template.yaml` a `k8s/secret.yaml`, ignorado por git, y completar
`DATABASE_URL` (PostgreSQL con `postgresql+asyncpg://`), `REDIS_URL` y
`JWT_PRIVATE_KEY` (PEM Ed25519, usando un bloque YAML `|` para conservar los saltos).
Nunca aplicar la plantilla vacía sobre un Secret real: sobrescribiría sus valores.
El pipeline debe generar y aplicar el Secret con valores de GitHub Secrets.

`PUBLIC_BASE_URL` usa el host del Ingress con `/api`, porque la aplicación agrega
`/auth/verify` al construir el link. `JWT_ISSUER` configura el claim `iss` de los tokens
emitidos; no agrega validación de emisor al recibir tokens.

El Service es interno (`ClusterIP`, puerto `80` hacia `8000`); la entrada externa
pasa por el Ingress y el gateway. `containerPort`, `targetPort`, `EXPOSE` y el comando
Uvicorn del Dockerfile coinciden en `8000`. Ambas sondas consultan `/healthcheck`.
Ese endpoint comprueba PostgreSQL y Redis: una caída sostenida de esas dependencias
también provoca reinicios por la sonda de vida.

Para validar sin modificar el cluster:

```bash
kubectl apply --dry-run=client -f k8s/
```

El comando requiere kubectl y un contexto con acceso de lectura al API server
para consultar descubrimiento y esquemas, aunque no requiere permisos de escritura.
La validación de la plantilla no acredita que los secretos ni la imagen estén listos.
Para desplegar, aplicar explícitamente ConfigMap, Secret real, Deployment con imagen
resuelta y Service, sin incluir `secret.template.yaml`. La aprobación del tutor se
gestiona en el PR.

## Primer superadmin

El panel no puede crear al primer administrador porque nadie puede entrar al panel todavía. Se
siembra con un comando que corre antes de arrancar la API; en desarrollo lo dispara el compose,
en producción es un job del despliegue, con las credenciales inyectadas desde GitHub Secrets:

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

**Una sola migración mientras no haya un deploy real** (`migrations/versions/0001_esquema_actual.py`).
Sin una base con datos vivos no hay nada que una migración incremental esté protegiendo, así que
un cambio de esquema se edita en ese mismo archivo en vez de sumar una `0002_...` nueva. El día
que exista un primer deploy, esa migración pasa a ser la base fija y ahí sí arrancan las
incrementales con `alembic revision --autogenerate`.

## Probar el flujo completo a mano

Levantá el stack y **dejá esa terminal abierta**: ahí aparece el link de verificación, que es
lo que iría por correo.

```bash
docker compose -f docker/docker-compose.dev.yml down -v
docker compose -f docker/docker-compose.dev.yml up --build
```

Los comandos que siguen van en otra terminal. Están en PowerShell porque es lo que usa el
equipo; en bash se escriben igual sin las contrabarras.

### 1. Registrarse

```powershell
curl.exe -X POST http://localhost:8000/auth/register -H "Content-Type: application/json" -d '{\"email\":\"Alumno@udesa.edu.ar\",\"handle\":\"@alumno_01\",\"password\":\"Contrasena1\",\"terms_accepted\":true}'
```

```json
{"id":"6a0e1bc0-...","email":"alumno@udesa.edu.ar","handle":"@alumno_01"}
```

El email se guardó en minúsculas aunque se mandó con mayúscula: es `E1-H1 CA.7`.

En la terminal del compose aparece el correo:

```
INFO users_api.infrastructure.email.console | Correo de verificación para alumno@udesa.edu.ar.
Link válido por tiempo limitado: http://localhost:8000/auth/verify?token=P0oIiKeSRxIN...
```

### 2. Intentar entrar sin validar la cuenta

```powershell
curl.exe -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{\"identifier\":\"alumno@udesa.edu.ar\",\"password\":\"Contrasena1\"}'
```

```json
{"status":403,"detail":"Revisá tu casilla de correo para validar la cuenta antes de ingresar", ...}
```

`E1-H1 CA.1` y `E1-H2 CA.4`. Notar que el mensaje es específico: las credenciales eran
correctas, así que quien pregunta ya demostró ser el dueño de la cuenta.

### 3. Validar la cuenta

El JSON va por archivo porque PowerShell rompe las comillas anidadas.

```powershell
$log = docker compose -f docker/docker-compose.dev.yml logs users-api | Out-String
$tok = [regex]::Match($log, 'token=([\w\-]+)').Groups[1].Value
'{"token":"' + $tok + '"}' | Set-Content "$env:TEMP\token.json" -Encoding utf8 -NoNewline
curl.exe -X POST http://localhost:8000/auth/verify -H "Content-Type: application/json" --data "@$env:TEMP\token.json"
```

```json
{"status":"verified","handle":"@alumno_01"}
```

Repetir el mismo comando devuelve `400`: el token es de un solo uso.

### 4. Entrar, con el email en mayúsculas

```powershell
curl.exe -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{\"identifier\":\"ALUMNO@UDESA.EDU.AR\",\"password\":\"Contrasena1\"}'
```

```json
{"access_token":"eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9...","token_type":"bearer","expires_in":900}
```

`expires_in` son los 15 minutos de `E1-H2 CA.1`. Pegando el token en
[jwt.io](https://jwt.io) se ven `alg: EdDSA` y los claims `sub`, `role` y `jti`.

También funciona entrando con el handle en lugar del email.

### 5. Bloqueo por intentos fallidos

```powershell
foreach ($i in 1..6) { curl.exe -s -o NUL -w "intento $i -> %{http_code}`n" -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{\"identifier\":\"alumno@udesa.edu.ar\",\"password\":\"Mala1234\"}' }
```

```
intento 1 -> 401
intento 2 -> 401
intento 3 -> 401
intento 4 -> 401
intento 5 -> 401
intento 6 -> 429
```

`E1-H2 CA.2`. A partir del sexto, **la contraseña correcta tampoco entra**: devuelve `429`
hasta que pasen los 15 minutos. La clave en Redis tiene TTL, así que el desbloqueo es
automático.

### 6. Cerrar sesión

Repetí el paso 4 para conseguir un token nuevo (el de más arriba ya gastó intentos en el paso
anterior) y guardalo en una variable:

```powershell
$body = curl.exe -s -X POST http://localhost:8000/auth/login -H "Content-Type: application/json" -d '{\"identifier\":\"alumno@udesa.edu.ar\",\"password\":\"Contrasena1\"}' | ConvertFrom-Json
$token = $body.access_token

curl.exe -s -o NUL -w "%{http_code}`n" -X POST http://localhost:8000/auth/logout -H "Authorization: Bearer $token"
```

```
204
```

`E1-H3 CA.1`. El token queda revocado en Redis con el mismo tiempo de vida que le quedaba:

```powershell
docker compose -f docker/docker-compose.dev.yml exec redis redis-cli keys "revoked:*"
```

### 7. Recuperar la contraseña olvidada

```powershell
curl.exe -X POST http://localhost:8000/auth/forgot-password -H "Content-Type: application/json" -d '{\"identifier\":\"alumno@udesa.edu.ar\"}'
```

```json
{"status":"accepted"}
```

`E1-H5 CA.4`. La respuesta es esta misma para una dirección que no existe: probá con
`nadie@udesa.edu.ar` y comparala. En la terminal del compose aparece el link, que dura diez
minutos y no veinticuatro horas como el de validación (`E1-H5 CA.1`):

```
INFO users_api.infrastructure.email.console | Correo de recuperación para alumno@udesa.edu.ar.
Link válido por tiempo limitado: http://localhost:8000/auth/reset-password?token=VMT1tI_Hy7...
```

Con ese token se cambia la contraseña. La confirmación va aparte y tiene que coincidir
(`E1-H5 CA.3`):

```powershell
$log = docker compose -f docker/docker-compose.dev.yml logs users-api | Out-String
$tok = [regex]::Match($log, 'reset-password\?token=([\w\-]+)').Groups[1].Value
'{"token":"' + $tok + '","password":"Contrasena2","password_confirmation":"Contrasena2"}' | Set-Content "$env:TEMP\reset.json" -Encoding utf8 -NoNewline
curl.exe -X POST http://localhost:8000/auth/reset-password -H "Content-Type: application/json" --data "@$env:TEMP\reset.json"
```

```json
{"status":"reset","handle":"@alumno_01"}
```

Repetir el mismo comando devuelve `400`: el link es de un solo uso (`E1-H5 CA.5`). Reintentar
con la contraseña vieja, `Contrasena1`, también da `400`, porque la nueva tiene que ser distinta
(`E1-H5 CA.6`). Y todas las sesiones que estaban abiertas quedaron revocadas de una (`E1-H5
CA.7`):

```powershell
docker compose -f docker/docker-compose.dev.yml exec redis redis-cli keys "revoked:user:*"
```

Pedir más de tres links en una hora para el mismo identificador devuelve `429` (`E1-H5 CA.8`).

### 8. Entrar al backoffice como superadmin

El superadmin sembrado por el compose entra por la puerta del backoffice y el token lleva su rol:

```powershell
curl.exe -X POST http://localhost:8000/admin/auth/login -H "Content-Type: application/json" -d '{\"email\":\"admin@udesa.edu.ar\",\"password\":\"Admin1234\"}'
```

El usuario del paso 1 tiene la contraseña correcta pero no el rol, así que recibe `403` con
`type` terminado en `/not-an-administrator` (`E5-H2 CA.2`). Tres contraseñas equivocadas seguidas
bloquean esta puerta por 30 minutos con `429` y `Retry-After: 1800` (`E5-H2 CA.3`); el login de
la app del mismo usuario no se entera, porque cada puerta lleva su contador.

### 9. Crear un administrador desde el panel

Con el token del paso anterior, el superadmin da de alta a una moderadora. La respuesta trae la
contraseña temporal, y es la única vez que se puede leer:

```powershell
curl.exe -X POST http://localhost:8000/admin/users -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{\"email\":\"moderadora@udesa.edu.ar\",\"handle\":\"@moderadora\",\"role\":\"moderator\"}'
```

Esa cuenta entra al backoffice con la temporal y el login le contesta `must_change_password: true`.
Mientras esa bandera esté prendida su sesión solo sirve para `POST /me/change-password` y para
cerrarse: cualquier otra ruta devuelve `403` con `type` terminado en `/password-change-required`
(`E5-H1 CA.1`). Un moderador que intente crear administradores recibe `403` con
`/superadmin-required` (`E5-H1 CA.2`).

Pasadas 24 horas sin usarla, la temporal deja de servir y el superadmin genera otra con
`POST /admin/users/{id}/reset-temporary-password` (`E5-H1 CA.3`). Con
`ADMINISTRATOR_EMAIL_DOMAIN=udesa.edu.ar` en el compose, un alta con una dirección de otro
dominio se rechaza con `400` y `/email-domain-not-allowed` (`E5-H1 CA.4`).

Para terminar: `docker compose -f docker/docker-compose.dev.yml down`

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
    ├── email/              # en desarrollo escribe el link en el log
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
