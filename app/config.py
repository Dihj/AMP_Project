import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-12345')
    
    # Path to external data (Points to external_data/ relative to project root)
    # You can also use an absolute path like: "/var/data/climate_data"
    BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    EXTERNAL_DATA_DIR = os.environ.get(
        'DATA_DIR', 
        os.path.abspath(os.path.join(BASE_DIR, '..', 'external_data'))
    )


    