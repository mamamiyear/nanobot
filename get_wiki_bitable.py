import os
import requests

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")

def get_tenant_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload)
    return resp.json()["tenant_access_token"]

def get_wiki_bitable(wiki_id):
    token = get_tenant_token()
    url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?token={wiki_id}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    print("wiki节点信息:", resp.json())
    node_info = resp.json()["data"]["node"]
    if node_info["obj_type"] == "bitable":
        bitable_token = node_info["obj_token"]
        print(f"找到嵌入的多维表格，base_id: {bitable_token}")
        # 再获取这个base下的所有表
        table_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{bitable_token}/tables"
        resp = requests.get(table_url, headers=headers)
        tables = resp.json()["data"]["items"]
        print(f"\n该多维表格包含 {len(tables)} 个数据表：")
        for table in tables:
            print(f"- 表名：{table['name']}，表ID：{table['table_id']}")

if __name__ == "__main__":
    get_wiki_bitable("LdV6wmUL3idymykTA0bcX8RZnqg")
