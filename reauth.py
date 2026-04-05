"""Google OAuth 再認証スクリプト"""
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
creds_path = os.path.join(SCRIPT_DIR, "credentials.json")
token_path = os.path.join(SCRIPT_DIR, "token.json")

print("ブラウザを開いて Google 認証を行います...")
flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
creds = flow.run_local_server(port=0, open_browser=True)

with open(token_path, "w") as f:
    f.write(creds.to_json())

print("認証完了！token.json を更新しました。")
