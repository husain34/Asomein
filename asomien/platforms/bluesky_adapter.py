"""
asomien/platforms/bluesky_adapter.py

Bluesky Platform Adapter using the atproto SDK.
"""

import logging
from typing import Any, Optional

from atproto import Client, models
from asomien.platforms.base_platform import BasePlatformAdapter

logger = logging.getLogger(__name__)

class BlueskyAdapter(BasePlatformAdapter):
    """Adapter for the Bluesky AT Protocol."""

    def __init__(
        self,
        handle: str,
        app_password: str,
    ) -> None:
        self.handle = handle
        self.client = Client()
        import time
        last_error = None
        for attempt in range(3):
            try:
                self.client.login(handle, app_password)
                last_error = None
                break
            except Exception as e:
                last_error = e
                logger.warning(f"[BlueskyAdapter] Login attempt {attempt+1}/3 failed: {e}")
                time.sleep(5)
        if last_error is not None:
            raise RuntimeError(f"[BlueskyAdapter] Failed to authenticate after 3 retries: {last_error}")

    def publish_text_post(self, text: str, **kwargs: Any) -> str:
        """Publish a root post. Returns the URI."""
        post = self.client.send_post(text=text)
        logger.info(f"Published Bluesky post: {post.uri}")
        return post.uri

    def publish_reply(self, text: str, parent_post_id: str, **kwargs: Any) -> str:
        """Publish a reply to an existing post. `parent_post_id` is the URI."""
        # 1. Fetch the parent post to get its CID and root reference
        thread = self.client.get_post_thread(uri=parent_post_id)
        parent_post = thread.thread.post
        
        parent_ref = models.ComAtprotoRepoStrongRef.Main(uri=parent_post.uri, cid=parent_post.cid)
        
        # Determine the root reference
        if hasattr(parent_post.record, 'reply') and parent_post.record.reply:
            root_ref = parent_post.record.reply.root
        else:
            root_ref = parent_ref
            
        reply_ref = models.AppBskyFeedPost.ReplyRef(
            parent=parent_ref,
            root=root_ref
        )
        
        post = self.client.send_post(text=text, reply_to=reply_ref)
        logger.info(f"Published Bluesky reply: {post.uri}")
        return post.uri

    def quote_post(self, text: str, uri: str, cid: str, **kwargs: Any) -> str:
        """Publish a quote post embedding an existing post."""
        embed = models.AppBskyEmbedRecord.Main(
            record=models.ComAtprotoRepoStrongRef.Main(
                cid=cid,
                uri=uri
            )
        )
        post = self.client.send_post(text=text, embed=embed)
        logger.info(f"Published Bluesky quote post: {post.uri}")
        return post.uri

    def delete_post(self, post_id: str, **kwargs: Any) -> bool:
        """Delete a post by URI."""
        try:
            rkey = post_id.split("/")[-1]
            self.client.com.atproto.repo.delete_record({
                'repo': self.client.me.did,
                'collection': 'app.bsky.feed.post',
                'rkey': rkey
            })
            return True
        except Exception as e:
            logger.error(f"Failed to delete Bluesky post: {e}")
            return False

    def get_post_metrics(self, post_id: str, **kwargs: Any) -> dict[str, Any]:
        """Fetch likes, replies, and reposts for a post by URI."""
        try:
            thread = self.client.get_post_thread(uri=post_id)
            post_data = thread.thread.post
            return {
                "likes": post_data.like_count or 0,
                "replies": post_data.reply_count or 0,
                "reposts": post_data.repost_count or 0,
                "quotes": post_data.quote_count or 0,
                "views": 0, # Bluesky doesn't expose views yet
                "shares": 0
            }
        except Exception as e:
            logger.warning(f"Failed to fetch metrics for {post_id}: {e}")
            return {}

    def get_audience_insights(self, **kwargs: Any) -> dict[str, Any]:
        """Fetch follower count."""
        try:
            profile = self.client.get_profile(actor=self.handle)
            return {
                "followers_count": profile.followers_count or 0
            }
        except Exception as e:
            logger.warning(f"Failed to fetch audience insights: {e}")
            return {}

    def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        """Fetch the basic profile."""
        try:
            profile = self.client.get_profile(actor=self.handle)
            return {
                "id": profile.did,
                "username": profile.handle,
                "name": profile.display_name
            }
        except Exception as e:
            logger.error(f"Failed to fetch profile: {e}")
            return {}

    def get_user_profile(self, actor: str) -> dict[str, Any]:
        """Fetch a specific user's profile including their bio/description."""
        try:
            profile = self.client.get_profile(actor=actor)
            return {
                "did": profile.did,
                "handle": profile.handle,
                "description": getattr(profile, 'description', "") or ""
            }
        except Exception as e:
            logger.warning(f"Failed to fetch profile for {actor}: {e}")
            return {"did": actor, "handle": "", "description": ""}

    def get_publishing_quota(self, **kwargs: Any) -> dict[str, Any]:
        """Bluesky write limit is 35k/day, effectively limitless for this bot."""
        return {"quota": "limitless"}

    def get_post_replies(self, post_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch top-level replies for the Engagement Agent."""
        try:
            thread = self.client.get_post_thread(uri=post_id)
            replies = []
            if hasattr(thread.thread, 'replies') and thread.thread.replies:
                for reply in thread.thread.replies:
                    # Exclude our own replies
                    if reply.post.author.handle != self.handle:
                        images = self.get_post_images_base64(reply.post)
                        replies.append({
                            "id": reply.post.uri,
                            "text": reply.post.record.text,
                            "author": reply.post.author.handle,
                            "images": images
                        })
            return replies
        except Exception as e:
            logger.warning(f"Failed to fetch replies for {post_id}: {e}")
            return []

    def get_followers(self, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch a list of followers."""
        try:
            response = self.client.get_followers(actor=self.handle, limit=limit)
            return [
                {
                    "did": f.did,
                    "handle": f.handle,
                    "viewer_following": getattr(f.viewer, 'following', None) if f.viewer else None
                }
                for f in response.followers
            ]
        except Exception as e:
            logger.warning(f"Failed to fetch followers: {e}")
            return []

    def follow(self, did: str) -> bool:
        """Follow a user by DID."""
        try:
            self.client.follow(did)
            logger.info(f"Followed user: {did}")
            return True
        except Exception as e:
            logger.error(f"Failed to follow user {did}: {e}")
            return False

    def unfollow(self, did: str) -> bool:
        """Unfollow a user by their DID."""
        try:
            profile = self.client.get_profile(did)
            follow_uri = profile.viewer.following if profile.viewer else None
            if follow_uri:
                self.client.delete_follow(follow_uri)
                logger.info(f"Unfollowed user: {did}")
                return True
            logger.warning(f"Could not find follow record for {did}")
            return False
        except Exception as e:
            logger.error(f"Failed to unfollow user {did}: {e}")
            return False

    def get_timeline(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch the home timeline (posts from people we follow)."""
        try:
            feed = self.client.get_timeline(limit=limit).feed
            posts = []
            for item in feed:
                post = item.post
                # Only grab posts with text, ignoring our own posts
                if post.author.handle != self.handle and hasattr(post.record, 'text') and post.record.text:
                    posts.append({
                        "uri": post.uri,
                        "cid": post.cid,
                        "author": post.author.handle,
                        "text": post.record.text
                    })
            return posts
        except Exception as e:
            logger.warning(f"Failed to fetch timeline: {e}")
            return []

    def like_post(self, uri: str, cid: str) -> bool:
        """Like a post by URI and CID."""
        try:
            self.client.like(uri=uri, cid=cid)
            logger.info(f"Liked post: {uri}")
            return True
        except Exception as e:
            logger.error(f"Failed to like post {uri}: {e}")
            return False

    def get_post_images_base64(self, post: Any) -> list[str]:
        """Extract and download base64 images from a post's embed."""
        import base64
        import urllib.request
        b64_images = []
        try:
            embed = getattr(post.record, 'embed', None)
            if embed and hasattr(embed, 'images'):
                for img_obj in embed.images:
                    cid = getattr(img_obj.image.ref, 'link', None)
                    if cid:
                        url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{post.author.did}/{cid}@jpeg"
                        try:
                            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=10) as response:
                                img_data = response.read()
                                b64_images.append(base64.b64encode(img_data).decode('utf-8'))
                        except Exception as e:
                            logger.warning(f"Failed to download image {url}: {e}")
        except Exception as e:
            logger.warning(f"Failed to process images for post {post.uri}: {e}")
        return b64_images

    def search_global_posts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Bluesky globally for posts matching a keyword."""
        try:
            results = self.client.app.bsky.feed.search_posts(params={'q': query, 'limit': limit, 'sort': 'top'})
            posts = []
            for post in results.posts:
                # Ignore our own posts and replies
                if post.author.handle != self.handle and hasattr(post.record, 'text') and post.record.text:
                    if getattr(post.record, 'reply', None) is not None:
                        continue
                    
                    # In atproto SDK, $type is exposed as py_type or via model_dump()
                    embed_obj = post.record.embed if hasattr(post.record, 'embed') and post.record.embed else None
                    embed_type = ""
                    if embed_obj:
                        embed_type = getattr(embed_obj, 'py_type', '') or getattr(embed_obj, '$type', '')
                        if not embed_type and hasattr(embed_obj, 'model_dump'):
                            embed_type = embed_obj.model_dump().get('$type', '')
                    if embed_type in ['app.bsky.embed.video', 'app.bsky.embed.external']:
                        continue
                        
                    # Extract quoted text if it's a quote tweet
                    quoted_text = ""
                    if embed_type in ['app.bsky.embed.record', 'app.bsky.embed.recordWithMedia']:
                        try:
                            # Try to extract the text from the hydrated record embed
                            if hasattr(post, 'embed') and post.embed:
                                record = getattr(post.embed, 'record', None)
                                if hasattr(record, 'record'):  # Sometimes it's nested
                                    record = record.record
                                if hasattr(record, 'value') and hasattr(record.value, 'text'):
                                    quoted_text = f"\n[Quoted Post]: {record.value.text}"
                        except Exception as e:
                            logger.warning(f"Failed to extract quote text: {e}")

                    b64_images = self.get_post_images_base64(post)
                    
                    full_text = post.record.text + quoted_text
                    
                    posts.append({
                        "uri": post.uri,
                        "cid": post.cid,
                        "author": post.author.handle,
                        "author_did": post.author.did,
                        "text": full_text,
                        "images": b64_images,
                        "likes": getattr(post, 'like_count', 0) or 0,
                        "replies": getattr(post, 'reply_count', 0) or 0
                    })
            return posts
        except Exception as e:
            logger.exception(f"Failed to search global posts for '{query}': {e}")
            return []

    def create_starter_pack(self, name: str, description: str, dids: list[str]) -> str:
        """Create a Bluesky Starter Pack containing the given DIDs."""
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            
            # 1. Create the List record
            list_record = models.AppBskyGraphList.Record(
                name=name,
                purpose="app.bsky.graph.defs#curatelist",
                description=description,
                created_at=now
            )
            list_response = self.client.com.atproto.repo.create_record({
                'repo': self.client.me.did,
                'collection': 'app.bsky.graph.list',
                'record': list_record
            })
            list_uri = list_response.uri
            
            # 2. Add members to the list
            for did in dids:
                try:
                    item_record = models.AppBskyGraphListitem.Record(
                        subject=did,
                        list=list_uri,
                        created_at=now
                    )
                    self.client.com.atproto.repo.create_record({
                        'repo': self.client.me.did,
                        'collection': 'app.bsky.graph.listitem',
                        'record': item_record
                    })
                except Exception as e:
                    logger.warning(f"Failed to add {did} to starter pack list: {e}")
            
            # 3. Create the Starter Pack record
            sp_record = models.AppBskyGraphStarterpack.Record(
                name=name,
                description=description,
                list=list_uri,
                created_at=now
            )
            sp_response = self.client.com.atproto.repo.create_record({
                'repo': self.client.me.did,
                'collection': 'app.bsky.graph.starterpack',
                'record': sp_record
            })
            
            logger.info(f"Successfully created Starter Pack: {sp_response.uri}")
            return sp_response.uri
            
        except Exception as e:
            logger.error(f"Failed to create Starter Pack: {e}")
            return ""
