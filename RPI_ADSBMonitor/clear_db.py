import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

SERVICE_ACCOUNT_KEY_PATH = './flight-key.json'
DATABASE_URL = 'https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app/'

def initialize_firebase():
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })

def clear_path(path='/'):
    ref = db.reference(path)
    ref.set()
    print(f"Cleared data at path: {path}")

if __name__ == "__main__":
    initialize_firebase()

    # Modify this to the path you want to clear, or leave as '/' to clear the whole DB
    path_to_clear = '/'  # e.g., '/users' or '/' to clear everything
    clear_path(path_to_clear)
