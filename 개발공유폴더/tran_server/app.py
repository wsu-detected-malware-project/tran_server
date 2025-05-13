from flask import Flask, request, send_file, render_template, jsonify, make_response, redirect
import requests
import tempfile
import os
from datetime import datetime, timedelta, timezone
import threading
import tempfile
from collections import Counter
from werkzeug.utils import secure_filename
import jwt_token
import jwt
from io import BytesIO
from check_link import register_check_server_routes
from secret.key import SECRET_KEY

app = Flask(__name__)

register_check_server_routes(app)

DEPLOY_URL = "http://localhost:7070"
EXTERNAL_SERVER_URL = 'http://localhost:8080/upload'
USERNAME = None
KEY = SECRET_KEY
KST = timezone(timedelta(hours=9))
UTC = timezone.utc
upload_timestamps = []
lock = threading.Lock()

@app.route('/')
def index():
    token = request.cookies.get('token')

    if token:
        try:
            data = jwt_token.decode_token(token)
            username = data['username']

            if (username == 'admin'):
                return render_template('/index.html')
            else:
                return render_template('/login.html')
            
        except jwt.ExpiredSignatureError:
            return render_template('/login.html')
        except jwt.InvalidTokenError:
            return render_template('/login.html')
    
    return render_template('/login.html')

@app.route('/upload-stats')
def upload_stats():
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(minutes=10)

    with lock:
        recent = [t for t in upload_timestamps if t > one_hour_ago]

    # 분 단위로 그룹화
    time_buckets = [t.replace(second=0, microsecond=0) for t in recent]
    counter = Counter(time_buckets)

    labels = []
    values = []
    for i in range(60):
        minute = one_hour_ago + timedelta(minutes=i)
        kst_minute = minute.astimezone(KST)
        labels.append(kst_minute.strftime('%H:%M'))  # 한국 시간 표시
        values.append(counter.get(minute.replace(second=0, microsecond=0), 0))

    return jsonify({'labels': labels, 'values': values})


@app.route('/upload', methods=['POST'])
def upload():
    
    if 'file' not in request.files:
        return "전송 된 파일 없음", 400
    file_storage = request.files.getlist('file')
    
    if (len(file_storage) != 1):
        return '여러개의 파일 감지', 400

    uploaded_file = file_storage[0]
    
    if uploaded_file.filename == '':
        return "선택 된 파일 없음", 400
    
    safe_file = secure_filename(uploaded_file.filename)
    
    with lock:
        upload_timestamps.append(datetime.now(UTC))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_in:
        uploaded_file.save(temp_in.name)

        with open(temp_in.name, 'rb') as f:
            files = {'file': (safe_file, f, 'text/csv')}
            response = requests.post(EXTERNAL_SERVER_URL, files=files)

    os.remove(temp_in.name)  # 임시 입력 파일 삭제

    if response.status_code != 200:
        return f"External server error: {response.status_code}", 502

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_out:
        temp_out.write(response.content)
        temp_out_path = temp_out.name

    return send_file(temp_out_path, as_attachment=True, download_name='result.csv')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        data = request.form.get('password')

        if data != KEY:
            return render_template('/login.html', error='틀렸습니다.')
        
        username = 'admin'
        new_token = jwt_token.create_token(username)

        resp = make_response(redirect('/'))
        resp.set_cookie('token', new_token)

        return resp
    return render_template('/login.html')

@app.route('/check-update', methods=['GET'])
def check_update():
    client_version = request.args.get('version')
    try:
        manifest_url = f"{DEPLOY_URL}/manifest"
        resp = requests.get(manifest_url)
        resp.raise_for_status()
        manifest = resp.json()
        latest_version = manifest.get("version")

        if client_version != latest_version:
            return jsonify({
                "update_required": True,
                "latest_version": latest_version,
                "release_notes": manifest.get("release_notes", ""),
                "files": [
                    {
                        "path": f["path"],
                        "url": f"/download/{f['path']}"
                    } for f in manifest.get("files", [])
                ]
            })
        else:
            return jsonify({"update_required": False})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<path:filename>', methods=['GET'])
def download_file(filename):
    try:
        # 배포 서버 API를 통해 파일 요청
        file_url = f"{DEPLOY_URL}/file/{filename}"
        resp = requests.get(file_url, stream=True)
        if resp.status_code == 200:
            return send_file(BytesIO(resp.content),
                             download_name=filename,
                             as_attachment=True)
        else:
            return "File not found", 404
    except Exception as e:
        return f"Error: {e}", 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)