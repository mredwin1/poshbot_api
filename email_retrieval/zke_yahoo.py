import mysql.connector
import os
import imaplib
import email


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

    cursor.execute(f"SELECT id, mail, pass, imap FROM yahoo_edwincruz WHERE status = 'free' LIMIT {quantity}")

    return cursor.fetchall()


def update_email_status(email_ids, status):
    email_db = _connect_to_db()
    cursor = email_db.cursor()

    email_ids_str = ",".join(str(email_id) for email_id in email_ids)
    cursor.execute(f"UPDATE yahoo_edwincruz SET status = '{status}' WHERE id IN ({email_ids_str})")

    cursor.execute("COMMIT")


def check_for_email(sender_email, email_address, password, subject_keyword, date_filter=None, imap_server="imap.mail.yahoo.com", port=993):
    try:
        # Connect to the IMAP server
        mail = imaplib.IMAP4_SSL(imap_server, port)

        # Log in to the email account
        mail.login(email_address, password)

        # Select the mailbox you want to search in (e.g., 'INBOX')
        mail.select("INBOX")

        # Construct the search query based on filters
        search_query = f'FROM "{sender_email}" SUBJECT "{subject_keyword}"'
        if date_filter:
            formatted_date_filter = date_filter.strftime("%d-%b-%Y")
            search_query += f' SENTSINCE {formatted_date_filter}'

        # Search for emails based on the constructed query
        result, data = mail.search(None, search_query)

        if result == "OK":
            email_ids = data[0].split()
            for email_id in email_ids:
                # Fetch the email based on its ID
                result, msg_data = mail.fetch(email_id, "(RFC822)")
                if result == "OK":
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Check if the sender matches the expected sender
                    from_address = msg.get("From")
                    if sender_email.lower() in from_address.lower():
                        return msg  # Return the matching email object
        else:
            print("Error searching for emails.")

        # Log out and close the connection
        mail.logout()

    except Exception as e:
        print("An error occurred:", str(e))

    return None
