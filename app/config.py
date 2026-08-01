import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-12345')
    DATA_DIR = os.environ.get('DATA_DIR', './data')


    