# coding=utf-8
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json
import requests
from pprint import pprint


class GoogleAPI:
    def __init__(self):
        self.credentials = None
        self.credentials: Credentials

    @staticmethod
    def refresh_token_is_valid(refresh_token: str) -> bool:
        result = requests.get(
            "https://www.googleapis.com/oauth2/v1/tokeninfo?access_token="
            + refresh_token,
            timeout=10,
        )
        return result.status_code == 200

    def setup_credentials(self, refresh_token: str):
        with open("google_client_secret.json", "r", encoding="utf-8") as f:
            secret_dict = json.load(f)
        if not self.refresh_token_is_valid(refresh_token):
            raise Exception("Refresh token has expired or invalid.")
        self.credentials = Credentials(
            client_id=secret_dict["web"]["client_id"],
            quota_project_id=secret_dict["web"]["project_id"],
            token_uri=secret_dict["web"]["token_uri"],
            client_secret=secret_dict["web"]["client_secret"],
            token=secret_dict["token"],
            refresh_token=refresh_token,
            scopes=['https://www.googleapis.com/auth/userinfo.email',
                    'https://www.googleapis.com/auth/userinfo.profile']
        )

    def get_basic_data_from_google(self) -> dict:
        if self.credentials is None:
            raise RuntimeError(
                'Credentials not set. Run "setup_credentials" before using this method.'
            )
        oauth_obj = build("people", "v1", credentials=self.credentials)
        # result = oauth_obj.userinfo().get().execute()
        result = oauth_obj.people().get(resourceName='people/me',
                                        personFields='emailAddresses,names,photos').execute()
        formatted_result = {
            "email_address": result.get("emailAddresses", [])[0].get("value", ""),
            "name": result.get("names", [])[0].get("displayName", ""),
            "photo": result.get("photos", [])[0].get("url", "").split("=")[0],
        }
        return formatted_result


if __name__ == "__main__":
    test_obj = GoogleAPI()
    test_obj.setup_credentials(input("Enter refresh token: "))
    pprint(test_obj.get_basic_data_from_google())
