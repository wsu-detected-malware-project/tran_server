from flask import Blueprint, Response
import requests

server_bp = Blueprint('check_link', __name__)

EXTERNAL_SERVER_URL = 'http://localhost:8080/health'

@server_bp.route('/check_link')
def check():
    try:
        res = requests.get(EXTERNAL_SERVER_URL)

        if res.status_code == 200:
            return 'OK', 200
        else:
            return 'Unavailable', 503
    except:
        return 'Error', 503

def register_check_server_routes(app):
    app.register_blueprint(server_bp)