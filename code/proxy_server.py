from flask import Flask, request, Response
import requests
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

LINGXING_API_BASE = "https://openapi.lingxing.com"

@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE'])
def proxy(path):
    try:
        target_url = f"{LINGXING_API_BASE}/{path}"
        logger.info(f"转发 {request.method} {target_url}")

        params = request.args.to_dict()

        headers = {}
        for k, v in request.headers:
            kl = k.lower()
            if kl not in ['host', 'connection', 'keep-alive', 'proxy-authenticate',
                         'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade']:
                headers[k] = v

        data = request.get_data() if request.method != 'GET' else None

        response = requests.request(
            method=request.method,
            url=target_url,
            params=params,
            data=data,
            headers=headers,
            timeout=30,
            stream=False
        )

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding',
                           'connection', 'keep-alive', 'proxy-authenticate',
                           'proxy-authorization', 'te', 'trailers', 'upgrade']

        resp_headers = []
        for k, v in response.headers.items():
            if k.lower() not in excluded_headers:
                resp_headers.append((k, v))

        return Response(
            response.content,
            status=response.status_code,
            headers=resp_headers
        )

    except Exception as e:
        logger.error(f"代理失败: {str(e)}")
        return Response(
            json.dumps({"error": str(e), "msg": "转发失败"}),
            status=500,
            mimetype='application/json'
        )

@app.route('/health')
def health():
    return {"status": "ok"}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5007, threaded=True)
