import threading
import boto3
import json
import os
import psycopg2
from django.db.backends.postgresql import base


class DatabaseWrapper(base.DatabaseWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()

    @staticmethod
    def get_new_password():
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name="secretsmanager", region_name="us-east-1"
            )
            secrets = client.get_secret_value(SecretId=os.environ["DB_SECRET"])
            return json.loads(secrets["SecretString"])["password"]
        except Exception as e:
            raise Exception("Failed to retrieve credentials from Secrets Manager", e)

    def get_connection_params(self):
        params = super().get_connection_params()
        with self.lock:
            params["password"] = self.get_new_password()
        return params

    def _cursor(self, name=None):
        try:
            return super()._cursor(name)
        except psycopg2.OperationalError as e:
            if "password authentication failed for user" in str(e):
                with self.lock:
                    self.close_if_unusable_or_obsolete()
                    self.connection = None
                    self.connect()
                return super()._cursor(name)
            else:
                raise e
