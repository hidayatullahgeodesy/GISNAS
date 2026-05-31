import os

path = r'c:\docker\gisnas\gisnas_sketsa\sketsa_utils.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

new_utils = """
def api_post_file(url, file_path):
    import urllib.request
    import uuid
    import os

    boundary = uuid.uuid4().hex
    filename = os.path.basename(file_path)
    
    with open(file_path, 'rb') as f:
        file_data = f.read()

    body = (
        f"--{boundary}\\r\\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\\r\\n'
        f"Content-Type: application/octet-stream\\r\\n\\r\\n"
    ).encode('utf-8') + file_data + f"\\r\\n--{boundary}--\\r\\n".encode('utf-8')

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "GISNAS-Sketsa/1.0"
        },
        method="POST",
    )
    
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read().decode("utf-8")
        import json
        return json.loads(raw) if raw.strip() else {"status": resp.status}

def api_download_file(url, target_path):
    import urllib.request
    import shutil
    
    req = urllib.request.Request(url, headers={"User-Agent": "GISNAS-Sketsa/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(target_path, 'wb') as out_file:
        shutil.copyfileobj(resp, out_file)
"""

content += '\n' + new_utils

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Done modifying sketsa_utils.py')
