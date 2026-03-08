
import json
from volcengine.viking_knowledgebase import VikingKnowledgeBaseService, CollectionVersion

collection_name = "HaloKnowledgeBase"

project_name = "ark_project_20250722_halo"
query = "Halo平台是什么？它的技术架构怎么样？"
image_query = "请传入可访问的图片URL或者Base64编码"

account = "halo_account"
account_id = "2105201732"
g_knowledge_base_domain = "api-knowledgebase.mlp.cn-beijing.volces.com"
sk = "3c2f8f57a19e70666235a6233fa52377"
ak = f"service_account={account};"
ak += f"main_account_id={account_id};"
ak += "sts_type=samlSts;"
ak += f"volc_host={g_knowledge_base_domain}"
viking_kb_service = VikingKnowledgeBaseService(host="paas-gw-volc.byted.org", scheme="https", ak=ak, sk=sk)

def create_collection():
    collection = viking_kb_service.create_collection("ooo_collection", version=CollectionVersion.UltimateVersion, project=project_name)
    print(f"create collection: {collection.collection_name} successfully")

def list_collections():
    collections = viking_kb_service.list_collections(project=project_name)
    for collection in collections:
        print(collection)

def delete_collection():
    viking_kb_service.drop_collection("ooo_collection", project=project_name)
    print("delete collection finished")

def get_collection():
    try:
        collection = viking_kb_service.get_collection(collection_name, project=project_name)
        print("get collection:", collection.collection_name)
    except Exception as e:
        print(f"get collection failed: {e}")

def search_knowledge(): 
    ret = viking_kb_service.search_knowledge(collection_name=collection_name, query=query, project=project_name)
    print(json.dumps(ret, ensure_ascii=False, indent=2))



def add_document():
    try:
        collection = viking_kb_service.get_collection(collection_name, project=project_name)
        
        doc_id = "doc_test_manual_001"
        content = "Halo平台是一个基于Java的开源建站工具，支持多种数据库，具有强大的插件系统和主题系统。它的技术架构采用了Spring Boot框架，前端使用了Vue.js。"
        
        points = [
            {
                "doc_id": doc_id,
                "chunk_type": "text",
                "content": content,
                "chunk_title": "Halo平台简介"
            }
        ]
        
        # SDK 的 add_point 方法通常接受列表
        res = collection.add_point(points)
        print(f"add document (point) successfully: {json.dumps(res, ensure_ascii=False)}")
        
        # 从返回结果中提取 point_id
        # 返回结构示例: {"data": {"point_id": "..."}}
        # 注意: add_point 批量添加时可能返回列表或单个对象，需根据实际返回处理
        if isinstance(res, dict) and "data" in res:
             point_id = res["data"].get("point_id")
             print(f"Returned point_id: {point_id}")
             return point_id
        
        return None

    except Exception as e:
        print(f"add document failed: {e}")
        return None

def update_document(point_id):
    if not point_id:
        print("Skipping update_document: No point_id provided.")
        return

    try:
        collection = viking_kb_service.get_collection(collection_name, project=project_name)
        
        new_content = "Halo平台更新：Halo 2.0 引入了全新的插件机制，支持更灵活的扩展。前端架构升级为 Vue 3。"
        
        # SDK 的 update_point 方法
        print(f"Updating document with point_id: {point_id}")
        res = collection.update_point(point_id=point_id, content=new_content, chunk_title="Halo平台更新")
        print(f"update document result: {json.dumps(res, ensure_ascii=False)}")

    except Exception as e:
        print(f"update document failed: {e}")

def get_document():
    try:
        collection = viking_kb_service.get_collection(collection_name, project=project_name)
        # 假设通过 doc_id 获取
        # doc = collection.get_doc(doc_id="doc_test_001")
        # print(f"get document: {doc}")
        print("get_document function placeholder")
    except Exception as e:
        print(f"get document failed: {e}")

def delete_document():
    try:
        collection = viking_kb_service.get_collection(collection_name, project=project_name)
        # collection.delete_doc(doc_id="doc_test_001")
        print("delete_document function placeholder")
    except Exception as e:
        print(f"delete document failed: {e}")

if __name__ == "__main__":
    create_collection()
    list_collections()
    # delete_collection()
    get_collection()
    search_knowledge()
    
    # New demos
    add_document()
    get_document()
    delete_document()
