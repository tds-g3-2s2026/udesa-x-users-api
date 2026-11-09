"""Avisar la visibilidad de todas las cuentas vivas antes de que el cambio generara eventos.

`posts-api` decide quién lee los posts de una cuenta con una copia de `profile_visibility`
que hasta ahora solo se actualizaba cuando la cuenta hacía un pedido con un token. Una
cuenta que cambió de visibilidad sin volver a interactuar quedó con la copia vieja, y no hay
forma de saber desde acá cuáles. Por eso se avisa a todas, públicas y protegidas.

Deja un evento por cuenta con los valores vigentes en el outbox, y el publicador los manda
como a cualquier otro. Las cuentas borradas quedan afuera: no tienen posts que proteger.

El `time` de estos eventos es el origen de la época y no el instante de la migración. Este
evento solo tiene que llenar las copias que nunca recibieron uno, y cualquier cambio real,
anterior o posterior, tiene que ganarle. Con la hora de la base, un cambio que se estaba
guardando cuando corrió la migración, o un reloj adelantado, podían dejar la copia vieja.

Tiene que correr con `posts-api` ya desplegado con el consumidor de la visibilidad: un
evento que el consumidor viejo lee sin el campo nuevo no cambia nada, y no se vuelve a
mandar. Y con la cola de `posts-api` ya ligada al evento: uno sin cola ligada se queda en el
outbox, y una tanda grande de esos frenaría a los demás.

También tiene que correr cuando ya no queda ningún pod de `users-api` con el código viejo:
uno que atienda un cambio de visibilidad después de la migración no publica el evento, y la
copia queda vieja hasta el próximo cambio de esa cuenta.

No hay vuelta atrás: un evento ya publicado no se puede retirar.
"""

from alembic import op

revision = "e27b5d83a1c4"
down_revision = "b83f0c1d7e52"
branch_labels = None
depends_on = None

QUEUE_CURRENT_PREFERENCES = """
    INSERT INTO outbox (id, type, payload)
    SELECT
        event_id,
        'preferences.changed.v1',
        jsonb_build_object(
            'specversion', '1.0',
            'id', event_id::text,
            'source', 'users-api',
            'type', 'preferences.changed.v1',
            'time', '1970-01-01T00:00:00.000Z',
            'data', jsonb_build_object(
                'user_id', id::text,
                'feed_language', feed_language,
                'profile_visibility', profile_visibility
            )
        )
    FROM (
        SELECT gen_random_uuid() AS event_id, id, feed_language, profile_visibility
        FROM users
        WHERE deleted_at IS NULL
    ) AS living
"""


def upgrade() -> None:
    op.execute(QUEUE_CURRENT_PREFERENCES)


def downgrade() -> None:
    pass
