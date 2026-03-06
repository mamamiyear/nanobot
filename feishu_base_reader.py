#!/usr/bin/env python3
import requests
import json
import os
from urllib.parse import urlparse, parse_qs

# 从环境变量获取飞书应用信息
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET')

if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
    print("错误：请设置FEISHU_APP_ID和FEISHU_APP_SECRET环境变量")
    exit(1)

def get_feishu_token():
    """获取飞书API访问令牌"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    
    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()['tenant_access_token']

def parse_base_url(url):
    """解析飞书多维表格URL，提取base_id和table_id"""
    parsed = urlparse(url)
    path_parts = parsed.path.split('/')
    base_id = path_parts[2] if len(path_parts) >=3 else None
    
    query_params = parse_qs(parsed.query)
    table_id = query_params.get('table', [None])[0]
    
    if not base_id or not table_id:
        print("错误：无法从URL中提取base_id或table_id")
        exit(1)
    
    return base_id, table_id

def get_table_records(base_id, table_id, token):
    """获取多维表格指定表的所有记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_id}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    records = []
    page_token = ""
    
    while True:
        params = {"page_token": page_token, "page_size": 100}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        records.extend(data['data']['items'])
        page_token = data['data'].get('page_token', '')
        
        if not page_token:
            break
    
    return records

def get_table_fields(base_id, table_id, token):
    """获取多维表格指定表的字段信息"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base_id}/tables/{table_id}/fields"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()['data']['items']

def main():
    import sys
    if len(sys.argv) != 2:
        print("用法：python feishu_base_reader.py <飞书多维表格URL>")
        exit(1)
    
    url = sys.argv[1]
    base_id, table_id = parse_base_url(url)
    
    print(f"正在读取多维表格：base_id={base_id}, table_id={table_id}")
    
    token = get_feishu_token()
    fields = get_table_fields(base_id, table_id, token)
    records = get_table_records(base_id, table_id, token)
    
    # 构建字段映射（field_id到field_name）
    field_map = {field['field_id']: field['field_name'] for field in fields}
    
    # 输出表格内容
    print(f"\n表格包含 {len(records)} 条记录，字段信息：")
    for field in fields:
        print(f"  - {field['field_name']} ({field['field_id']}): {field['type']}")
    
    print("\n记录内容：")
    for i, record in enumerate(records, 1):
        print(f"\n--- 记录 {i} ---")
        for field_id, value in record['fields'].items():
            field_name = field_map.get(field_id, field_id)
            print(f"  {field_name}: {value}")

if __name__ == "__main__":
    main()