"""
Bid Writing Extension for PageIndex API

This module extends the PageIndex API with bid writing functionality:
- Project management (CRUD)
- Auto-save
- AI content generation
- Text rewriting
"""

from fastapi import APIRouter
from .routes import router as bid_router

__all__ = ['bid_router']
