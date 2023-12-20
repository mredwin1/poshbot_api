import boto3
import json
import logging
import os
import psycopg2
import threading

from django.db.backends.postgresql import base


logger = logging.getLogger(__name__)


class DatabaseWrapper(base.DatabaseWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()

    @staticmethod
    def get_new_credentials():
        try:
            session = boto3.session.Session()
            client = session.client(
                service_name="secretsmanager", region_name="us-east-1"
            )
            secret = client.get_secret_value(SecretId=os.environ["DB_SECRET"])
            return json.loads(secret["SecretString"])["password"]
        except Exception as e:
            raise Exception("Failed to retrieve credentials from Secrets Manager", e)

    def get_connection_params(self):
        params = super().get_connection_params()
        credentials = self.get_new_credentials()

        params["user"] = credentials["username"]
        params["password"] = credentials["password"]
        return params

    def _cursor(self, name=None):
        try:
            return super()._cursor(name)
        except psycopg2.OperationalError as e:
            if "password authentication failed for user" in str(e):
                with self.lock:
                    # Close the current connection if it exists
                    if self.connection is not None:
                        self.connection.close()
                        self.connection = None

                    # Refresh the password and re-establish the connection
                    self.connect()
                    return super()._cursor(name)
            else:
                raise e
