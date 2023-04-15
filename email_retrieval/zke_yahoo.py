import mysql.connector
import os


def _connect_to_db():
    db = mysql.connector.connect(
        host=os.environ['ZKE_YAHOO_HOST'],
        port=os.environ['ZKE_YAHOO_PORT'],
        user=os.environ['ZKE_YAHOO_USER'],
        password=os.environ['ZKE_YAHOO_PASSWORD'],
        database=os.environ['ZKE_YAHOO_DATABASE']
    )

    if db.is_connected():
        return db.cursor()


def check_availability():
    cursor = _connect_to_db()

    cursor.execute(f"SELECT COUNT(*) FROM yahoo_edwincruz WHERE status = 'free'")

    count = cursor.fetchone()[0]

    return count


def get_email():
    cursor = _connect_to_db()

    cursor.execute("SELECT id, mail, pass, status FROM yahoo_edwincruz WHERE status = 'free' LIMIT 1")

    return cursor.fetchall()


def update_email_status(email_id, status):
    cursor = _connect_to_db()

    cursor.execute(f"UPDATE yahoo_edwincruz SET status = '{status}' WHERE id = {email_id}")

    cursor.execute("COMMIT")
