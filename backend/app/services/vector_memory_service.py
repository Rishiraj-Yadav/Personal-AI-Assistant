"""
Vector Memory Service - Persistent Semantic Memory with Qdrant
Stores ALL messages (user + assistant), insights, and user facts
Provides cross-conversation context retrieval for SonarBot
"""
import os
import time
import uuid
from typing import List, Dict, Optional
from datetime import datetime, timezone
from loguru import logger

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    PayloadSchemaType
)


def _generate_point_id() -> int:
    """Generate a unique positive integer ID for Qdrant points"""
    return int(uuid.uuid4().int >> 64)


class VectorMemoryService:
    """
    Persistent semantic memory using Qdrant.
    
    Collections:
    - user_messages: All conversation messages (user + assistant + exchanges)
    - user_insights: Extracted facts, preferences, and summaries about users
    """
    
    def __init__(self):
        self.qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        self._client = None
        self._embedder = None
        self.embedding_dim = 384  # all-MiniLM-L6-v2 output dimension
        
        self.MESSAGES_COLLECTION = "user_messages"
        self.INSIGHTS_COLLECTION = "user_insights"
        
        logger.info("✅ Vector Memory Service initialized (lazy loading)")
    
    @property
    def client(self) -> QdrantClient:
        """Lazy load Qdrant client with retry"""
        if self._client is None:
            self._client = self._connect_with_retry()
        return self._client
    
    @property
    def embedder(self) -> SentenceTransformer:
        """Lazy load embedding model"""
        if self._embedder is None:
            logger.info("🔄 Loading sentence-transformers model...")
            self._embedder = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("✅ Embedding model loaded")
        return self._embedder
    
    def _connect_with_retry(self, max_retries=5, delay=2) -> QdrantClient:
        """Connect to Qdrant with retry logic"""
        for attempt in range(max_retries):
            try:
                logger.info(f"🔄 Connecting to Qdrant at {self.qdrant_url} (attempt {attempt + 1}/{max_retries})")
                client = QdrantClient(url=self.qdrant_url, timeout=10)
                client.get_collections()
                self._init_collections(client)
                logger.info("✅ Connected to Qdrant successfully")
                return client
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ Qdrant connection failed (attempt {attempt + 1}): {e}")
                    time.sleep(delay)
                else:
                    logger.error(f"❌ Failed to connect to Qdrant after {max_retries} attempts")
                    raise
    
    def _init_collections(self, client: QdrantClient):
        """Create Qdrant collections if they don't exist"""
        try:
            collections = client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.MESSAGES_COLLECTION not in collection_names:
                client.create_collection(
                    collection_name=self.MESSAGES_COLLECTION,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                client.create_payload_index(
                    collection_name=self.MESSAGES_COLLECTION,
                    field_name="user_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                client.create_payload_index(
                    collection_name=self.MESSAGES_COLLECTION,
                    field_name="conversation_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                client.create_payload_index(
                    collection_name=self.MESSAGES_COLLECTION,
                    field_name="role",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                logger.info(f"✅ Created collection: {self.MESSAGES_COLLECTION}")
            
            if self.INSIGHTS_COLLECTION not in collection_names:
                client.create_collection(
                    collection_name=self.INSIGHTS_COLLECTION,
                    vectors_config=VectorParams(
                        size=self.embedding_dim,
                        distance=Distance.COSINE
                    )
                )
                client.create_payload_index(
                    collection_name=self.INSIGHTS_COLLECTION,
                    field_name="user_id",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                client.create_payload_index(
                    collection_name=self.INSIGHTS_COLLECTION,
                    field_name="insight_type",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                logger.info(f"✅ Created collection: {self.INSIGHTS_COLLECTION}")
        
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize collections: {e}")
    
    # ============ EMBEDDING ============
    
    def embed_text(self, text: str) -> List[float]:
        """Convert text to embedding vector"""
        embedding = self.embedder.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    # ============ MESSAGE STORAGE ============
    
    def store_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Dict = None
    ):
        """
        Store ANY message (user or assistant) in vector database.
        Both roles are stored for full context retrieval.
        """
        if not content or not content.strip():
            return
        
        try:
            vector = self.embed_text(content)
            point_id = _generate_point_id()
            
            point = PointStruct(
                id=point_id,
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
            
            self.client.upsert(
                collection_name=self.MESSAGES_COLLECTION,
                points=[point]
            )
            
            logger.debug(f"💾 Stored {role} message in vector DB")
        
        except Exception as e:
            logger.error(f"❌ Error storing message vector: {e}")
    
    def store_conversation_pair(
        self,
        user_id: str,
        conversation_id: str,
        user_message: str,
        assistant_response: str,
        metadata: Dict = None
    ):
        """
        Store a user+assistant exchange as a combined entry.
        This makes semantic search much more effective for retrieving full context.
        """
        if not user_message or not assistant_response:
            return
        
        try:
            combined = f"User asked: {user_message}\nAssistant answered: {assistant_response[:500]}"
            vector = self.embed_text(combined)
            point_id = _generate_point_id()
            
            point = PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    'user_id': user_id,
                    'conversation_id': conversation_id,
                    'role': 'exchange',
                    'content': combined,
                    'user_message': user_message,
                    'assistant_response': assistant_response[:2000],
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'metadata': metadata or {}
                }
            )
            
            self.client.upsert(
                collection_name=self.MESSAGES_COLLECTION,
                points=[point]
            )
            
            logger.debug(f"💾 Stored conversation pair in vector DB")
        
        except Exception as e:
            logger.error(f"❌ Error storing conversation pair: {e}")
    
    # ============ INSIGHT STORAGE ============
    
    def store_insight(
        self,
        user_id: str,
        insight_type: str,
        content: str,
        metadata: Dict = None
    ):
        """
        Store extracted insight/fact about user.
        insight_type: 'user_fact', 'preference', 'summary', 'behavior'
        """
        if not content or not content.strip():
            return
        
        try:
            vector = self.embed_text(content)
            point_id = _generate_point_id()
            
            point = PointStruct(
                id=point_id,
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
            
            logger.debug(f"🧠 Stored insight: {insight_type} - {content[:50]}")
        
        except Exception as e:
            logger.error(f"❌ Error storing insight: {e}")
    
    # ============ SEARCH / RETRIEVAL ============
    
    def search_similar_messages(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        score_threshold: float = 0.3
    ) -> List[Dict]:
        """
        Find semantically similar past messages across ALL conversations.
        Threshold 0.3 ensures we catch more relevant context.
        """
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
                    'content': result.payload.get('content', ''),
                    'user_message': result.payload.get('user_message', ''),
                    'assistant_response': result.payload.get('assistant_response', ''),
                    'role': result.payload.get('role', ''),
                    'conversation_id': result.payload.get('conversation_id', ''),
                    'timestamp': result.payload.get('timestamp', ''),
                    'similarity_score': result.score,
                    'metadata': result.payload.get('metadata', {})
                })
            
            logger.debug(f"🔍 Found {len(similar_messages)} similar messages for user {user_id}")
            return similar_messages
        
        except Exception as e:
            logger.error(f"❌ Error searching messages: {e}")
            return []
    
    def search_insights(
        self,
        user_id: str,
        query: str,
        insight_type: str = None,
        limit: int = 5,
        score_threshold: float = 0.2
    ) -> List[Dict]:
        """Find relevant insights about the user"""
        try:
            query_vector = self.embed_text(query)
            
            filter_conditions = [
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=user_id)
                )
            ]
            
            if insight_type:
                filter_conditions.append(
                    FieldCondition(
                        key="insight_type",
                        match=MatchValue(value=insight_type)
                    )
                )
            
            results = self.client.search(
                collection_name=self.INSIGHTS_COLLECTION,
                query_vector=query_vector,
                query_filter=Filter(must=filter_conditions),
                limit=limit,
                score_threshold=score_threshold
            )
            
            insights = []
            for result in results:
                insights.append({
                    'type': result.payload.get('insight_type', ''),
                    'content': result.payload.get('content', ''),
                    'similarity_score': result.score,
                    'timestamp': result.payload.get('timestamp', ''),
                    'metadata': result.payload.get('metadata', {})
                })
            
            logger.debug(f"🧠 Found {len(insights)} relevant insights")
            return insights
        
        except Exception as e:
            logger.error(f"❌ Error searching insights: {e}")
            return []
    
    def get_all_user_insights(self, user_id: str, limit: int = 50) -> List[Dict]:
        """Get ALL stored insights for a user (scroll-based, not similarity)"""
        try:
            results, _ = self.client.scroll(
                collection_name=self.INSIGHTS_COLLECTION,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                ),
                limit=limit
            )
            
            insights = []
            for point in results:
                insights.append({
                    'type': point.payload.get('insight_type', ''),
                    'content': point.payload.get('content', ''),
                    'timestamp': point.payload.get('timestamp', ''),
                    'metadata': point.payload.get('metadata', {})
                })
            
            return insights
        
        except Exception as e:
            logger.error(f"❌ Error getting all insights: {e}")
            return []
    
    def get_recent_user_messages(self, user_id: str, limit: int = 20) -> List[Dict]:
        """Get recent messages for a user across ALL conversations"""
        try:
            results, _ = self.client.scroll(
                collection_name=self.MESSAGES_COLLECTION,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="user_id",
                            match=MatchValue(value=user_id)
                        )
                    ]
                ),
                limit=limit
            )
            
            messages = []
            for point in results:
                messages.append({
                    'content': point.payload.get('content', ''),
                    'role': point.payload.get('role', ''),
                    'conversation_id': point.payload.get('conversation_id', ''),
                    'timestamp': point.payload.get('timestamp', ''),
                })
            
            messages.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            return messages[:limit]
        
        except Exception as e:
            logger.error(f"❌ Error getting recent messages: {e}")
            return []
    
    # ============ CONTEXT BUILDING ============
    
    def get_user_context(
        self,
        user_id: str,
        current_query: str,
        include_messages: bool = True,
        include_insights: bool = True
    ) -> Dict:
        """Build comprehensive context for current query from ALL past conversations"""
        context = {
            'query': current_query,
            'similar_messages': [],
            'insights': [],
            'all_insights': []
        }
        
        if include_messages:
            context['similar_messages'] = self.search_similar_messages(
                user_id, current_query, limit=5, score_threshold=0.3
            )
        
        if include_insights:
            context['insights'] = self.search_insights(
                user_id, current_query, limit=5, score_threshold=0.2
            )
            context['all_insights'] = self.get_all_user_insights(user_id, limit=30)
        
        return context
    
    # ============ FACT EXTRACTION ============
    
    def extract_and_store_facts(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str
    ):
        """
        Extract facts/preferences from a conversation exchange and store as insights.
        Runs after each message to build up a persistent user profile.
        """
        try:
            content_lower = user_message.lower()
            
            # Extract self-identification (name, role, etc.)
            name_triggers = [
                'my name is ', 'i am ', "i'm ", 'call me ', 'name is ',
                'this is ', 'i go by '
            ]
            for trigger in name_triggers:
                if trigger in content_lower:
                    idx = content_lower.find(trigger) + len(trigger)
                    name_candidate = user_message[idx:idx+50].strip()
                    # Clean up
                    for sep in ['.', ',', '!', '?', ' and ', ' but ']:
                        name_candidate = name_candidate.split(sep)[0]
                    name_candidate = name_candidate.strip()
                    if name_candidate and 1 < len(name_candidate) < 50:
                        self.store_insight(
                            user_id=user_id,
                            insight_type='user_fact',
                            content=f"User's name is {name_candidate}",
                            metadata={'source': 'self_identification', 'original': user_message[:100]}
                        )
                        break
            
            # Extract preferences
            pref_triggers = ['i like ', 'i love ', 'i prefer ', 'i use ', 'i work with ',
                           'i usually ', 'my favorite ', 'i enjoy ', 'i want ']
            for trigger in pref_triggers:
                if trigger in content_lower:
                    idx = content_lower.find(trigger)
                    pref_text = user_message[idx:idx+100].strip()
                    for sep in ['.', '!', '?']:
                        pref_text = pref_text.split(sep)[0]
                    if pref_text:
                        self.store_insight(
                            user_id=user_id,
                            insight_type='preference',
                            content=f"User preference: {pref_text}",
                            metadata={'source': 'explicit_preference'}
                        )
            
            # Extract tech stack mentions
            languages = ['python', 'javascript', 'typescript', 'java', 'c++', 'c#',
                        'go', 'rust', 'ruby', 'php', 'swift', 'kotlin']
            frameworks = ['react', 'vue', 'angular', 'nextjs', 'flask', 'django',
                         'fastapi', 'express', 'spring', 'laravel', 'rails']
            
            for lang in languages:
                if lang in content_lower and any(kw in content_lower for kw in
                    ['write', 'code', 'build', 'create', 'use', 'prefer', 'work']):
                    self.store_insight(
                        user_id=user_id,
                        insight_type='preference',
                        content=f"User works with {lang} programming language",
                        metadata={'source': 'inferred_from_conversation'}
                    )
            
            for fw in frameworks:
                if fw in content_lower:
                    self.store_insight(
                        user_id=user_id,
                        insight_type='preference',
                        content=f"User uses {fw} framework",
                        metadata={'source': 'inferred_from_conversation'}
                    )
            
            # Extract location/context clues
            location_triggers = ['i live in ', 'i am from ', "i'm from ", 'based in ',
                               'i work at ', 'i study at ', 'my company ']
            for trigger in location_triggers:
                if trigger in content_lower:
                    idx = content_lower.find(trigger)
                    fact = user_message[idx:idx+80].strip()
                    for sep in ['.', '!', '?']:
                        fact = fact.split(sep)[0]
                    if fact:
                        self.store_insight(
                            user_id=user_id,
                            insight_type='user_fact',
                            content=f"User context: {fact}",
                            metadata={'source': 'self_disclosure'}
                        )
        
        except Exception as e:
            logger.error(f"❌ Error extracting facts: {e}")

    # ============ STATISTICS ============
    
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
