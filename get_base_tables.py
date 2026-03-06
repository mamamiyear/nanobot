import os
import requests

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")

def get_tenant_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, json=payload)
    return resp.json()["tenant_access_token"]

def get_base_tables(base_id):
    token = get_tenant_token()
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_id}/tables"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    print("响应内容:", resp.json())
    tables = resp.json()["data"]["items"]
    print(f"该多维表格包含 {len(tables)} 个数据表：")
    for table in tables:
        print(f"- 表名：{table['name']}，表ID：{table['table_id']}")

if __name__ == "__main__":
    get_base_tables("LdV6wmUL3idymykTA0bcX8RZnqg")
