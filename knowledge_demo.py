import json
import requests

from volcengine.auth.SignerV4 import SignerV4
from volcengine.base.Request import Request
from volcengine.Credentials import Credentials

account_id = "kb-service-83ec26c52770a92a"
g_knowledge_base_domain = "api-knowledgebase.mlp.cn-beijing.volces.com"
apikey = "56d82040-85c7-4701-8f87-734985e27909"
## 纯文本时的query
query = "Halo平台是什么？它的技术架构怎么样？"
## 当query包含图片时，使用以下格式
# query = [
#     {
#         "text": "你的问题",
#         "type": "text"
#     },
#     {
#         "image_url": {
#             "url": "请传入可访问的图片URL或者Base64编码"
#         },
#         "type": "image_url"
#     }
# ]

def prepare_request(method, path, params=None, data=None, doseq=0):
    if params:
        for key in params:
            if (
                    isinstance(params[key], int)
                    or isinstance(params[key], float)
                    or isinstance(params[key], bool)
            ):
                params[key] = str(params[key])
            elif isinstance(params[key], list):
                if not doseq:
                    params[key] = ",".join(params[key])
    r = Request()
    r.set_shema("http")
    r.set_method(method)
    r.set_connection_timeout(10)
    r.set_socket_timeout(10)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=UTF-8",
        "Host": g_knowledge_base_domain,
        'Authorization': f'Bearer {apikey}'
    }
    r.set_headers(headers)
    if params:
        r.set_query(params)
    r.set_host(g_knowledge_base_domain)
    r.set_path(path)
    if data is not None:
        r.set_body(json.dumps(data))
    return r


def knowledge_service_chat():
    method = "POST"
    path = "/api/knowledge/service/chat"
    request_params = {
    "service_resource_id": "kb-service-83ec26c52770a92a",
    "messages":[
        {
            "role": "user",
            "content":query
        }
    ],
    "stream": False
    }

    info_req = prepare_request(method=method, path=path, data=request_params)
    rsp = requests.request(
        method=info_req.method,
        url="http://{}{}".format(g_knowledge_base_domain, info_req.path),
        headers=info_req.headers,
        data=info_req.body
    )
    rsp.encoding = "utf-8"
    print(rsp.text)
    return

if __name__ == "__main__":
    knowledge_service_chat()