"""Avisar el idioma de las cuentas que lo eligieron antes de que existiera el evento.

`posts-api` guarda una copia de `feed_language` que se actualiza con
`preferences.changed.v1`, y una cuenta sin copia ve todos los idiomas. Una cuenta que ya
tenía español o inglés nunca generaría ese evento, y su feed no filtraría aunque la app le
muestre el idioma elegido.

Deja un evento por cuenta en el outbox y el publicador los manda como a cualquier otro. Si
la cuenta cambia de idioma después, el consumidor se queda con el más nuevo por el `time`.
Las cuentas borradas quedan afuera: no tienen feed que filtrar.

Tiene que correr con la cola de `posts-api` ya ligada al evento: un evento sin cola ligada
se queda en el outbox, y una tanda grande de esos frenaría a los demás. Que `posts-api` esté
desplegado no alcanza, porque declara la cola en segundo plano y arranca igual si el broker
no responde.

No hay vuelta atrás: un evento ya publicado no se puede retirar.
"""

from alembic import op

revision = "d14a6e2f9c07"
down_revision = "search_account_trigrams"
branch_labels = None
depends_on = None

QUEUE_CHOSEN_LANGUAGES = """
    INSERT INTO outbox (id, type, payload)
    SELECT
        event_id,
        'preferences.changed.v1',
        jsonb_build_object(
            'specversion', '1.0',
            'id', event_id::text,
            'source', 'users-api',
            'type', 'preferences.changed.v1',
            'time', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
            'data', jsonb_build_object('user_id', id::text, 'feed_language', feed_language)
        )
    FROM (
        SELECT gen_random_uuid() AS event_id, id, feed_language
        FROM users
        WHERE feed_language <> 'all' AND deleted_at IS NULL
    ) AS chosen
"""


def upgrade() -> None:
    op.execute(QUEUE_CHOSEN_LANGUAGES)


def downgrade() -> None:
    pass
