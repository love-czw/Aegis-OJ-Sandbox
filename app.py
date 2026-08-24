from flask import Flask, request, jsonify, render_template
import subprocess
import time
import json

app = Flask(__name__)

# 路由 1：返回酷炫的前端页面
@app.route('/')
def index():
    return render_template('index.html')

# 路由 2：刚才的核心 API 逻辑，保持不变
@app.route('/api/predict', methods=['GET'])
def predict():
    start_time = time.time()
    feature1 = request.args.get('f1', '1.0')
    feature2 = request.args.get('f2', '-2.0')
    feature3 = request.args.get('f3', '3.0')
    input_data = f"{feature1} {feature2} {feature3}"

    process = subprocess.run(['./sandbox_api'], input=input_data, capture_output=True, text=True)
    process_time = round((time.time() - start_time) * 1000, 2)
    
    logs = process.stdout.strip().split('\n')
    ai_result = {}
    for line in reversed(logs):
        if line.startswith('{'):
            ai_result = json.loads(line)
            break

    return jsonify({
        "process_time_ms": process_time,
        "ai_engine_output": ai_result,
        "sandbox_logs": [log for log in logs if not log.startswith('{')]
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888)
