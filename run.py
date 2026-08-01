import argparse
from app import create_app

app = create_app()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run the Weather Dashboard Flask App")
    parser.add_argument('--port', type=int, default=5000, help="Port to run the application on (Default: 5000)")
    parser.add_argument('--host', type=str, default='127.0.0.1', help="Host IP address (Default: 127.0.0.1)")
    parser.add_argument('--debug', action='store_true', help="Run in debug mode")

    args = parser.parse_args()

    print(f"Starting dashboard server on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)

    