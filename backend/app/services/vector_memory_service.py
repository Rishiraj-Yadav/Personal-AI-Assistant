"""
Vector Memory Service - Semantic Search with Qdrant
FIXED: Lazy loading + retry logic
"""
import os
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from loguru import logger
import numpy as np

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue
)


class VectorMemoryService:
    """
    Manages semantic memory storage and retrieval using Qdrant
    FIXED: Lazy initialization to avoid startup errors
    """
    
    def __init__(self):
        # ✅ LAZY INIT: Don't connect immediately
        self.qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self._client = None
        self._embedder = None
        self.embedding_dim = 384
        
        # Collection names
        self.MESSAGES_COLLECTION = "user_messages"
        self.INSIGHTS_COLLECTION = "user_insights"
        
        logger.info("✅ Vector Memory Service initialized (lazy loading)")
    
    @property
    def client(self):
        """Lazy load Qdrant client with retry"""
        if self._client is None:
            self._client = self._connect_with_retry()
        return self._client
    
    @property
    def embedder(self):
        """Lazy load embedding model"""
        if self._embedder is None:
            logger.info("🔄 Loading sentence-transformers model...")
            self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding model loaded")
        return self._embedder
    
    def _connect_with_retry(self, max_retries=5, delay=2):
        """Connect to Qdrant with retry logic"""
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 Connecting to Qdrant at {self.qdrant_url} (attempt {attempt + 1}/{max_retries})")
                client = QdrantClient(url=self.qdrant_url)
                
                # Test connection
                client.get_collections()
                
                # Initialize collections
                self._init_collections_internal(client)
                
                logger.info("✅ Connected to Qdrant successfully")
                return client
            
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Qdrant connection failed (attempt {attempt + 1}): {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"❌ Failed to connect to Qdrant after {max_retries} attempts")
                    raise
    
    def _init_collections_internal(self, client):
        """Create Qdrant collections if they don't exist"""
        try:
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            # Messages collection
            if self.MESSAGES_COLLECTION not in collection_names:
                client.create_collection(
                    collection_name=self.MESSAGES_COLLECTION,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"✅ Created collection: {self.MESSAGES_COLLECTION}")
            
            # Insights collection
            if self.INSIGHTS_COLLECTION not in collection_names:
                client.create_collection(
                    collection_name=self.INSIGHTS_COLLECTION,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"✅ Created collection: {self.INSIGHTS_COLLECTION}")
        
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize collections: {e}")
    
    def embed_text(self, text: str) -> List[float]:
        """Convert text to embedding vector"""
        embedding = self.embedder.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def store_message(
        self,
        user_id: str,
        message_id: int,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ):
        """Store message in vector database"""
        # Only store user messages
        if role != 'user':
            return
        
        try:
            # Generate embedding
            vector = self.embed_text(content)
            
            # Create point
            point = PointStruct(
                id=message_id,
                vector=vector,
                payload={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'role': role,
                    'content': content,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metadata': metadata or {}
                }
            )
            
            # Store in Qdrant
            self.client.upsert(
                collection_name=self.MESSAGES_COLLECTION,
                points=[point]
            )
            
            logger.debug(f"💾 Stored message {message_id} in vector DB")
        
        except Exception as e:
            logger.error(f"❌ Error storing message vector: {e}")
    
    def store_insight(
        self,
        user_id: str,
        insight_type: str,
        content: str,
        metadata: Dict = None
    ):
        """Store extracted insight"""
        try:
            insight_id = hash(f"{user_id}_{insight_type}_{content}_{datetime.now().timestamp()}")
            vector = self.embed_text(content)
            
            point = PointStruct(
                id=insight_id,
                vector=vector,
                payload={
                    'user_id': user_id,
                    'insight_type': insight_type,
                    'content': content,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metadata': metadata or {}
                }
            )
            
            self.client.upsert(
                collection_name=self.INSIGHTS_COLLECTION,
                points=[point]
            )
            
            logger.debug(f"🧠 Stored insight: {insight_type}")
        
        except Exception as e:
            logger.error(f"❌ Error storing insight: {e}")
    
    def search_similar_messages(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        score_threshold: float = 0.7
    ) -> List[Dict]:
        """Find semantically similar past messages"""
        try:
            query_vector = self.embed_text(query)
            
            results = self.client.search(
                collection_name=self.MESSAGES_COLLECTION,
                query_vector=query_vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                ),
                limit=limit,
                score_threshold=score_threshold
            )
            
            similar_messages = []
            for result in results:
                similar_messages.append({
                    'content': result.payload['content'],
                    'conversation_id': result.payload['conversation_id'],
                    'timestamp': result.payload['timestamp'],
                    'similarity_score': result.score,
                    'metadata': result.payload.get('metadata', {})
                })
            
            logger.debug(f"🔍 Found {len(similar_messages)} similar messages")
            return similar_messages
        
        except Exception as e:
            logger.error(f"❌ Error searching messages: {e}")
            return []
    
    def search_insights(
        self,
        user_id: str,
        query: str,
        insight_types: List[str] = None,
        limit: int = 3
    ) -> List[Dict]:
        """Find relevant insights"""
        try:
            query_vector = self.embed_text(query)
            
            filter_conditions = [
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id)
                )
            ]
            
            if insight_types:
                filter_conditions.append(
                    FieldCondition(
                        key="insight_type",
                        match=MatchValue(value=insight_types)
                    )
                )
            
            results = self.client.search(
                collection_name=self.INSIGHTS_COLLECTION,
                query_vector=query_vector,
                query_filter=Filter(must=filter_conditions),
                limit=limit
            )
            
            insights = []
            for result in results:
                insights.append({
                    'type': result.payload['insight_type'],
                    'content': result.payload['content'],
                    'similarity_score': result.score,
                    'metadata': result.payload.get('metadata', {})
                })
            
            logger.debug(f"🧠 Found {len(insights)} relevant insights")
            return insights
        
        except Exception as e:
            logger.error(f"❌ Error searching insights: {e}")
            return []
    
    def get_user_context(
        self,
        user_id: str,
        current_query: str,
        include_messages: bool = True,
        include_insights: bool = True
    ) -> Dict:
        """Build comprehensive context for current query"""
        context = {
            'query': current_query,
            'similar_messages': [],
            'insights': []
        }
        
        if include_messages:
            context['similar_messages'] = self.search_similar_messages(
                user_id, current_query, limit=3
            )
        
        if include_insights:
            context['insights'] = self.search_insights(
                user_id, current_query, limit=3
            )
        
        return context
    
    def extract_and_store_insights(
        self,
        user_id: str,
        conversation_messages: List[Dict]
    ):
        """Extract insights from conversation"""
        user_messages = [
            msg for msg in conversation_messages 
            if msg.get('role') == 'user'
        ]
        
        for msg in user_messages:
            content = msg.get('content', '').lower()
            
            # Extract language preferences
            if 'love' in content or 'prefer' in content or 'like' in content:
                for lang in ['python', 'javascript', 'typescript', 'java', 'go', 'rust']:
                    if lang in content:
                        self.store_insight(
                            user_id=user_id,
                            insight_type='preference',
                            content=f"User prefers {lang} programming language",
                            metadata={'extracted_from': msg.get('content')[:100]}
                        )
            
            # Extract framework preferences
            for framework in ['react', 'vue', 'angular', 'flask', 'django', 'fastapi']:
                if framework in content:
                    self.store_insight(
                        user_id=user_id,
                        insight_type='preference',
                        content=f"User uses {framework} framework",
                        metadata={'extracted_from': msg.get('content')[:100]}
                    )
    
    def get_stats(self, user_id: str) -> Dict:
        """Get statistics about user's vector memory"""
        try:
            message_count = self.client.count(
                collection_name=self.MESSAGES_COLLECTION,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                )
            )
            
            insight_count = self.client.count(
                collection_name=self.INSIGHTS_COLLECTION,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                )
            )
            
            return {
                'total_messages': message_count.count,
                'total_insights': insight_count.count
            }
        
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {'total_messages': 0, 'total_insights': 0}


# Global instance
vector_memory = VectorMemoryService()