import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

SERVICE_ACCOUNT_KEY_PATH = './flightkey.json'
DATABASE_URL = 'https://rpi-flight-tracker-default-rtdb.europe-west1.firebasedatabase.app/'

def initialize_firebase():
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
    firebase_admin.initialize_app(cred, {
        'databaseURL': DATABASE_URL
    })

def clear_path(path='/'):
    ref = db.reference(path)
    ref.set(0)
    print(f"Cleared data at path: {path}")

if __name__ == "__main__":
    initialize_firebase()
    
    path_to_clear = '/'  
    clear_path(path_to_clear)
