import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    "dbname": "test",
    "user": "postgres",
    "password": " ", # вставить свой пароль от пользователя
    "host": "localhost",
    "port": 5432,
}


def get_connection():
    """Возвращает соединение с БД."""
    return psycopg2.connect(**DB_CONFIG)


# -----------------------------------------------------------------------------
# 1. Функция, создающая структуру БД (таблицы)
# -----------------------------------------------------------------------------
def create_db_and_tables():
    # Создаём базу, если её нет
    conn_tmp = psycopg2.connect(dbname="postgres", user=DB_CONFIG["user"],
                                password=DB_CONFIG["password"], host=DB_CONFIG["host"],
                                port=DB_CONFIG["port"])
    conn_tmp.autocommit = True
    cur = conn_tmp.cursor()
    try:
        cur.execute(f"CREATE DATABASE {DB_CONFIG['dbname']}")
    except psycopg2.errors.DuplicateDatabase:
        pass
    cur.close()
    conn_tmp.close()

    # Создаём таблицы в базе
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id SERIAL PRIMARY KEY,
                    first_name VARCHAR(50) NOT NULL,
                    last_name  VARCHAR(50) NOT NULL,
                    email      VARCHAR(100) NOT NULL UNIQUE
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS client_phones (
                    phone_id   SERIAL PRIMARY KEY,
                    client_id  INTEGER NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
                    phone      VARCHAR(20) NOT NULL,
                    UNIQUE(client_id, phone)
                );
            """)
        conn.commit()


# -----------------------------------------------------------------------------
# 2. Функция, позволяющая добавить нового клиента
# -----------------------------------------------------------------------------
def add_client(conn, first_name, last_name, email, phones=None):
    """
    Добавляет клиента и сразу его телефоны (если переданы).
    phones: список строк или None.
    Возвращает client_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO clients (first_name, last_name, email) VALUES (%s, %s, %s) RETURNING client_id;",
            (first_name, last_name, email),
        )
        client_id = cur.fetchone()[0]

        if phones:
            for phone in phones:
                try:
                    cur.execute(
                        "INSERT INTO client_phones (client_id, phone) VALUES (%s, %s);",
                        (client_id, phone),
                    )
                except psycopg2.IntegrityError:
                    conn.rollback()
                    continue
        conn.commit()
    return client_id


# -----------------------------------------------------------------------------
# 3. Функция, позволяющая добавить телефон для существующего клиента
# -----------------------------------------------------------------------------
def add_phone(conn, client_id, phone):
    """Добавляет телефон клиенту. Возвращает True при успехе, False если телефон уже есть."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO client_phones (client_id, phone) VALUES (%s, %s);",
                (client_id, phone),
            )
            conn.commit()
            return True
        except psycopg2.IntegrityError:
            conn.rollback()
            return False


# -----------------------------------------------------------------------------
# 4. Функция, позволяющая изменить данные о клиенте
# -----------------------------------------------------------------------------
def update_client(conn, client_id, first_name=None, last_name=None, email=None):
    """Частичное обновление данных клиента. Возвращает True, если строка обновлена."""
    parts = []
    values = []

    if first_name is not None:
        parts.append("first_name = %s")
        values.append(first_name)
    if last_name is not None:
        parts.append("last_name = %s")
        values.append(last_name)
    if email is not None:
        parts.append("email = %s")
        values.append(email)

    if not parts:
        return False

    values.append(client_id)
    sql = f"UPDATE clients SET {', '.join(parts)} WHERE client_id = %s;"

    with conn.cursor() as cur:
        cur.execute(sql, values)
        conn.commit()
        return cur.rowcount > 0


# -----------------------------------------------------------------------------
# 5. Функция, позволяющая удалить телефон для существующего клиента
# -----------------------------------------------------------------------------
def delete_phone(conn, phone_id):
    """Удаляет телефон по phone_id. Возвращает True, если удалён хотя бы 1 строка."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM client_phones WHERE phone_id = %s;", (phone_id,))
        conn.commit()
        return cur.rowcount > 0


