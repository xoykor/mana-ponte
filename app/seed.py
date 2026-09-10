"""Dados demonstrativos determinísticos e sem acesso à rede.

O seed serve para a primeira execução local e para os testes. Ele nunca deve
substituir um catálogo real nem ser usado como rotina de sincronização.
"""

from __future__ import annotations

from .auth import hash_password
from .db import get_connection, init_db


# Senha pública usada somente pelos fixtures locais e pelos testes.
DEV_PASSWORD = "ManaPonte!2026"


# Cada tupla representa uma impressão:
# scryfall_id, oracle_id, nome, código do set, nome do set, número,
# idioma, raridade e URL da imagem.
CARDS = [
    (
        "b0faa7f2-b547-42c4-a810-839da50dadfe",
        "5089ec1a-f881-4d55-af14-5d996171203b",
        "Black Lotus",
        "lea",
        "Limited Edition Alpha",
        "232",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/b/0/b0faa7f2-b547-42c4-a810-839da50dadfe.jpg",
    ),
    (
        "46ca0b66-a000-4483-b916-f5b89e710244",
        "6ad8011d-3471-4369-9d68-b264cc027487",
        "Sol Ring",
        "cmm",
        "Commander Masters",
        "410",
        "en",
        "uncommon",
        "https://cards.scryfall.io/normal/front/4/6/46ca0b66-a000-4483-b916-f5b89e710244.jpg",
    ),
    (
        "e768c957-3a1f-42f5-853a-96942f645df5",
        "4457ed35-7c10-48c8-9776-456485fdf070",
        "Lightning Bolt",
        "m11",
        "Magic 2011",
        "149",
        "en",
        "common",
        "https://cards.scryfall.io/normal/front/e/7/e768c957-3a1f-42f5-853a-96942f645df5.jpg",
    ),
    (
        "1920dae4-fb92-4f19-ae4b-eb3276b8dac7",
        "cc187110-1148-4090-bbb8-e205694a39f5",
        "Counterspell",
        "mh2",
        "Modern Horizons 2",
        "267",
        "en",
        "uncommon",
        "https://cards.scryfall.io/normal/front/1/9/1920dae4-fb92-4f19-ae4b-eb3276b8dac7.jpg",
    ),
    (
        "581b7327-3215-4a4f-b4ae-d9d4002ba882",
        "68954295-54e3-4303-a6bc-fc4547a4e3a3",
        "Llanowar Elves",
        "dom",
        "Dominaria",
        "168",
        "en",
        "common",
        "https://cards.scryfall.io/normal/front/5/8/581b7327-3215-4a4f-b4ae-d9d4002ba882.jpg",
    ),
    (
        "4d3473d0-b46f-41f5-ac1e-ba217f7747d4",
        "358789f9-7d87-411d-919e-d597da665cbd",
        "Stoneforge Mystic",
        "2xm",
        "Double Masters",
        "31",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/4/d/4d3473d0-b46f-41f5-ac1e-ba217f7747d4.jpg",
    ),
    (
        "6fc57076-cac4-4f5e-956b-e3d77bd258b2",
        "53f7c868-b03e-4fc2-8dcf-a75bbfa3272b",
        "Dark Ritual",
        "sta",
        "Strixhaven Mystical Archive",
        "26",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/6/f/6fc57076-cac4-4f5e-956b-e3d77bd258b2.jpg",
    ),
    (
        "b281a308-ab6b-47b6-bec7-632c9aaecede",
        "edd8d1e8-be43-4c38-bb3a-83081fbaf0b5",
        "Thoughtseize",
        "2xm",
        "Double Masters",
        "109",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/b/2/b281a308-ab6b-47b6-bec7-632c9aaecede.jpg",
    ),
    (
        "3d69a3e0-6a2e-475a-964e-0affed1c017d",
        "d3a0b660-358c-41bd-9cd2-41fbf3491b1a",
        "Birds of Paradise",
        "rvr",
        "Ravnica Remastered",
        "133",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/3/d/3d69a3e0-6a2e-475a-964e-0affed1c017d.jpg",
    ),
    (
        "043b2d30-a40f-4d47-933b-80544512f9c2",
        "53236dd7-845a-444c-96d5-f41ed7325d8f",
        "Rhystic Study",
        "wot",
        "Wilds of Eldraine: Enchanting Tales",
        "25",
        "en",
        "mythic",
        "https://cards.scryfall.io/normal/front/0/4/043b2d30-a40f-4d47-933b-80544512f9c2.jpg",
    ),
    (
        "ff08e5ed-f47b-4d8e-8b8b-41675dccef8b",
        "d75b9c82-1b49-4c3e-a1b5-aeef57d6644b",
        "Cyclonic Rift",
        "2xm",
        "Double Masters",
        "47",
        "en",
        "rare",
        "https://cards.scryfall.io/normal/front/f/f/ff08e5ed-f47b-4d8e-8b8b-41675dccef8b.jpg",
    ),
    (
        "71590b6f-9f38-4c5d-8431-50e5f02f8c93",
        "fa56a5fa-ef96-404c-8fb6-d1f5fcebb52e",
        "Surrak, the Hunt Caller",
        "cmm",
        "Commander Masters",
        "326",
        "en",
        "uncommon",
        "https://cards.scryfall.io/normal/front/7/1/71590b6f-9f38-4c5d-8431-50e5f02f8c93.jpg",
    ),
]


