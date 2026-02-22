"""
Vector Memory Service - Semantic Search with Qdrant
Enables context-aware memory retrieval
"""
import os
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
    """
    
    def __init__(self):
        # Connect to Qdrant
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self.client = QdrantClient(url=qdrant_url)
        
        # Initialize embedding model (lightweight, fast)
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
        self.embedding_dim = 384
        
        # Collection names
        self.MESSAGES_COLLECTION = "user_messages"
        self.INSIGHTS_COLLECTION = "user_insights"
        
        # Initialize collections
        self._init_collections()
        
        logger.info("✅ Vector Memory Service initialized with Qdrant")
    
    def _init_collections(self):
        """Create Qdrant collections if they don't exist"""
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        # Messages collection: stores all user messages with metadata
        if self.MESSAGES_COLLECTION not in collection_names:
            self.client.create_collection(
                collection_name=self.MESSAGES_COLLECTION,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"✅ Created collection: {self.MESSAGES_COLLECTION}")
        
        # Insights collection: stores extracted insights/preferences
        if self.INSIGHTS_COLLECTION not in collection_names:
            self.client.create_collection(
                collection_name=self.INSIGHTS_COLLECTION,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                )
            )
            logger.info(f"✅ Created collection: {self.INSIGHTS_COLLECTION}")
    
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
        """
        Store message in vector database
        
        Args:
            user_id: User identifier
            message_id: Unique message ID from SQL database
            conversation_id: Conversation ID
            role: 'user' or 'assistant'
            content: Message content
            metadata: Additional metadata
        """
        # Only store user messages (not assistant responses)
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
        """
        Store extracted insight (preference, pattern, learned fact)
        
        Args:
            user_id: User identifier
            insight_type: 'preference', 'pattern', 'correction', 'fact'
            content: The insight text
            metadata: Additional data
        """
        try:
            # Generate unique ID
            insight_id = hash(f"{user_id}_{insight_type}_{content}_{datetime.now().timestamp()}")
            
            # Generate embedding
            vector = self.embed_text(content)
            
            # Create point
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
            
            # Store in Qdrant
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
        """
        Find semantically similar past messages
        
        Args:
            user_id: User identifier
            query: Search query
            limit: Maximum results
            score_threshold: Minimum similarity score
            
        Returns:
            List of similar messages with scores
        """
        try:
            # Generate query embedding
            query_vector = self.embed_text(query)
            
            # Search with user filter
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
            
            # Format results
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
        """
        Find relevant insights for context
        
        Args:
            user_id: User identifier
            query: Search query
            insight_types: Filter by types (preference, pattern, etc.)
            limit: Maximum results
            
        Returns:
            List of relevant insights
        """
        try:
            # Generate query embedding
            query_vector = self.embed_text(query)
            
            # Build filter
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
            
            # Search
            results = self.client.search(
                collection_name=self.INSIGHTS_COLLECTION,
                query_vector=query_vector,
                query_filter=Filter(must=filter_conditions),
                limit=limit
            )
            
            # Format results
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
        """
        Build comprehensive context for current query
        
        Args:
            user_id: User identifier
            current_query: User's current message
            include_messages: Include similar past messages
            include_insights: Include relevant insights
            
        Returns:
            Dict with semantic context
        """
        context = {
            'query': current_query,
            'similar_messages': [],
            'insights': []
        }
        
        # Get similar past messages
        if include_messages:
            context['similar_messages'] = self.search_similar_messages(
                user_id, current_query, limit=3
            )
        
        # Get relevant insights
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
        """
        Extract insights from conversation and store them
        
        This should be called periodically or after important conversations
        
        Args:
            user_id: User identifier
            conversation_messages: Recent messages from conversation
        """
        # Simple insight extraction (can be enhanced with LLM)
        user_messages = [
            msg for msg in conversation_messages 
            if msg.get('role') == 'user'
        ]
        
        # Look for explicit preferences
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
            # Count messages
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
            
            # Count insights
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