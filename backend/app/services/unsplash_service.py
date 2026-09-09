"""Unsplash图片服务"""

import requests
from typing import List, Optional
from ..config import get_settings
from ..errors import ConfigurationError, UpstreamError, UpstreamTimeout

class UnsplashService:
    """Unsplash图片服务类"""
    
    def __init__(self):
        """初始化服务"""
        settings = get_settings()
        self.access_key = settings.unsplash_access_key.get_secret_value()
        self.base_url = "https://api.unsplash.com"
    
    def search_photos(self, query: str, per_page: int = 5) -> List[dict]:
        """
        搜索图片
        
        Args:
            query: 搜索关键词
            per_page: 每页数量
            
        Returns:
            图片列表
        """
        if not self.access_key.strip():
            raise ConfigurationError()
        try:
            url = f"{self.base_url}/search/photos"
            params = {
                "query": query,
                "per_page": per_page
            }
            
            response = requests.get(url, params=params, headers={"Authorization": f"Client-ID {self.access_key}"}, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            
            # 提取图片URL
            photos = []
            for photo in results:
                photos.append({
                    "id": photo.get("id"),
                    "url": photo.get("urls", {}).get("regular"),
                    "thumb": photo.get("urls", {}).get("thumb"),
                    "description": photo.get("description") or photo.get("alt_description"),
                    "photographer": photo.get("user", {}).get("name")
                })
            
            return photos
            
        except requests.Timeout as exc:
            raise UpstreamTimeout() from exc
        except Exception as exc:
            raise UpstreamError() from exc
    
    def get_photo_url(self, query: str) -> Optional[str]:
        """
        获取单张图片URL

        Args:
            query: 搜索关键词

        Returns:
            图片URL
        """
        photos = self.search_photos(query, per_page=1)
        if photos:
            return photos[0].get("url")
        return None


def get_unsplash_service() -> UnsplashService:
    # No persistent session/client; cheap request-local configuration holder.
    return UnsplashService()