# -----------------------------------------------------------------------------
# 6. Функция, позволяющая удалить существующего клиента
# -----------------------------------------------------------------------------
def delete_client(conn, client_id):
    """Удаляет клиента (и все его телефоны из-за ON DELETE CASCADE)."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM clients WHERE client_id = %s;", (client_id,))
        conn.commit()
        return cur.rowcount > 0


# -----------------------------------------------------------------------------
# 7. Функция, позволяющая найти клиента по его данным: имени, фамилии, email или телефону
# -----------------------------------------------------------------------------
def find_clients(conn, first_name=None, last_name=None, email=None, phone=None):
    """
    Поиск клиентов по любому из полей (поддерживается частичное совпадение).
    Возвращает список словарей с client_id, именами, email и списком телефонов.
    """
    conditions = []
    values = []

    if first_name:
        conditions.append("c.first_name ILIKE %s")
        values.append(f"%{first_name}%")
    if last_name:
        conditions.append("c.last_name ILIKE %s")
        values.append(f"%{last_name}%")
    if email:
        conditions.append("c.email ILIKE %s")
        values.append(f"%{email}%")
    if phone:
        # Поиск по телефону через JOIN
        conditions.append("cp.phone ILIKE %s")
        values.append(f"%{phone}%")

    if not conditions:
        return []

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT c.client_id, c.first_name, c.last_name, c.email, ARRAY_AGG(cp.phone) AS phones
        FROM clients c
        LEFT JOIN client_phones cp ON c.client_id = cp.client_id
        WHERE {where_clause}
        GROUP BY c.client_id;
    """

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, values)
        return cur.fetchall()


# Вспомогательная функция для красивого вывода результата поиска
def print_clients(clients):
    if not clients:
        print("Клиенты не найдены.")
        return
    for c in clients:
        phones_str = ", ".join(c["phones"]) if c["phones"] and c["phones"][0] is not None else "нет телефонов"
        print(f"{c['first_name']} {c['last_name']} ({c['email']}) — телефоны: {phones_str}")


# =============================================================================
# ДЕМО: демонстрация работы всех функций
# =============================================================================
if __name__ == "__main__":
    # 1. Создаём БД и таблицы (безопасно запускать повторно)
    create_db_and_tables()

    with get_connection() as conn:
        print("=== Добавляем клиентов (функция add_client) ===")
        id_ivan = add_client(conn, "Иван", "Петров", "ivan@example.com")
        id_anna = add_client(conn, "Анна", "Сидорова", "anna@test.ru", ["+79001112233"])
        id_oleg = add_client(conn, "Олег", "Кузнецов", "oleg@mail.ru", ["+79990001122", "+79993334455", "+79996667788"])
        print(f"Созданы клиенты с ID: {id_ivan}, {id_anna}, {id_oleg}\n")

        print("=== Поиск по email (функция find_clients) ===")
        found = find_clients(conn, email="anna@test.ru")
        print_clients(found)
        print()

        print("=== Поиск по фамилии (функция find_clients) ===")
        by_surname = find_clients(conn, last_name="Петров")
        print_clients(by_surname)
        print()

        print("=== Поиск по телефону (функция find_clients) ===")
        by_phone = find_clients(conn, phone="+79993334455")
        print_clients(by_phone)
        print()

        print("=== Добавляем телефон существующему клиенту (функция add_phone) ===")
        ok = add_phone(conn, id_ivan, "+79998887766")
        print("Телефон добавлен:", ok)
        # Пробуем добавить дубликат
        ok_dup = add_phone(conn, id_anna, "+79001112233")
        print("Попытка добавить дубликат телефона:", "успех" if ok_dup else "проигнорировано (уже есть)\n")

        print("=== Изменяем данные клиента (функция update_client) ===")
        updated = update_client(conn, id_ivan, last_name="Иванов")
        print("Клиент обновлён:", updated)
        print()

        print("=== Удаляем телефон (функция delete_phone) ===")
        # Получаем ID телефона для удаления
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT phone_id FROM client_phones WHERE client_id = %s LIMIT 1;", (id_oleg,))
            row = cur.fetchone()
        if row:
            deleted = delete_phone(conn, row["phone_id"])
            print("Телефон удалён:", deleted)
        else:
            print("Не удалось найти телефон для удаления.")
        print()

        print("=== Удаляем клиента (функция delete_client) ===")
        deleted_client = delete_client(conn, id_oleg)
        print("Клиент удалён:", deleted_client)
        # Проверяем, что телефоны тоже исчезли
        after_delete = find_clients(conn, last_name="Кузнецов")
        print("После удаления поиск по фамилии 'Кузнецов':")
        print_clients(after_delete)
        print()

        print("=== Финальный список всех клиентов ===")
        all_clients = find_clients(conn)
        print_clients(all_clients)