# Os IDs numéricos dos usuários são estáveis para que as ofertas abaixo
# continuem apontando para as mesmas pessoas em execuções repetidas.
USERS = [
    (1, "danton", "danton@example.test", "Danton Homero", "Natal", "RN"),
    (2, "marina", "marina@example.test", "Marina Lima", "Fortaleza", "CE"),
    (3, "caio", "caio@example.test", "Caio Nunes", "Recife", "PE"),
    (4, "bia", "bia@example.test", "Beatriz Rocha", "João Pessoa", "PB"),
]


# O segundo campo é a posição (começando em 1) dentro de CARDS.
LISTINGS = [
    (
        1,
        2,
        "Sol Ring para troca",
        "Carta bem conservada, procuro staples de Commander.",
        None,
        "NM",
        "en",
        "troca",
    ),
    (
        2,
        3,
        "Lightning Bolt",
        "Playset disponível; preço por unidade.",
        1200,
        "SP",
        "en",
        "venda",
    ),
    (
        3,
        4,
        "Counterspell MH2",
        "Aceito venda ou troca local.",
        900,
        "NM",
        "en",
        "ambos",
    ),
    (
        4,
        5,
        "Llanowar Elves",
        "Ótima para completar o deck.",
        350,
        "SP",
        "en",
        "venda",
    ),
    (
        5,
        6,
        "Swords to Plowshares",
        "Envio por carta registrada.",
        1800,
        "NM",
        "en",
        "venda",
    ),
    (
        6,
        10,
        "Rhystic Study",
        "Busco fetch lands ou proposta em dinheiro.",
        21000,
        "NM",
        "en",
        "ambos",
    ),
]


def seed_all(db_path=None, reset: bool = False) -> None:
    """Garante schema e dados de demonstração no banco escolhido.

    Sem ``reset=True``, registros existentes são preservados e os fixtures são
    atualizados de forma idempotente. Isso permite iniciar a aplicação várias
    vezes sem destruir um catálogo já importado.
    """

    path = init_db(db_path)
    connection = get_connection(path)

    try:
        if reset:
            # A ordem respeita as relações entre ofertas, usuários e cartas.
            connection.execute("DELETE FROM wants")
            connection.execute("DELETE FROM listings")
            connection.execute("DELETE FROM users")
            connection.execute("DELETE FROM cards")

        connection.executemany(
            """
            INSERT INTO cards(
                scryfall_id,
                oracle_id,
                name,
                set_code,
                set_name,
                collector_number,
                language,
                rarity,
                image_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scryfall_id) DO UPDATE SET
                name = excluded.name,
                set_code = excluded.set_code,
                set_name = excluded.set_name,
                collector_number = excluded.collector_number,
                language = excluded.language,
                rarity = excluded.rarity,
                image_url = excluded.image_url
            """,
            CARDS,
        )

        # O seed atualiza dados públicos, mas nunca substitui uma senha que já
        # foi definida por um usuário real.
        connection.executemany(
            """
            INSERT INTO users(
                id,
                username,
                email,
                display_name,
                city,
                state
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                username = excluded.username,
                email = excluded.email,
                display_name = excluded.display_name,
                city = excluded.city,
                state = excluded.state
            """,
            USERS,
        )

        for user_id, *_ in USERS:
            current = connection.execute(
                "SELECT password_hash FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if current and current["password_hash"] is None:
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (hash_password(DEV_PASSWORD), user_id),
                )

        # Converte o scryfall_id das constantes acima no id inteiro local.
        card_ids_by_scryfall = {
            row["scryfall_id"]: row["id"]
            for row in connection.execute(
                "SELECT id, scryfall_id FROM cards"
            )
        }
        ordered_card_ids = [
            card_ids_by_scryfall[row[0]]
            for row in CARDS
        ]

        for listing_id, card_position, title, description, price_cents, condition, language, mode in LISTINGS:
            connection.execute(
                """
                INSERT INTO listings(
                    id,
                    card_id,
                    user_id,
                    title,
                    description,
                    price_cents,
                    condition,
                    language,
                    mode,
                    contact_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    card_id = excluded.card_id,
                    user_id = excluded.user_id,
                    title = excluded.title,
                    description = excluded.description,
                    price_cents = excluded.price_cents,
                    condition = excluded.condition,
                    language = excluded.language,
                    mode = excluded.mode
                """,
                (
                    listing_id,
                    ordered_card_ids[card_position - 1],
                    ((listing_id - 1) % 4) + 1,
                    title,
                    description,
                    price_cents,
                    condition,
                    language,
                    mode,
                    "#contato",
                ),
            )

        # O desejo demonstrativo é inserido uma única vez por usuário e carta.
        connection.execute(
            """
            INSERT INTO wants(
                card_id,
                user_id,
                max_price_cents,
                desired_condition,
                mode
            ) VALUES (?, 1, 22000, 'SP', 'ambos')
            ON CONFLICT(card_id, user_id) DO NOTHING
            """,
            (ordered_card_ids[9],),
        )

        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    seed_all()
    print("Dados de demonstração garantidos no banco.")
