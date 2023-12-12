import boto3
import json
import os
import psycopg2

from django.db.backends.postgresql import base


class DatabaseWrapper(base.DatabaseWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.most_recent_password = None

    def get_most_recent_password(self):
        if self.most_recent_password is None:
            self.refresh_password()
        return self.most_recent_password

    def refresh_password(self):
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name="secretsmanager", region_name="us-east-1"
            )
            secrets = client.get_secret_value(SecretId=os.environ["DB_SECRET"])
            self.most_recent_password = json.loads(secrets["SecretString"])["password"]
        except Exception as e:
            raise Exception("Failed to retrieve credentials from Secrets Manager", e)

    def get_connection_params(self):
        settings_dict = self.settings_dict

        conn_params = {
            "database": settings_dict["NAME"] or "postgres",
            **settings_dict["OPTIONS"],
        }
        conn_params.pop("isolation_level", None)

        if settings_dict["USER"]:
            conn_params["user"] = settings_dict["USER"]

        if settings_dict["HOST"]:
            conn_params["host"] = settings_dict["HOST"]

        if settings_dict["PORT"]:
            conn_params["port"] = settings_dict["PORT"]

        conn_params["password"] = self.get_most_recent_password()

        return conn_params

    def _cursor(self, name=None):
        try:
            return super()._cursor(name)
        except psycopg2.OperationalError as e:
            # Catch the specific error related to password authentication failure
            if "password authentication failed for user" in str(e):
                # Refresh the password and retry the connection
                self.refresh_password()
                return super()._cursor(name)
            else:
                raise e
