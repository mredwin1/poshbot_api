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
        return db


def check_availability():
    email_db = _connect_to_db()
    cursor = email_db.cursor()

    cursor.execute(f"SELECT COUNT(*) FROM yahoo_edwincruz WHERE status = 'free'")

    count = cursor.fetchone()[0]

    return count


def get_emails(quantity):
    email_db = _connect_to_db()
    cursor = email_db.cursor()

    cursor.execute(f"SELECT id, mail, pass FROM yahoo_edwincruz WHERE status = 'free' LIMIT {quantity}")

    return cursor.fetchall()


def update_email_status(email_id, status):
    email_db = _connect_to_db()
    cursor = email_db.cursor()

    cursor.execute(f"UPDATE yahoo_edwincruz SET status = '{status}' WHERE id = {email_id}")

    cursor.execute("COMMIT")
