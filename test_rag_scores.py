from services.rag_service import RagService

rag = RagService()
query1 = "What is Weave Scope?"
query2 = "Why do you?"

print(f"Results for '{query1}':")
# Langchain's Chroma similarity_search_with_score returns (doc, distance)
for doc, distance in rag.vector_store.similarity_search_with_score(query1, k=3):
    print(f" - Dist: {distance:.4f} | {doc.page_content[:50]}...")

print(f"\nResults for '{query2}':")
for doc, distance in rag.vector_store.similarity_search_with_score(query2, k=3):
    print(f" - Dist: {distance:.4f} | {doc.page_content[:50]}...")
