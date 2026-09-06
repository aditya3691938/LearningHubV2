import os
from app import create_app
from app.seed import init_db_and_seed

app = create_app()

if __name__ == '__main__':
    init_db_and_seed(app)
    env = os.environ.get('FLASK_ENV', 'development')
    port = int(os.environ.get('PORT', 5000))
    
    if env == 'production':
        from waitress import serve
        print(f"Starting Aditya Learning Hub in PRODUCTION mode on port {port} using Waitress WSGI...")
        serve(app, host='0.0.0.0', port=port)
    else:
        print(f"Starting Aditya Learning Hub in DEVELOPMENT mode on http://localhost:{port}...")
        app.run(host='0.0.0.0', port=port, debug=True)

