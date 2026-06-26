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
        for _ in range(3):
            try:
                self.client.login(handle, app_password)
                break
            except Exception as e:
                logger.warning(f"[BlueskyAdapter] Login timeout/error, retrying: {e}")
                time.sleep(5)

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
                        replies.append({
                            "id": reply.post.uri,
                            "text": reply.post.record.text,
                            "author": reply.post.author.handle
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

    def search_global_posts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search Bluesky globally for posts matching a keyword."""
        try:
            results = self.client.app.bsky.feed.search_posts(params={'q': query, 'limit': limit})
            posts = []
            for post in results.posts:
                # Ignore our own posts and replies
                if post.author.handle != self.handle and hasattr(post.record, 'text') and post.record.text:
                    if getattr(post.record, 'reply', None) is not None:
                        continue
                    posts.append({
                        "uri": post.uri,
                        "cid": post.cid,
                        "author": post.author.handle,
                        "author_did": post.author.did,
                        "text": post.record.text
                    })
            return posts
        except Exception as e:
            logger.warning(f"Failed to search global posts for '{query}': {e}")
            return []
