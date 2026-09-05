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
| `POST /auth/logout` | Revoca el token de sesión activo |
| `POST /auth/forgot-password` | Manda el link de recuperación, con email o handle |
| `POST /auth/reset-password` | Consume el link y cambia la contraseña |

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
| `ACCESS_TOKEN_MINUTES` | `15` | Vida del access token |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | `5` / `15` | Bloqueo del login de la app |
| `ADMIN_LOGIN_MAX_ATTEMPTS` / `ADMIN_LOGIN_LOCKOUT_MINUTES` | `3` / `30` | Bloqueo del login del backoffice. Contador independiente del de la app |
| `SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` | sin definir | Credenciales del primer superadmin, que siembra el comando de abajo |
| `SUPERADMIN_HANDLE` | `@superadmin` | Handle de esa cuenta: la columna es obligatoria y única |
| `CORS_ALLOWED_ORIGINS` | `[]` | Orígenes de browser permitidos, como lista JSON. Vacío bloquea a todos; mobile no lo necesita, el backoffice sí |

## Primer superadmin

El panel no puede crear al primer administrador porque nadie puede entrar al panel todavía. Se
siembra con un comando que corre antes de arrancar la API; en desarrollo lo dispara el compose,
en producción es un job del despliegue, con las credenciales por SOPS:

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
uv run alembic revision --autogenerate -m "descripcion"   # crear una nueva
```

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
├── api/                    # lo que se expone hacia afuera
│   ├── auth.py             # registro, validación, login y cierre de sesión
│   ├── password_reset.py   # recuperación de contraseña olvidada
│   ├── health.py           # verificación de dependencias
│   ├── deps.py             # qué implementación recibe cada interfaz
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
